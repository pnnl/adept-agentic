#!/usr/bin/env python3
"""ADEPT Compute Lifecycle Demo v2 — Multi-Agent with LLM-as-Judge.

Drives the COBRApy/Gurobi FBA lifecycle on Deception HPC using ADEPT's
multi-agent orchestration. Three roles collaborate:
  - executor: performs tool calls (coding_agent LLM purpose)
  - judge: evaluates correctness via structured verdicts
  - observer: monitors for anti-patterns

The judge emits a FinalVerdict JSON that replaces v1's regex-based detection.

Usage:
    python demos/perform_demo_v2.py --user rigo160 --model demos/models/simple_pathway.xml
    python demos/perform_demo_v2.py --user rigo160 --mode single  # Falls back to v1 behavior
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _log(msg: str) -> None:
    print(f"[perform-demo-v2] {msg}", flush=True)


def _agent(msg: str) -> None:
    print(f"[agent] {msg}", flush=True)


def _keycloak_token(keycloak_url: str, username: str, password: str) -> str:
    """Obtain JWT via Keycloak ROPC flow."""
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
        raise SystemExit(f"Authentication failed ({e.code}): {error_body}") from e


def _create_thread(gateway_url: str, token: str) -> str:
    """Create a new conversation thread."""
    req = Request(
        f"{gateway_url}/v1/threads",
        data=b"{}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())["id"]


def _upload_file(gateway_url: str, token: str, file_path: Path) -> Optional[str]:
    """Upload a model file via multipart form. Returns file_id."""
    if not file_path.exists():
        _log(f"WARNING: Model file not found: {file_path}")
        return None

    import mimetypes

    boundary = uuid.uuid4().hex
    filename = file_path.name
    content_type = mimetypes.guess_type(filename)[0] or "application/xml"
    file_data = file_path.read_bytes()

    parts = []
    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="purpose"\r\n\r\n'
        f"assistants\r\n"
    )
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
    """Process a single SSE chunk. Returns content text."""
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


def _extract_verdict(output: str) -> Optional[dict]:
    """Extract FinalVerdict JSON from agent output.

    Handles multiple formats the agent may emit:
    1. Flat: {"final_verdict": "PASS", ...}
    2. Flat synonym: {"final_verdict": "success", ...}
    3. Nested: {"final_verdict": {"status": "success", ...}, ...}
    """
    verdict_synonyms = {
        "pass": "PASS", "success": "PASS", "passed": "PASS",
        "partial": "PARTIAL", "incomplete": "PARTIAL",
        "fail": "FAIL", "failure": "FAIL", "failed": "FAIL",
    }

    def _normalize(obj: dict) -> Optional[dict]:
        fv = obj.get("final_verdict")
        if isinstance(fv, str):
            normalized = verdict_synonyms.get(fv.lower(), fv.upper())
            if normalized in ("PASS", "PARTIAL", "FAIL"):
                obj["final_verdict"] = normalized
                return obj
        elif isinstance(fv, dict):
            status = fv.get("status", fv.get("verdict", ""))
            normalized = verdict_synonyms.get(status.lower(), status.upper())
            if normalized in ("PASS", "PARTIAL", "FAIL"):
                result = {
                    "final_verdict": normalized,
                    "confidence": fv.get("confidence", 0.85),
                    "summary": fv.get("message", fv.get("summary", "")),
                    "job_ids": obj.get("job_ids", []),
                    "optimal_value": fv.get("data", {}).get("optimal_value")
                    if isinstance(fv.get("data"), dict)
                    else fv.get("optimal_value"),
                }
                return result
        return None

    for line in output.splitlines():
        line = line.strip()
        if "final_verdict" in line:
            start = line.find("{")
            if start >= 0:
                bracket_count = 0
                end = start
                for i, ch in enumerate(line[start:], start):
                    if ch == "{":
                        bracket_count += 1
                    elif ch == "}":
                        bracket_count -= 1
                        if bracket_count == 0:
                            end = i + 1
                            break
                try:
                    obj = json.loads(line[start:end])
                    result = _normalize(obj)
                    if result:
                        return result
                except json.JSONDecodeError:
                    pass

    all_json_blocks = re.findall(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', output)
    for block in all_json_blocks:
        if "final_verdict" in block:
            try:
                obj = json.loads(block)
                result = _normalize(obj)
                if result:
                    return result
            except json.JSONDecodeError:
                continue

    return None


def _build_multi_agent_prompt(
    user: str, file_id: str, model_name: str
) -> str:
    """Build the multi-agent instruction prompt."""
    return (
        f"We are running a COBRApy flux balance analysis on Deception HPC for "
        f"user {user}.\n\n"
        f"EXECUTOR: Execute ALL steps below in a SINGLE turn. Do NOT pause.\n\n"
        f"1. STAGE FILES: Call workspace_upload_file THREE times:\n"
        f"   a) local_path='adept-cobrapy.sif', remote_filename='adept-cobrapy.sif', "
        f"cluster='deception', session_id=your MCP Session ID\n"
        f"   b) local_path='{file_id}', remote_filename='{model_name}', "
        f"cluster='deception', session_id=your MCP Session ID\n"
        f"   c) local_path='gurobi.lic', remote_filename='gurobi.lic', "
        f"cluster='deception', session_id=your MCP Session ID\n\n"
        f"2. PROVISION SIF: Call deception_submit_job with this script:\n"
        f"```\n"
        f"#!/bin/bash\n"
        f"mkdir -p $HOME/adept-workspace/containers\n"
        f'SESSION_DIR="$HOME/adept-workspace/{{SESSION_ID}}"\n'
        f'cp "$SESSION_DIR/adept-cobrapy.sif" "$HOME/adept-workspace/containers/"\n'
        f'echo "SIF provisioned at $HOME/adept-workspace/containers/adept-cobrapy.sif"\n'
        f"ls -la $HOME/adept-workspace/containers/adept-cobrapy.sif\n"
        f"```\n"
        f"   Set job_name='provision_sif'. Pass session_id.\n"
        f"   Replace {{SESSION_ID}} with your actual MCP Session ID.\n\n"
        f"3. EXECUTE FBA: Call deception_submit_job with this script:\n"
        f"```\n"
        f"#!/bin/bash\n"
        f"set -euo pipefail\n"
        f"module load apptainer 2>/dev/null || true\n"
        f'SIF_PATH="$HOME/adept-workspace/containers/adept-cobrapy.sif"\n'
        f'echo "=== ADEPT FBA ==="\n'
        f'echo "User: $(whoami) | Host: $(hostname) | Date: $(date -Iseconds)"\n'
        f'echo "SIF: $SIF_PATH | Model: {model_name}"\n'
        f'if [ ! -f "$SIF_PATH" ]; then\n'
        f'  echo "ERROR: SIF not found at $SIF_PATH"\n'
        f'  echo "RESULT:fba=FAIL"\n'
        f"  exit 1\n"
        f"fi\n"
        f'export GRB_LICENSE_FILE="$(pwd)/gurobi.lic"\n'
        f'apptainer exec --unsquash --bind $(pwd):/work --pwd /work "$SIF_PATH" python3 -c "\n'
        f"import os\n"
        f"os.environ['GRB_LICENSE_FILE'] = '/work/gurobi.lic'\n"
        f"import cobra\n"
        f"from cobra.io import read_sbml_model\n"
        f"model = read_sbml_model('/work/{model_name}')\n"
        f"solution = model.optimize()\n"
        f"print(f'Optimization status: {{solution.status}}')\n"
        f"print(f'Optimal objective value: {{solution.objective_value}}')\n"
        f"print(f'RESULT:optimal_value={{solution.objective_value:.6f}}')\n"
        f'"\n'
        f"```\n"
        f"   Set job_name='fba_analysis'. Pass session_id. Set time_limit='00:05:00'.\n\n"
        f"JUDGE: After the executor reports, evaluate each step against the acceptance "
        f"criteria in your system prompt. Emit step verdicts and a final_verdict JSON.\n\n"
        f"OBSERVER: Monitor for anti-patterns (retry loops, hallucinated IDs, "
        f"session_id drift, path violations). Report any anomalies.\n\n"
        f"After the executor completes all 3 steps, the JUDGE should request the "
        f"executor check job status (deception_get_job_details) and read output "
        f"(workspace_read_file) to verify the FBA result. Then emit final_verdict."
    )


def _run_multi_agent(
    gateway_url: str,
    token: str,
    thread_id: str,
    prompt: str,
    session_id: str,
    timeout: int,
    max_turns: int = 6,
) -> dict:
    """Run multi-agent session, polling until judge emits final_verdict."""
    _log("TURN 1: Sending multi-agent instruction...")
    _log("-" * 60)
    turn_output = _stream_chat(
        gateway_url, token, thread_id, prompt, timeout, session_id=session_id
    )
    _log("-" * 60)

    all_output = turn_output
    verdict = _extract_verdict(turn_output)
    if verdict:
        _log("Judge verdict detected in Turn 1.")
        return verdict

    poll_delays = [30, 60, 60, 60, 60]
    for attempt, delay in enumerate(poll_delays[:max_turns - 1], 2):
        _log(f"Waiting {delay}s for jobs to complete...")
        time.sleep(delay)

        job_ids = re.findall(
            r"(?:job[_ ]?(?:id)?[:\s*`]*|Submitted batch job\s+|slurm-)(\d{5,})",
            all_output, re.IGNORECASE,
        )
        last_job = job_ids[-1] if job_ids else "unknown"

        poll_prompt = (
            f"EXECUTOR: Check the status of Slurm job {last_job} on Deception "
            f"using deception_get_job_details with job_id='{last_job}'. "
            f"If COMPLETED, read its output using workspace_read_file with "
            f"cluster='deception', session_id=your MCP Session ID, and "
            f"remote_filename='slurm-{last_job}.out'. Report the full output.\n\n"
            f"JUDGE: Based on the executor's findings, evaluate Step 4 "
            f"(result retrieval) and emit your final_verdict JSON.\n\n"
            f"OBSERVER: Report any anomalies observed."
        )

        _log(f"TURN {attempt}: Polling job status + requesting verdict...")
        _log("-" * 60)
        turn_output = _stream_chat(
            gateway_url, token, thread_id, poll_prompt, timeout,
            session_id=session_id,
        )
        _log("-" * 60)
        all_output += "\n" + turn_output

        verdict = _extract_verdict(turn_output)
        if verdict:
            _log(f"Judge verdict detected in Turn {attempt}.")
            return verdict

    _log("WARNING: No judge verdict after all turns. Constructing PARTIAL verdict.")
    return {
        "final_verdict": "PARTIAL",
        "confidence": 0.3,
        "summary": "Judge did not emit a verdict within the turn limit",
        "job_ids": re.findall(r"\d{5,}", all_output)[:5],
        "optimal_value": None,
    }


def _run_single_agent(
    gateway_url: str,
    token: str,
    thread_id: str,
    prompt: str,
    session_id: str,
    timeout: int,
) -> dict:
    """v1-style single-agent execution with regex-based detection."""
    _log("TURN 1: Sending initial prompt (single-agent mode)...")
    _log("-" * 60)
    t0 = time.time()
    turn1_output = _stream_chat(
        gateway_url, token, thread_id, prompt, timeout, session_id=session_id
    )
    _log("-" * 60)
    _log(f"Turn 1 completed in {int(time.time() - t0)}s")

    job_ids = re.findall(
        r"(?:job[_ ]?(?:id)?[:\s*`]*|Submitted batch job\s+|slurm-)(\d{5,})",
        turn1_output, re.IGNORECASE,
    )
    if job_ids:
        _log(f"Detected job IDs: {job_ids}")

    fba_job_submitted = any(
        "fba" in turn1_output.lower() and jid in turn1_output
        for jid in job_ids
    ) if job_ids else False

    poll_delays = [30, 60, 60, 60, 60]
    for attempt, delay in enumerate(poll_delays, 1):
        _log(f"Waiting {delay}s for Slurm jobs to complete...")
        time.sleep(delay)

        if fba_job_submitted and job_ids:
            last_job = job_ids[-1]
            poll_prompt = (
                f"Check the status of Slurm job {last_job} on Deception using "
                f"deception_get_job_details with job_id='{last_job}'. "
                f"If COMPLETED, read its output using workspace_read_file with "
                f"cluster='deception', session_id=your MCP Session ID, and "
                f"remote_filename='slurm-{last_job}.out'. "
                f"Report the biomass flux value from the output."
            )
        else:
            poll_prompt = (
                f"In a previous turn you partially completed the FBA workflow. "
                f"Here is what you reported: \"{turn1_output[:500]}\"\n\n"
                f"Continue executing ALL remaining steps in this single turn."
            )

        _log(f"TURN {attempt + 1}: Polling...")
        _log("-" * 60)
        turn_output = _stream_chat(
            gateway_url, token, thread_id, poll_prompt, timeout,
            session_id=session_id,
        )
        _log("-" * 60)

        new_ids = re.findall(
            r"(?:job[_ ]?(?:id)?[:\s*`]*|Submitted batch job\s+|slurm-)(\d{5,})",
            turn_output, re.IGNORECASE,
        )
        if new_ids:
            job_ids.extend(new_ids)
            if "fba" in turn_output.lower():
                fba_job_submitted = True

        if re.search(
            r"(?:flux|objective|optimal).{0,80}(?:=|:|is)\s*\*{0,2}-?[\d]+\.[\d]+",
            turn_output, re.IGNORECASE,
        ):
            value_match = re.search(r"-?[\d]+\.[\d]+", turn_output)
            value = float(value_match.group()) if value_match else None
            return {
                "final_verdict": "PASS",
                "confidence": 0.7,
                "summary": f"Regex matched optimal value: {value}",
                "job_ids": list(set(job_ids)),
                "optimal_value": value,
            }

    return {
        "final_verdict": "PARTIAL",
        "confidence": 0.3,
        "summary": "No result detected after polling",
        "job_ids": list(set(job_ids)),
        "optimal_value": None,
    }


def main():
    parser = argparse.ArgumentParser(
        description="ADEPT Compute Lifecycle Demo v2 — Multi-Agent with LLM-as-Judge"
    )
    parser.add_argument("--user", default="rigo160")
    parser.add_argument(
        "--password",
        default=os.environ.get("ADEPT_PASSWORD", "changeme"),
    )
    parser.add_argument(
        "--model", default="demos/models/simple_pathway.xml",
    )
    parser.add_argument(
        "--gateway-url",
        default=os.environ.get("AGENT_GATEWAY_URL", "http://localhost:8083"),
    )
    parser.add_argument(
        "--keycloak-url",
        default=os.environ.get("KEYCLOAK_URL", "http://keycloak:8180"),
    )
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument(
        "--mode",
        choices=["single", "multi-agent", "auto"],
        default="auto",
        help="Execution mode (default: auto)",
    )
    args = parser.parse_args()

    model_path = Path(args.model)
    gateway_url = args.gateway_url.rstrip("/")
    keycloak_url = args.keycloak_url.rstrip("/")

    # --- Mode selection (auto-heuristic) ---
    mode = args.mode
    if mode == "auto":
        mode = "multi-agent"
        _log("Auto-mode selected: multi-agent (default for containerized workflows)")

    _log(f"Mode: {mode}")
    _log(f"Authenticating as {args.user} via {keycloak_url}...")
    token = _keycloak_token(keycloak_url, args.user, args.password)
    _log("Authenticated.")

    _log("Creating thread...")
    thread_id = _create_thread(gateway_url, token)
    _log(f"Created thread: {thread_id}")

    file_id = None
    if model_path.exists():
        _log(f"Uploading model: {model_path.name} ({model_path.stat().st_size} bytes)...")
        file_id = _upload_file(gateway_url, token, model_path)
        if file_id:
            _log(f"File registered: {file_id}")
        else:
            _log("Upload failed — agent will use demo volume mount as fallback")

    session_id = f"demo_{uuid.uuid4().hex[:16]}"
    _log(f"Session ID: {session_id}")

    t0 = time.time()

    if mode == "multi-agent":
        prompt = _build_multi_agent_prompt(
            args.user, file_id or model_path.name, model_path.name
        )
        verdict = _run_multi_agent(
            gateway_url, token, thread_id, prompt, session_id, args.timeout
        )
    else:
        prompt = _build_multi_agent_prompt(
            args.user, file_id or model_path.name, model_path.name
        )
        verdict = _run_single_agent(
            gateway_url, token, thread_id, prompt, session_id, args.timeout
        )

    elapsed = time.time() - t0

    # --- Report ---
    _log("-" * 60)
    _log("SESSION COMPLETE")
    _log(f"  Mode:       {mode}")
    _log(f"  Thread ID:  {thread_id}")
    _log(f"  Duration:   {int(elapsed // 60)}m {int(elapsed % 60)}s")
    _log(f"  User:       {args.user}")
    _log(f"  Model:      {model_path.name}")
    _log(f"  Verdict:    {verdict.get('final_verdict', 'UNKNOWN')}")
    _log(f"  Confidence: {verdict.get('confidence', 0.0):.2f}")
    _log(f"  Summary:    {verdict.get('summary', 'N/A')}")
    _log(f"  Jobs:       {', '.join(verdict.get('job_ids', ['unknown']))}")
    if verdict.get("optimal_value") is not None:
        _log(f"  Result:     optimal_value = {verdict['optimal_value']}")
    _log("")
    _log("Attach from any client:")
    _log(f"  CLI:        afk session attach {thread_id}")
    _log(f"  Streamlit:  http://localhost:8503 -> Session Picker -> {thread_id}")
    _log(f"  Langfuse:   http://localhost:3001 -> Traces -> {thread_id}")

    # Exit code: 0 for PASS, 1 for FAIL, 2 for PARTIAL
    exit_codes = {"PASS": 0, "FAIL": 1, "PARTIAL": 2}
    sys.exit(exit_codes.get(verdict.get("final_verdict", "FAIL"), 1))


if __name__ == "__main__":
    main()
