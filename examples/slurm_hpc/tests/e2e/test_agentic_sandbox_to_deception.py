"""E2E test: Sandbox script generation + submission to Deception via agentic-cli.

This test validates the full ADEPT agentic workflow:
1. Authenticate with the ADEPT gateway (Keycloak JWT)
2. Send a prompt via the Response API asking the agent to:
   a. Generate a hello-world Slurm batch script (using sandbox code execution)
   b. Save the script to the uploaded_files shared volume
      (data/uploaded_files/{mcp_session_id}/) so it is readable by the
      slurm_hpc job submission tool via the shared_uploads Docker volume
   c. Submit that script to PNNL's Deception cluster (using deception_submit_job)
3. Poll the conversation until the agent reports the job was submitted
4. Verify the agent's response contains a valid Slurm job ID
5. (Optional) Poll job status via deception_get_job_details until completion

Volume architecture:
  orchestration_service writes → shared_uploads:/app/data/uploaded_files (rw)
  slurm_mcp_server reads      → shared_uploads:/app/data/uploaded_files (ro)

GUARDED: Requires ALL of:
- AGENTIC_SANDBOX_DECEPTION_E2E=true (opt-in env var)
- Network access to the ADEPT gateway (agent_gateway:8081 or localhost:8083)
- Network access to deception.pnl.gov:22 (from within the ADEPT stack)
- SSH keys provisioned for Deception
- LLM API keys configured (Azure/Bedrock for the agent to reason)

This test consumes real allocation hours on Deception and LLM tokens.
"""

import asyncio
import json
import logging
import os
import re
import socket
import time
import uuid
from pathlib import Path

import httpx
import pytest

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# --- Configuration (loaded from config/e2e_credentials.json, env vars override) ---
_CONFIG_PATHS = [
    Path(__file__).parent.parent.parent / "config" / "e2e_credentials.json",
    Path("/app/config/e2e_credentials.json"),
]
_config = {}
for _p in _CONFIG_PATHS:
    if _p.exists():
        _config = json.loads(_p.read_text())
        break

GATEWAY_URL = os.getenv("AGENT_GATEWAY_URL", _config.get("gateway_url", "http://agent_gateway:8081/v1"))
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", _config.get("keycloak_url", "http://keycloak:8180"))
KEYCLOAK_REALM = "master"
USERNAME = os.getenv("ADEPT_TEST_USER", _config.get("username", ""))
PASSWORD = os.getenv("ADEPT_TEST_PASSWORD", _config.get("password", ""))
CLIENT_ID = os.getenv("ADEPT_TEST_CLIENT_ID", _config.get("client_id", "agent-gateway-client"))
MODEL = os.getenv("ADEPT_TEST_MODEL", _config.get("model", "agentic-framework:scientific-agent-v1"))


def _get_client_secret() -> str:
    """Resolve the agent-gateway-client secret from file or env."""
    for path in [
        "/app/credentials/AGENT_GATEWAY_CLIENT_SECRET",
        "/run/secrets/AGENT_GATEWAY_CLIENT_SECRET",
    ]:
        try:
            with open(path) as f:
                return f.read().strip()
        except FileNotFoundError:
            continue
    return os.getenv("AGENT_GATEWAY_CLIENT_SECRET", "")

E2E_ENABLED = os.getenv("AGENTIC_SANDBOX_DECEPTION_E2E", "false").lower() == "true"
RESPONSE_TIMEOUT = int(os.getenv("AGENTIC_E2E_TIMEOUT", "300"))
JOB_POLL_TIMEOUT = int(os.getenv("AGENTIC_E2E_JOB_POLL_TIMEOUT", "180"))

skip_e2e = pytest.mark.skipif(
    not E2E_ENABLED,
    reason="AGENTIC_SANDBOX_DECEPTION_E2E not set to 'true' (opt-in required)",
)


def _can_reach_gateway() -> bool:
    """Check if the ADEPT gateway is reachable."""
    try:
        host = GATEWAY_URL.split("//")[1].split("/")[0]
        hostname, port = (host.split(":") + ["8081"])[:2]
        sock = socket.create_connection((hostname, int(port)), timeout=3.0)
        sock.close()
        return True
    except (OSError, socket.timeout, IndexError):
        return False


skip_network = pytest.mark.skipif(
    not _can_reach_gateway() if E2E_ENABLED else True,
    reason="Cannot reach ADEPT gateway",
)


def _get_jwt_token() -> str:
    """Authenticate with Keycloak and return a JWT access token."""
    token_url = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"
    client_secret = _get_client_secret()
    logger.info(
        "Auth: url=%s user=%s client_id=%s secret_len=%d",
        token_url, USERNAME, CLIENT_ID, len(client_secret),
    )
    data = {
        "grant_type": "password",
        "client_id": CLIENT_ID,
        "client_secret": client_secret,
        "username": USERNAME,
        "password": PASSWORD,
    }
    with httpx.Client(verify=False, timeout=15.0) as client:
        resp = client.post(token_url, data=data)
        if resp.status_code != 200:
            logger.error("Auth FAILED: %d %s", resp.status_code, resp.text[:300])
        resp.raise_for_status()
        token = resp.json()["access_token"]
        logger.info("Auth OK: token_len=%d", len(token))
        return token


def _send_message(
    token: str,
    session_id: str,
    mcp_session_id: str,
    messages: list,
) -> dict:
    """Send a message to the ADEPT Response API and return the full response."""
    url = f"{GATEWAY_URL}/responses/chat/completions"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": messages,
        "session_id": session_id,
        "mcp_session_id": mcp_session_id,
        "api_type": "response",
        "stream": False,
    }
    last_user_msg = next(
        (m["content"][:120] for m in reversed(messages) if m["role"] == "user"), ""
    )
    logger.info(
        "POST %s | session=%s | mcp_session=%s | turns=%d | last_user='%s...'",
        url, session_id, mcp_session_id, len(messages), last_user_msg,
    )
    with httpx.Client(verify=False, timeout=RESPONSE_TIMEOUT) as client:
        resp = client.post(url, json=payload, headers=headers)
        logger.info("Response status: %d (%d bytes)", resp.status_code, len(resp.content))
        resp.raise_for_status()
        result = resp.json()
        content = _extract_assistant_content(result)
        logger.info(
            "Assistant response (%d chars): %s",
            len(content), content[:500] if content else "<empty>",
        )
        return result


def _extract_assistant_content(response: dict) -> str:
    """Extract the assistant's text content from a Response API response."""
    choices = response.get("choices", [])
    if not choices:
        return ""
    message = choices[0].get("message", {})
    return message.get("content", "")


def _extract_job_id(text: str) -> str:
    """Extract a Slurm job ID (numeric string) from agent response text."""
    patterns = [
        r"job[_ ]?(?:id|ID)[:\s]+(\d{4,})",
        r"(?:Submitted|submitted)\s+(?:batch\s+)?job\s+(\d{4,})",
        r"(\d{6,})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return ""


@skip_e2e
@skip_network
class TestAgenticSandboxToDeception:
    """Full agentic E2E: prompt -> sandbox script gen -> Deception submit -> verify."""

    @pytest.fixture
    def auth_token(self) -> str:
        """Get a fresh JWT token for the test."""
        return _get_jwt_token()

    @pytest.fixture
    def session_ids(self) -> dict:
        """Generate unique session IDs for this test run."""
        run_id = uuid.uuid4().hex[:8]
        return {
            "session_id": f"e2e_sandbox_deception_{run_id}",
            "mcp_session_id": f"mcp_e2e_sandbox_deception_{run_id}",
        }

    def test_generate_and_submit_hello_world(self, auth_token, session_ids):
        """Full lifecycle: ask agent to generate script then submit to Deception.

        This is a single-turn test that gives the agent a complete instruction
        in one prompt. The agent should:
        1. Use the sandbox code execution tool to generate and save a bash script
           to the uploaded_files shared volume
        2. Use deception_submit_job to submit that script to the cluster
        3. Report back with the job ID

        The script is saved to the uploaded_files data folder which is readable
        by the slurm_hpc job submission tool via the shared_uploads volume.
        """
        mcp_sid = session_ids["mcp_session_id"]
        prompt = (
            "Generate a simple hello-world Slurm batch script that prints the hostname, "
            "current date, and 'ADEPT_E2E_SANDBOX_DECEPTION_OK' as a success marker, "
            "then sleeps for 10 seconds. The script should use 1 node, 1 task, and a "
            "5-minute time limit. "
            f"Save the script to the uploaded_files folder at the path "
            f"'data/uploaded_files/{mcp_sid}/hello_world_slurm.sh' using the sandbox "
            "code execution tool so it is accessible on the shared volume. "
            "Then submit that script to the Deception HPC cluster using the "
            "deception_submit_job tool with job_name 'adept_e2e_sandbox_test'. "
            "Report the job ID when done."
        )

        messages = [{"role": "user", "content": prompt}]

        response = _send_message(
            token=auth_token,
            session_id=session_ids["session_id"],
            mcp_session_id=session_ids["mcp_session_id"],
            messages=messages,
        )

        content = _extract_assistant_content(response)
        assert content, "Agent returned empty response"

        job_id = _extract_job_id(content)
        assert job_id, (
            f"No Slurm job ID found in agent response. "
            f"Response content (first 500 chars): {content[:500]}"
        )

        assert "submit" in content.lower() or "job" in content.lower(), (
            "Agent response does not mention job submission"
        )

    def test_generate_submit_and_poll(self, auth_token, session_ids):
        """Extended lifecycle: generate, submit, then poll job status.

        Like test_generate_and_submit_hello_world but adds a second turn
        asking the agent to check on the job status, verifying that the
        session context persists and the agent can use deception_get_job_details.
        """
        # Turn 1: Generate and submit
        mcp_sid = session_ids["mcp_session_id"]
        prompt_1 = (
            "Write a minimal Slurm batch script that runs: "
            "echo 'ADEPT_E2E_POLL_TEST_OK' && hostname && sleep 5. "
            f"Save the script to 'data/uploaded_files/{mcp_sid}/poll_test_slurm.sh' "
            "using the sandbox code execution tool so it is on the shared volume. "
            "Then submit it to Deception with job_name 'adept_e2e_poll_test', "
            "1 node, 1 task, time_limit '00:05:00'. Tell me the job ID."
        )

        messages = [{"role": "user", "content": prompt_1}]

        response_1 = _send_message(
            token=auth_token,
            session_id=session_ids["session_id"],
            mcp_session_id=session_ids["mcp_session_id"],
            messages=messages,
        )

        content_1 = _extract_assistant_content(response_1)
        assert content_1, "Agent returned empty response on turn 1"

        job_id = _extract_job_id(content_1)
        assert job_id, (
            f"No job ID in turn 1 response: {content_1[:500]}"
        )

        # Turn 2: Ask for job status
        messages.append({"role": "assistant", "content": content_1})
        messages.append({
            "role": "user",
            "content": f"Check the status of job {job_id} on Deception.",
        })

        response_2 = _send_message(
            token=auth_token,
            session_id=session_ids["session_id"],
            mcp_session_id=session_ids["mcp_session_id"],
            messages=messages,
        )

        content_2 = _extract_assistant_content(response_2)
        assert content_2, "Agent returned empty response on turn 2"

        valid_states = [
            "pending", "running", "completed", "failed",
            "cancelled", "configuring", "completing",
        ]
        content_lower = content_2.lower()
        assert any(state in content_lower for state in valid_states) or job_id in content_2, (
            f"Turn 2 response does not contain job state or ID: {content_2[:500]}"
        )

    def test_submit_status_and_introspect_call_graph(self, auth_token, session_ids):
        """Full lifecycle with introspection: submit -> status -> call graph.

        After the agent submits a job and checks its status, we ask it to
        generate a call graph of the workflow using its introspection tools.
        This exercises the full cross-service path (orchestration -> slurm_mcp
        -> Deception) and produces observable orchestration_service logs for
        evidence gathering.
        """
        mcp_sid = session_ids["mcp_session_id"]

        # Turn 1: Generate and submit
        prompt_1 = (
            "Write a minimal Slurm batch script that runs: "
            "echo 'ADEPT_E2E_INTROSPECT_TEST' && hostname && sleep 5. "
            f"Save the script to 'data/uploaded_files/{mcp_sid}/introspect_test.sh' "
            "using the sandbox code execution tool so it is on the shared volume. "
            "Then submit it to Deception with job_name 'adept_e2e_introspect', "
            "1 node, 1 task, time_limit '00:05:00'. Tell me the job ID."
        )

        messages = [{"role": "user", "content": prompt_1}]

        response_1 = _send_message(
            token=auth_token,
            session_id=session_ids["session_id"],
            mcp_session_id=session_ids["mcp_session_id"],
            messages=messages,
        )

        content_1 = _extract_assistant_content(response_1)
        assert content_1, "Agent returned empty response on turn 1 (submit)"

        job_id = _extract_job_id(content_1)
        assert job_id, f"No job ID in turn 1 response: {content_1[:500]}"

        # Turn 2: Check job status and list queue
        messages.append({"role": "assistant", "content": content_1})
        messages.append({
            "role": "user",
            "content": (
                f"Check the status of job {job_id} on Deception. "
                "Also list my recent jobs in the queue."
            ),
        })

        response_2 = _send_message(
            token=auth_token,
            session_id=session_ids["session_id"],
            mcp_session_id=session_ids["mcp_session_id"],
            messages=messages,
        )

        content_2 = _extract_assistant_content(response_2)
        assert content_2, "Agent returned empty response on turn 2 (status)"

        valid_states = [
            "pending", "running", "completed", "failed",
            "cancelled", "configuring", "completing",
        ]
        content_2_lower = content_2.lower()
        assert any(s in content_2_lower for s in valid_states) or job_id in content_2, (
            f"Turn 2 response does not contain job state or ID: {content_2[:500]}"
        )

        # Turn 3: Ask for introspection call graph after tool calls complete
        messages.append({"role": "assistant", "content": content_2})
        messages.append({
            "role": "user",
            "content": (
                "Use your introspection tools to generate a call graph of "
                "the workflow I requested."
            ),
        })

        response_3 = _send_message(
            token=auth_token,
            session_id=session_ids["session_id"],
            mcp_session_id=session_ids["mcp_session_id"],
            messages=messages,
        )

        content_3 = _extract_assistant_content(response_3)
        assert content_3, "Agent returned empty response on turn 3 (introspection)"

        # The introspection response should reference the tools/steps used
        introspection_keywords = [
            "sandbox", "submit", "deception", "script", "job",
            "execute", "code", "tool", "call", "workflow", "graph",
            "step", "sequence", "flow",
        ]
        content_3_lower = content_3.lower()
        matches = [kw for kw in introspection_keywords if kw in content_3_lower]
        assert len(matches) >= 3, (
            f"Introspection response lacks workflow references. "
            f"Only matched {matches} from keywords. "
            f"Response (first 800 chars): {content_3[:800]}"
        )

    def test_direct_transport_submission_fallback(self, auth_token, session_ids):
        """Fallback test: bypass the LLM and submit directly via Fabric transport.

        This validates the infrastructure path (SSH -> sbatch) independently
        of the LLM agent, ensuring the Deception SSH key and transport work
        from within the test environment. Useful for diagnosing whether
        failures in the full agentic test are LLM-side or infra-side.
        """
        try:
            import sys
            slurm_mcp_dir = os.path.join(
                os.path.dirname(__file__), "..", "..", "slurm_mcp_server"
            )
            if slurm_mcp_dir not in sys.path:
                sys.path.insert(0, slurm_mcp_dir)

            from slurm_mcp.deception.config import deception_config
            from slurm_mcp.fabric_transport import FabricSSHTransport
        except ImportError:
            pytest.skip("slurm_mcp package not importable in test environment")

        if not deception_config.resolved_ssh_key_path.exists():
            pytest.skip("SSH key not provisioned for Deception")

        transport = FabricSSHTransport(deception_config)

        script = (
            "#!/bin/bash\n"
            "echo '[HOSTNAME]' $(hostname)\n"
            "echo '[DATE]' $(date -u '+%Y-%m-%dT%H:%M:%SZ')\n"
            "echo 'ADEPT_E2E_DIRECT_TRANSPORT_OK'\n"
            "sleep 5\n"
            "exit 0\n"
        )

        result = asyncio.get_event_loop().run_until_complete(
            transport.submit_job(
                script=script,
                job_name="adept_e2e_direct_transport",
                time_limit="00:05:00",
                nodes=1,
                ntasks=1,
            )
        )

        assert result.success, f"Direct submission failed: {result.error}"
        assert result.job_id, f"No job_id in result: {result.output}"

        # Poll for completion (up to 120s)
        deadline = time.time() + 120
        final_state = None
        while time.time() < deadline:
            status = asyncio.get_event_loop().run_until_complete(
                transport.get_job_status(result.job_id)
            )
            if status.success and status.raw_data:
                state = status.raw_data.get("job_state", "")
                if state in ("COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"):
                    final_state = state
                    break
            time.sleep(5)

        assert final_state == "COMPLETED", (
            f"Job {result.job_id} ended with state: {final_state}"
        )

        asyncio.get_event_loop().run_until_complete(transport.close())
