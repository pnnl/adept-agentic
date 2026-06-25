#!/usr/bin/env python3
"""Post-run analysis for ADEPT compute lifecycle demos.

Cross-references Docker service logs and Langfuse telemetry to produce
a summary of tool calls, token usage, errors, and timing for a given
thread or time window.

Usage:
    # Analyze the most recent demo run
    python demos/analyze_demo_run.py

    # Analyze a specific thread
    python demos/analyze_demo_run.py --thread thread_a2b697d7d3314c01a6b55ffdf60f28d6

    # Analyze runs from last N minutes
    python demos/analyze_demo_run.py --since 60

    # Output as JSON for downstream processing
    python demos/analyze_demo_run.py --format json
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _log(msg: str) -> None:
    print(f"[analyze] {msg}", flush=True)


def _docker_logs(container: str, since_minutes: int) -> str:
    """Get Docker container logs from last N minutes."""
    try:
        result = subprocess.run(
            ["docker", "logs", container, "--since", f"{since_minutes}m"],
            capture_output=True, text=True, timeout=30,
        )
        return result.stdout + result.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _get_langfuse_creds() -> tuple:
    """Get Langfuse credentials from orchestration_service container."""
    try:
        result = subprocess.run(
            ["docker", "exec", "orchestration_service", "env"],
            capture_output=True, text=True, timeout=10,
        )
        pk, sk = "", ""
        for line in result.stdout.splitlines():
            if line.startswith("LANGFUSE_PUBLIC_KEY="):
                pk = line.split("=", 1)[1]
            elif line.startswith("LANGFUSE_SECRET_KEY="):
                sk = line.split("=", 1)[1]
        return pk, sk
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return "", ""


def _langfuse_api(endpoint: str, pk: str, sk: str) -> dict:
    """Call Langfuse public API."""
    url = f"http://localhost:3001/api/public/{endpoint}"
    req = Request(url, headers={"Authorization": ""})
    import base64
    auth = base64.b64encode(f"{pk}:{sk}".encode()).decode()
    req.add_header("Authorization", f"Basic {auth}")
    try:
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except (HTTPError, URLError, Exception):
        return {}


def _find_thread_in_logs(log_dir: Path) -> Optional[str]:
    """Find the most recent thread ID from demo log files."""
    logs = sorted(log_dir.glob("perform_demo_*.log"), reverse=True)
    for log_path in logs:
        content = log_path.read_text()
        match = re.search(r"thread_([a-f0-9]{32})", content)
        if match:
            return f"thread_{match.group(1)}"
    return None


def _extract_docker_tool_calls(logs: str, thread_id: Optional[str] = None) -> list:
    """Extract tool call events from orchestration_service logs."""
    calls = []
    for line in logs.splitlines():
        if "STREAMING_EXECUTOR" in line and "completed" in line:
            match = re.search(
                r"Tool '([^']+)' completed \((\d+) chars, ([\d.]+)s\)", line
            )
            if match:
                calls.append({
                    "tool": match.group(1),
                    "output_chars": int(match.group(2)),
                    "duration_s": float(match.group(3)),
                    "source": "docker/orchestration_service",
                })
        elif "LLM requested tools" in line:
            match = re.search(r"LLM requested tools: \[([^\]]+)\]", line)
            if match:
                tools = [t.strip().strip("'\"") for t in match.group(1).split(",")]
                for t in tools:
                    calls.append({
                        "tool": t,
                        "output_chars": 0,
                        "duration_s": 0,
                        "source": "docker/orchestration_service/requested",
                    })
    return calls


def _extract_slurm_tool_calls(logs: str) -> list:
    """Extract tool execution events from slurm_mcp_server logs."""
    calls = []
    for line in logs.splitlines():
        if "deception_submit_job" in line.lower() or "workspace" in line.lower():
            if "error" in line.lower():
                match = re.search(r"(deception_\w+|workspace_\w+)", line)
                if match:
                    calls.append({
                        "tool": match.group(1),
                        "status": "error",
                        "detail": line.strip()[-200:],
                        "source": "docker/slurm_mcp_server",
                    })
    return calls


def _get_langfuse_traces(pk: str, sk: str, since_minutes: int) -> list:
    """Get recent Langfuse traces."""
    data = _langfuse_api("traces?limit=10", pk, sk)
    traces = data.get("data", [])
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
    result = []
    for t in traces:
        ts_str = t.get("timestamp", "")
        if ts_str:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts >= cutoff:
                result.append(t)
    return result


def _get_trace_observations(trace_id: str, pk: str, sk: str) -> list:
    """Get observations (LLM calls, tool events) for a trace."""
    data = _langfuse_api(f"observations?traceId={trace_id}&limit=50", pk, sk)
    return data.get("data", [])


def _analyze_trace(trace: dict, observations: list) -> dict:
    """Produce analysis summary for a single trace."""
    llm_calls = [o for o in observations if o.get("type") == "GENERATION"]
    tool_events = [o for o in observations if o.get("type") == "EVENT"]

    total_input_tokens = 0
    total_output_tokens = 0
    models_used = set()

    for gen in llm_calls:
        usage = gen.get("usage") or {}
        total_input_tokens += (
            usage.get("input") or usage.get("inputTokens")
            or usage.get("promptTokens") or 0
        )
        total_output_tokens += (
            usage.get("output") or usage.get("outputTokens")
            or usage.get("completionTokens") or 0
        )
        model = gen.get("model") or ""
        if model:
            models_used.add(model)

    tool_names = []
    for evt in tool_events:
        name = evt.get("name", "")
        if name.startswith("tool_output_"):
            tool_names.append(name.replace("tool_output_", ""))

    inp = trace.get("input", {})
    user_input = ""
    if isinstance(inp, dict):
        user_input = inp.get("kwargs", {}).get("user_input", "")

    out = trace.get("output", {})
    output_text = ""
    if isinstance(out, dict):
        output_text = out.get("output", "")

    return {
        "trace_id": trace.get("id", ""),
        "session_id": trace.get("sessionId", ""),
        "timestamp": trace.get("timestamp", ""),
        "user_input_preview": user_input[:200],
        "output_preview": output_text[:300],
        "llm_calls": len(llm_calls),
        "tool_calls": len(tool_events),
        "tool_names": tool_names,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_tokens": total_input_tokens + total_output_tokens,
        "models_used": list(models_used),
        "max_single_call_input": max(
            (
                (o.get("usage") or {}).get("input")
                or (o.get("usage") or {}).get("inputTokens")
                or (o.get("usage") or {}).get("promptTokens")
                or 0
            )
            for o in llm_calls
        ) if llm_calls else 0,
    }


def _format_report(analyses: list, docker_tools: list, slurm_tools: list) -> str:
    """Format a human-readable report."""
    lines = []
    lines.append("=" * 70)
    lines.append("ADEPT COMPUTE LIFECYCLE — POST-RUN ANALYSIS")
    lines.append("=" * 70)
    lines.append("")

    for i, a in enumerate(analyses, 1):
        lines.append(f"--- Run {i}: {a['trace_id'][:16]}... ---")
        lines.append(f"  Timestamp:     {a['timestamp']}")
        lines.append(f"  Session:       {a['session_id']}")
        lines.append(f"  LLM Calls:     {a['llm_calls']}")
        lines.append(f"  Tool Calls:    {a['tool_calls']}")
        lines.append(f"  Tools Used:    {', '.join(a['tool_names']) or 'none'}")
        lines.append(f"  Input Tokens:  {a['total_input_tokens']:,}")
        lines.append(f"  Output Tokens: {a['total_output_tokens']:,}")
        lines.append(f"  Total Tokens:  {a['total_tokens']:,}")
        lines.append(f"  Max Single:    {a['max_single_call_input']:,} input tokens")
        lines.append(f"  Models:        {', '.join(a['models_used']) or 'unknown'}")
        lines.append(f"  Input:         {a['user_input_preview'][:100]}...")
        lines.append(f"  Output:        {a['output_preview'][:100]}...")
        lines.append("")

    if docker_tools:
        lines.append("--- Docker Tool Execution (orchestration_service) ---")
        for tc in docker_tools[:20]:
            lines.append(
                f"  {tc['tool']:50} | {tc['output_chars']:>8} chars | "
                f"{tc['duration_s']:.2f}s"
            )
        lines.append("")

    if slurm_tools:
        lines.append("--- Slurm MCP Server Events ---")
        for st in slurm_tools[:10]:
            lines.append(f"  {st['tool']:30} | {st['status']:6} | {st.get('detail','')[:60]}")
        lines.append("")

    lines.append("=" * 70)

    if analyses:
        total_tokens = sum(a["total_tokens"] for a in analyses)
        total_llm = sum(a["llm_calls"] for a in analyses)
        total_tools = sum(a["tool_calls"] for a in analyses)
        lines.append(f"TOTALS: {len(analyses)} runs, {total_llm} LLM calls, "
                     f"{total_tools} tool calls, {total_tokens:,} tokens")

        problem_runs = [
            a for a in analyses if a["max_single_call_input"] > 30000
        ]
        if problem_runs:
            lines.append("")
            lines.append("WARNING: Runs with excessive context (>30K input tokens):")
            for a in problem_runs:
                lines.append(
                    f"  {a['trace_id'][:16]}... — "
                    f"{a['max_single_call_input']:,} tokens in single call"
                )
                overflow_tools = [
                    t for t in docker_tools
                    if t["output_chars"] > 50000
                ]
                if overflow_tools:
                    for ot in overflow_tools:
                        lines.append(
                            f"    Likely cause: {ot['tool']} "
                            f"returned {ot['output_chars']:,} chars"
                        )

    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Post-run analysis for ADEPT compute lifecycle demos"
    )
    parser.add_argument(
        "--thread", default=None,
        help="Specific thread ID to analyze",
    )
    parser.add_argument(
        "--since", type=int, default=60,
        help="Analyze runs from last N minutes (default: 60)",
    )
    parser.add_argument(
        "--format", choices=["text", "json"], default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--log-dir", default="logs",
        help="Directory containing perform_demo logs",
    )
    args = parser.parse_args()

    log_dir = Path(args.log_dir)

    # If no thread specified, find from latest log
    if not args.thread and log_dir.exists():
        args.thread = _find_thread_in_logs(log_dir)
        if args.thread:
            _log(f"Found thread from latest log: {args.thread}")

    # Collect Docker logs
    _log(f"Collecting Docker logs (last {args.since} minutes)...")
    orch_logs = _docker_logs("orchestration_service", args.since)
    slurm_logs = _docker_logs("slurm_mcp_server", args.since)

    docker_tools = _extract_docker_tool_calls(orch_logs, args.thread)
    slurm_tools = _extract_slurm_tool_calls(slurm_logs)

    # Collect Langfuse traces
    _log("Querying Langfuse traces...")
    pk, sk = _get_langfuse_creds()
    analyses = []

    if pk and sk:
        traces = _get_langfuse_traces(pk, sk, args.since)
        _log(f"Found {len(traces)} traces in last {args.since} minutes")

        for trace in traces:
            if trace.get("name") != "agent_arun":
                continue
            obs = _get_trace_observations(trace["id"], pk, sk)
            analysis = _analyze_trace(trace, obs)
            analyses.append(analysis)
    else:
        _log("WARNING: Could not get Langfuse credentials")

    # Output
    if args.format == "json":
        output = {
            "analyses": analyses,
            "docker_tool_calls": docker_tools,
            "slurm_tool_events": slurm_tools,
            "metadata": {
                "since_minutes": args.since,
                "thread_filter": args.thread,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        print(json.dumps(output, indent=2))
    else:
        report = _format_report(analyses, docker_tools, slurm_tools)
        print(report)


if __name__ == "__main__":
    main()
