#!/usr/bin/env python3
"""ADEPT Compute Lifecycle Demo — Responses API Driver.

Drives the full COBRApy/Gurobi FBA lifecycle on Deception HPC through
ADEPT's Responses API (agent-mediated). Produces a portable thread_id
observable from any ADEPT client (Streamlit, CLI, Claude adaptor, Langfuse).

Usage:
    python demos/perform_demo.py --user rigo160 --model demos/models/simple_pathway.xml
    python demos/perform_demo.py --user dowd665 --gateway-url http://localhost:8083
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _log(msg: str) -> None:
    print(f"[perform-demo] {msg}", flush=True)


def _agent(msg: str) -> None:
    print(f"[agent] {msg}", flush=True)


def _keycloak_token(keycloak_url: str, username: str, password: str) -> str:
    """Obtain JWT via Keycloak ROPC flow (direct to Keycloak, not gateway proxy)."""
    token_url = f"{keycloak_url}/realms/master/protocol/openid-connect/token"
    body = urllib.parse.urlencode({
        "client_id": "login-client",
        "username": username,
        "password": password,
        "grant_type": "password",
        "scope": "openid profile email",
    }).encode()
    req = Request(token_url, data=body, headers={
        "Content-Type": "application/x-www-form-urlencoded",
    })
    try:
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            return data["access_token"]
    except HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        raise SystemExit(
            f"Authentication failed ({e.code}): {error_body}"
        ) from e


def _create_thread(gateway_url: str, token: str) -> str:
    """Create a new conversation thread."""
    url = f"{gateway_url}/v1/threads"
    req = Request(
        url,
        data=b"{}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
        return data["id"]


def _upload_file(
    gateway_url: str, token: str, file_path: Path
) -> Optional[str]:
    """Upload a model file via the ADEPT file API. Returns file_id.

    Uses proper multipart/form-data with 'file' and 'purpose' fields,
    matching the gateway's FastAPI UploadFile + Form signature.
    """
    if not file_path.exists():
        _log(f"WARNING: Model file not found: {file_path}")
        return None

    import mimetypes
    import uuid

    boundary = uuid.uuid4().hex
    filename = file_path.name
    content_type = mimetypes.guess_type(filename)[0] or "application/xml"
    file_data = file_path.read_bytes()

    # Build multipart body with both 'purpose' form field and 'file' upload
    parts = []
    # Part 1: purpose (required Form field)
    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="purpose"\r\n\r\n'
        f"assistants\r\n"
    )
    # Part 2: file (UploadFile)
    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    )

    body = b""
    body += parts[0].encode()
    body += parts[1].encode()
    body += file_data
    body += f"\r\n--{boundary}--\r\n".encode()

    req = Request(
        f"{gateway_url}/v1/files",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        with urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            return data.get("id") or data.get("file_id")
    except HTTPError as e:
        error_body = e.read().decode()[:200] if e.fp else ""
        _log(f"WARNING: File upload failed ({e.code}): {error_body}")
        return None


def _stream_chat(
    gateway_url: str, token: str, thread_id: str, prompt: str, timeout: int,
    session_id: Optional[str] = None,
) -> str:
    """Send prompt via Responses API with SSE streaming. Returns agent output."""
    url = f"{gateway_url}/v1/responses/chat/completions"
    body = {
        "model": "agentic-framework:scientific-agent-v1",
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "thread_id": thread_id,
    }
    if session_id:
        body["session_id"] = session_id
    payload = json.dumps(body).encode()

    req = Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
    )

    collected_output = []
    start = time.time()
    try:
        with urlopen(req, timeout=timeout) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\n\r")
                if not line:
                    continue
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        event = json.loads(data_str)
                        text = _handle_sse_event(event)
                        if text:
                            collected_output.append(text)
                    except json.JSONDecodeError:
                        pass
    except HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        _log(f"ERROR: Stream failed ({e.code}): {error_body[:200]}")
        raise SystemExit(1)
    except URLError as e:
        if time.time() - start >= timeout - 5:
            _log(f"TIMEOUT: Agent did not complete within {timeout}s")
        else:
            _log(f"ERROR: Connection failed: {e.reason}")
        raise SystemExit(1)
    return "".join(collected_output)


def _handle_sse_event(event: dict) -> str:
    """Process a single SSE chunk from Responses API. Returns content text."""
    text_parts = []
    choices = event.get("choices", [])
    for choice in choices:
        delta = choice.get("delta", {})
        content = delta.get("content")
        tool_calls = delta.get("tool_calls")

        if content:
            _agent(content)
            text_parts.append(content)
        if tool_calls:
            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                if name:
                    _agent(f"[tool_call] {name}(...)")
    return "".join(text_parts)


def main():
    parser = argparse.ArgumentParser(
        description="Drive ADEPT compute lifecycle via Responses API"
    )
    parser.add_argument(
        "--user", default="rigo160", help="Deception username (default: rigo160)"
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("ADEPT_PASSWORD", "changeme"),
        help="ADEPT/Keycloak password (default: $ADEPT_PASSWORD or 'changeme')",
    )
    parser.add_argument(
        "--model",
        default="demos/models/simple_pathway.xml",
        help="Path to SBML model file (default: simple_pathway.xml)",
    )
    parser.add_argument(
        "--gateway-url",
        default=os.environ.get("AGENT_GATEWAY_URL", "http://localhost:8083"),
        help="ADEPT Agent Gateway URL (default: $AGENT_GATEWAY_URL or localhost:8083)",
    )
    parser.add_argument(
        "--keycloak-url",
        default=os.environ.get("KEYCLOAK_URL", "http://keycloak:8180"),
        help="Keycloak base URL (default: $KEYCLOAK_URL or keycloak:8180)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Max seconds to wait for agent completion (default: 600)",
    )
    parser.add_argument(
        "--prompt",
        default=None,
        help="Custom prompt (default: auto-generated from user and model)",
    )
    parser.add_argument(
        "--skip-upload",
        action="store_true",
        help="Skip file upload (use pre-uploaded or bundled model)",
    )
    parser.add_argument(
        "--use-demo-mount",
        action="store_true",
        help="Use the demos volume mount as model source (fallback if upload fails)",
    )
    args = parser.parse_args()

    model_path = Path(args.model)
    gateway_url = args.gateway_url.rstrip("/")

    keycloak_url = args.keycloak_url.rstrip("/")
    _log(f"Authenticating as {args.user} via {keycloak_url}...")
    token = _keycloak_token(keycloak_url, args.user, args.password)
    _log("Authenticated.")

    _log("Creating thread...")
    thread_id = _create_thread(gateway_url, token)
    _log(f"Created thread: {thread_id}")

    file_id = None
    if not args.skip_upload and not args.use_demo_mount and model_path.exists():
        _log(f"Uploading model: {model_path.name} ({model_path.stat().st_size} bytes)...")
        file_id = _upload_file(gateway_url, token, model_path)
        if file_id:
            _log(f"File registered: {file_id}")
        else:
            _log("Upload failed — agent will use demo volume mount as fallback")

    # Build prompt with context about how to find the model
    if args.prompt:
        prompt = args.prompt
    elif file_id:
        # file_id doubles as the filename in shared_uploads (flat storage)
        prompt = (
            f"Run COBRApy flux balance analysis on Deception HPC for user {args.user}. "
            f"I have uploaded the SBML model. The file is already in shared_uploads "
            f"with local_path='{file_id}' (filename: {model_path.name}).\n\n"
            f"IMPORTANT CONSTRAINTS:\n"
            f"- For ALL tool calls, pass session_id=your MCP Session ID "
            f"(shown in your system prompt). This routes job output to your "
            f"workspace where it can be read later.\n"
            f"- Do NOT call list_uploaded_files — the file is confirmed available.\n"
            f"- Do NOT specify a partition in any sbatch job — omit the partition "
            f"field entirely and let SBATCH defaults apply.\n"
            f"- Do NOT call get_cluster_summary — it returns too much data.\n"
            f"- Do NOT generate your own scripts — use the EXACT scripts below.\n\n"
            f"Execute ALL steps below in a SINGLE turn. Do NOT pause or ask for "
            f"confirmation between steps. Complete all 3 steps before responding.\n\n"
            f"1. STAGE FILES: Upload all required files to the session workspace.\n"
            f"   Call workspace_upload_file THREE times:\n"
            f"   a) local_path='adept-cobrapy.sif', remote_filename='adept-cobrapy.sif', "
            f"cluster='deception', session_id=your MCP Session ID\n"
            f"   b) local_path='{file_id}', remote_filename='{model_path.name}', "
            f"cluster='deception', session_id=your MCP Session ID\n"
            f"   c) local_path='gurobi.lic', remote_filename='gurobi.lic', "
            f"cluster='deception', session_id=your MCP Session ID\n\n"
            f"2. PROVISION SIF: Call deception_submit_job with this script:\n"
            f"```\n"
            f"#!/bin/bash\n"
            f"mkdir -p $HOME/adept-workspace/containers\n"
            f"SESSION_DIR=\"$HOME/adept-workspace/{{SESSION_ID}}\"\n"
            f"cp \"$SESSION_DIR/adept-cobrapy.sif\" \"$HOME/adept-workspace/containers/\"\n"
            f"echo \"SIF provisioned at $HOME/adept-workspace/containers/adept-cobrapy.sif\"\n"
            f"ls -la $HOME/adept-workspace/containers/adept-cobrapy.sif\n"
            f"```\n"
            f"   Set job_name='provision_sif'. Pass session_id.\n"
            f"   Replace {{SESSION_ID}} with your actual MCP Session ID.\n\n"
            f"3. EXECUTE FBA: Call deception_submit_job with this EXACT script:\n"
            f"```\n"
            f"#!/bin/bash\n"
            f"set -euo pipefail\n"
            f"module load apptainer 2>/dev/null || true\n"
            f"SIF_PATH=\"$HOME/adept-workspace/containers/adept-cobrapy.sif\"\n"
            f"echo \"=== ADEPT FBA ===\"\n"
            f"echo \"User: $(whoami) | Host: $(hostname) | Date: $(date -Iseconds)\"\n"
            f"echo \"SIF: $SIF_PATH | Model: {model_path.name}\"\n"
            f"if [ ! -f \"$SIF_PATH\" ]; then\n"
            f"  echo \"ERROR: SIF not found at $SIF_PATH\"\n"
            f"  echo \"RESULT:fba=FAIL\"\n"
            f"  exit 1\n"
            f"fi\n"
            f"export GRB_LICENSE_FILE=\"$(pwd)/gurobi.lic\"\n"
            f"apptainer exec --unsquash --bind $(pwd):/work --pwd /work \"$SIF_PATH\" python3 -c \"\n"
            f"import os\n"
            f"os.environ['GRB_LICENSE_FILE'] = '/work/gurobi.lic'\n"
            f"import cobra\n"
            f"from cobra.io import read_sbml_model\n"
            f"model = read_sbml_model('/work/{model_path.name}')\n"
            f"solution = model.optimize()\n"
            f"print(f'Optimization status: {{solution.status}}')\n"
            f"print(f'Optimal objective value: {{solution.objective_value}}')\n"
            f"print(f'RESULT:optimal_value={{solution.objective_value:.6f}}')\n"
            f"\"\n"
            f"```\n"
            f"   Set job_name='fba_analysis'. Pass session_id. Set time_limit='00:05:00'.\n"
            f"   The working directory is automatically the session workspace.\n\n"
            f"After completing ALL 3 steps, report ONLY the FBA job ID. "
            f"Do NOT read output — the job needs time to run."
        )
    else:
        # Fallback: no uploaded file — use demos volume mount
        # The demos dir is at /app/demos/ on the slurm_mcp_server container,
        # but workspace_upload_file reads from SHARED_UPLOAD_DIR only.
        # Use deception_execute_command to scp from a known location instead.
        prompt = (
            f"Run COBRApy flux balance analysis on Deception HPC for user {args.user}. "
            f"The model file {model_path.name} is not uploaded to shared storage.\n\n"
            f"IMPORTANT CONSTRAINTS:\n"
            f"- Do NOT specify a partition in any sbatch job — omit the partition "
            f"field entirely and let SBATCH defaults apply.\n"
            f"- Do NOT call get_cluster_summary — it returns too much data.\n\n"
            f"Execute these steps in order:\n"
            f"1. Call deception_submit_job with the preflight_workspace.sh script "
            f"(creates $HOME/adept-workspace/ directories). No partition needed.\n"
            f"2. The model file needs to be placed in $HOME/adept-workspace/ on "
            f"Deception. Check if it exists there already.\n"
            f"3. Submit the FBA job script that loads modules (python/3.11, "
            f"gurobi/11.0) and runs COBRApy FBA on the model.\n"
            f"Report the optimal biomass flux value when complete."
        )

    # --- Multi-turn execution ---
    # Stable session_id across all turns so MCP workspace is consistent.
    # Without this, each Responses API call generates a new session_id and
    # the agent's workspace directory changes between turns.
    import uuid
    stable_session_id = f"demo_{uuid.uuid4().hex[:16]}"
    _log(f"Session ID: {stable_session_id}")

    # Turn 1: Submit jobs (preflight + upload + FBA)
    _log("TURN 1: Sending initial prompt to agent...")
    _log("-" * 60)
    t0 = time.time()
    turn1_output = _stream_chat(
        gateway_url, token, thread_id, prompt, args.timeout,
        session_id=stable_session_id,
    )
    _log("-" * 60)
    _log(f"Turn 1 completed in {int(time.time() - t0)}s")

    # Extract job IDs from agent output for the follow-up prompt.
    # Agent may format output with markdown: **Job ID:** `856125`
    job_ids = re.findall(
        r"(?:job[_ ]?(?:id)?[:\s*`]*|Submitted batch job\s+|slurm-)(\d{5,})",
        turn1_output, re.IGNORECASE,
    )
    if job_ids:
        _log(f"Detected job IDs: {job_ids}")

    # Detect if Turn 1 produced an FBA-specific job (not just provisioning jobs)
    fba_job_submitted = any(
        "fba" in turn1_output.lower() and jid in turn1_output
        for jid in job_ids
    ) if job_ids else False

    # Turn 2: Wait, then ask agent to check status and read output
    poll_delays = [30, 60, 60, 60, 60]
    for attempt, delay in enumerate(poll_delays, 1):
        _log(f"Waiting {delay}s for Slurm jobs to complete...")
        time.sleep(delay)

        if fba_job_submitted and job_ids:
            last_job = job_ids[-1]
            poll_prompt = (
                f"Check the status of Slurm job {last_job} on Deception using "
                f"deception_get_job_details with job_id='{last_job}'. "
                f"Do NOT use the generic get_job_details tool — it calls slurmrestd "
                f"which is not available. Use deception_get_job_details (SSH-based). "
                f"If the job state is COMPLETED, read its output using "
                f"workspace_read_file with cluster='deception', "
                f"session_id=your MCP Session ID (from your system prompt), and "
                f"remote_filename='slurm-{last_job}.out'. "
                f"IMPORTANT: You MUST pass session_id to workspace_read_file — "
                f"it is the same MCP Session ID shown in your system prompt. "
                f"Report the biomass flux value from the output. "
                f"If the job is still RUNNING or PENDING, just report its current state."
            )
        else:
            # Agent didn't complete the full workflow in Turn 1 — inject context
            # and tell it to continue from where it left off.
            poll_prompt = (
                f"In a previous turn you partially completed the FBA workflow. "
                f"Here is what you reported: \"{turn1_output[:500]}\"\n\n"
                f"Continue executing the remaining steps from the original "
                f"instructions. Complete ALL remaining steps in this single turn: "
                f"stage files (workspace_upload_file), provision SIF "
                f"(deception_submit_job), and submit the FBA job "
                f"(deception_submit_job). Do NOT pause or ask for confirmation. "
                f"Report the FBA job ID when done."
            )

        _log(f"TURN {attempt + 1}: Polling job status...")
        _log("-" * 60)
        turn_output = _stream_chat(
            gateway_url, token, thread_id, poll_prompt, args.timeout,
            session_id=stable_session_id,
        )
        _log("-" * 60)

        # Capture any new job IDs from this turn's output
        new_ids = re.findall(
            r"(?:job[_ ]?(?:id)?[:\s*`]*|Submitted batch job\s+|slurm-)(\d{5,})",
            turn_output, re.IGNORECASE,
        )
        if new_ids:
            job_ids.extend(new_ids)
            _log(f"Detected new job IDs: {new_ids}")
            # If agent mentions fba_analysis in this turn, mark as submitted
            if "fba" in turn_output.lower():
                fba_job_submitted = True

        # Check if the agent reported a numeric flux/objective result
        if re.search(
            r"(?:flux|objective|optimal).{0,80}(?:=|:|is)\s*\*{0,2}-?[\d]+\.[\d]+",
            turn_output, re.IGNORECASE,
        ):
            _log("Result detected in agent output.")
            break
        # Match COMPLETED only when describing current state, not future conditions.
        # Exclude "updates to COMPLETED" / "becomes COMPLETED" / "once...COMPLETED"
        if re.search(
            r"(?:state|status|job).{0,40}(?:is|:|=)\s*[\"'`*]*COMPLETED",
            turn_output, re.IGNORECASE,
        ) and not re.search(
            r"(?:once|when|until|updates?\s+to|becomes?)\s.{0,20}COMPLETED",
            turn_output, re.IGNORECASE,
        ):
            _log("Job completed. Agent should have reported result above.")
            break

    elapsed = time.time() - t0

    _log("-" * 60)
    _log("SESSION COMPLETE")
    _log(f"  Thread ID:  {thread_id}")
    _log(f"  Duration:   {int(elapsed // 60)}m {int(elapsed % 60)}s")
    _log(f"  User:       {args.user}")
    _log(f"  Model:      {model_path.name}")
    _log(f"  Jobs:       {', '.join(job_ids) if job_ids else 'unknown'}")
    _log("")
    _log("Attach from any client:")
    _log(f"  CLI:        afk session attach {thread_id}")
    _log(f"  Streamlit:  http://localhost:8503 -> Session Picker -> {thread_id}")
    _log(f"  Langfuse:   http://localhost:3001 -> Traces -> {thread_id}")
    _log(f'  Claude:     "Check status of session {thread_id} on ADEPT"')


if __name__ == "__main__":
    main()
