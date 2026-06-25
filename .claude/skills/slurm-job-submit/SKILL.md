---
name: slurm-job-submit
description: Submit arbitrary Slurm HPC jobs via ADEPT agent — supports single-agent (v1) and multi-agent (v2 with LLM-as-judge) execution modes. Handles script hardening, mode selection, and result verification.
disable-model-invocation: true
allowed-tools: Bash(make *) Bash(grep *) Bash(ls *) Bash(find *) Bash(cat *) Bash(python3 *) Bash(git *) Read Write Edit
argument-hint: [optional: path-to-script.sh or description of job]
---

You are assisting an ADEPT developer or domain scientist with submitting a Slurm HPC job through the ADEPT agent. This skill handles the full lifecycle: script validation, mode selection, execution, and result verification.

Do not use emojis in any output.
Do not inspect or read files in the user's home directory for credentials.
Always use Makefile targets for execution (never ad-hoc shell invocations).

Base directory: `examples/slurm_hpc/`

---

## Lessons Learned Reference

This skill is built on findings from 5+ production demo sessions on Deception HPC.

### From v1 (Single-Agent) — L1 through L8

| ID | Lesson | Impact |
|----|--------|--------|
| L1 | Deception filesystem: `/scratch/` is node-local (ephemeral), `$HOME/adept-workspace/` is shared QFS | Path violations cause "file not found" on compute nodes |
| L2 | Apptainer on compute nodes lacks `/dev/fuse` — `--unsquash` is mandatory | Jobs hang or crash without it |
| L3 | Agent prompt must use unconditional sequential steps ("do ALL in SINGLE turn") | Multi-turn stalls happen when agent is given conditional logic |
| L4 | Harness must inject prior turn output into subsequent prompts (turn propagation) | Without it, agent loses context on what it already did |
| L5 | Result detection regex must account for markdown formatting (bold `**`, backticks) | Regex too narrow = demo never exits on success |
| L6 | Agent stderr must be separated from stdout (sbatch `2>/dev/null` for module load noise) | Stderr noise confuses result parsing |
| L7 | SSE streaming splits tokens at arbitrary byte boundaries — reassemble before parsing job IDs | Partial IDs like "86" + "9838" = "869838" |
| L8 | SIF provisioning is the AGENT's job (workspace_upload_file + submit copy script) — NOT manual infra | The demo's value proposition IS agent-mediated lifecycle |

### From v2 (Multi-Agent) — M1 through M6

| ID | Lesson | Impact |
|----|--------|--------|
| M1 | Judge persona must evaluate tool call RESULTS, not agent prose | Agents claim success when tools return errors |
| M2 | Observer detects anti-patterns (retry loops, hallucinated IDs, session drift) passively | Critical for reliability assessment without blocking execution |
| M3 | FinalVerdict JSON replaces regex — structured output is more reliable than pattern matching | Eliminates false positives/negatives from regex |
| M4 | Multi-agent session needs consistent session_id across all tool calls | Session drift = files land in wrong workspace |
| M5 | Judge termination rule: emit verdict after at most 3 exchanges | Prevents infinite evaluation loops |
| M6 | Mode auto-selection: multi-agent for containerized workflows, single for quick scripts | Overhead of 3 personas not justified for simple sbatch |

---

## Phase 1: Orient

Read the user's request and classify the job:

**If argument is a script path**: Read the script, validate it exists, extract metadata.
**If argument is a description**: Help the user create the job script.
**If no argument**: Ask what they want to run.

Gather required information:

1. **Script or command**: What to execute on the cluster
2. **Target cluster**: Which HPC system (default: `deception`)
3. **Container requirement**: Does the job need Apptainer/Singularity? (SIF path)
4. **Resource requirements**: nodes, time limit, partition (or defaults)
5. **Input files**: Any data files that need staging to the workspace
6. **Expected output**: What result indicates success

```bash
# Check available clusters
grep -r "cluster" examples/slurm_hpc/config/ --include="*.yaml" -l 2>/dev/null
ls examples/slurm_hpc/config/clusters/ 2>/dev/null
```

---

## Phase 2: Mode Selection

Apply heuristics to recommend single-agent or multi-agent execution:

### Auto-mode decision matrix

| Criterion | Single-Agent (v1) | Multi-Agent (v2) |
|-----------|-------------------|-------------------|
| Script complexity | < 20 lines, no SIF | > 20 lines or SIF required |
| Multi-step staging | No staging needed | Files + SIF + license staging |
| Verification need | Regex on output sufficient | Structured verdict needed |
| Cost sensitivity | Lower (1 LLM session) | Higher (3 personas, more tokens) |
| Failure diagnosis | Basic (pass/fail) | Rich (per-step verdicts, anomaly detection) |

Present the recommendation:

**"Based on [criteria], I recommend [mode]. This will [brief description of what happens]. Proceed?"**

Options the user can choose:
- `single` — v1 harness, regex-based result detection
- `multi-agent` — v2 harness with executor/judge/observer personas
- `auto` — let the harness decide (default: multi-agent for containerized workflows)

---

## Phase 3: Script Hardening

Before submission, apply these transforms to prevent common failures:

### Mandatory transforms (always apply)

1. **Path validation**: Replace any `~` with `$HOME`, replace `/scratch/` with `$HOME/adept-workspace/` for shared files
2. **Stderr separation**: Add `2>/dev/null` after `module load` commands
3. **Set strict mode**: Add `set -euo pipefail` if not present
4. **Shebang**: Ensure `#!/bin/bash` is first line

### Conditional transforms (apply when detected)

5. **Apptainer --unsquash**: If script uses `apptainer exec` or `singularity exec`, ensure `--unsquash` flag is present (L2)
6. **Result marker**: If script produces a numeric result, add `echo "RESULT:<key>=<value>"` at the end
7. **GRB_LICENSE_FILE**: If Gurobi is used, add `export GRB_LICENSE_FILE="$(pwd)/gurobi.lic"` before execution

### Validation checklist

```bash
# Check for path violations
grep -n "~/" script.sh && echo "FAIL: tilde in path"
grep -n "/scratch/" script.sh && echo "WARNING: /scratch/ is node-local"

# Check for apptainer without --unsquash
grep -n "apptainer exec" script.sh | grep -v "\-\-unsquash" && echo "FAIL: missing --unsquash"

# Check for module load without stderr redirect
grep -n "module load" script.sh | grep -v "2>/dev/null" && echo "WARNING: noisy module load"
```

Present the hardened script to the user for approval before proceeding.

---

## Phase 4: Execute

### Single-Agent Mode (v1)

```bash
cd examples/slurm_hpc
mkdir -p logs && nohup make perform-demo \
  USER="<username>" \
  PASSWORD="<password>" \
  MODEL="<model-file-if-applicable>" \
  GATEWAY_URL="<gateway-url>" \
  TIMEOUT="<timeout>" \
  > logs/slurm_job_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

### Multi-Agent Mode (v2)

```bash
cd examples/slurm_hpc
mkdir -p logs && nohup make perform-demo-v2 \
  USER="<username>" \
  PASSWORD="<password>" \
  MODEL="<model-file-if-applicable>" \
  GATEWAY_URL="<gateway-url>" \
  TIMEOUT="<timeout>" \
  MODE="multi-agent" \
  > logs/slurm_job_v2_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

### Monitoring execution

```bash
# Follow the log
tail -f logs/slurm_job_*.log | grep -E "\[perform-demo|TURN|verdict|RESULT"

# Check MCP server logs for tool calls
docker logs slurm_mcp_server --since 10m 2>&1 | grep -v sse_starlette | grep "submit_job\|upload_file"
```

---

## Phase 5: Report

### Single-Agent Result Interpretation

Check the log for result detection:
```bash
# Look for optimal value
grep -i "optimal\|objective\|flux\|RESULT:" logs/slurm_job_*.log | tail -5

# Check exit code
echo "Exit code: $?"
```

### Multi-Agent Result Interpretation

Parse the FinalVerdict JSON from the log:
```bash
# Extract verdict
grep -o '{"final_verdict".*}' logs/slurm_job_v2_*.log | python3 -m json.tool

# Quick status
grep "Verdict:" logs/slurm_job_v2_*.log
grep "Confidence:" logs/slurm_job_v2_*.log
```

### Post-execution analysis

```bash
# Cross-reference with Docker logs and Langfuse traces
cd examples/slurm_hpc
make analyze-demo SINCE=30
```

### Result reporting template

Report to the user:

```
Job Submission Result:
  Mode:       <single|multi-agent>
  Cluster:    <cluster-name>
  Verdict:    <PASS|PARTIAL|FAIL>
  Job IDs:    <comma-separated>
  Duration:   <Nm Ns>
  Result:     <key=value if applicable>
  Log:        <log-file-path>

Next steps:
  - <if PASS: attach session for details>
  - <if PARTIAL: check which step failed>
  - <if FAIL: diagnose with analyze-demo>
```

---

## Troubleshooting

### Common failure patterns and fixes

| Symptom | Cause | Fix |
|---------|-------|-----|
| "file not found" on compute node | Used `/scratch/` for shared file | Use `$HOME/adept-workspace/` (L1) |
| Job hangs at apptainer exec | Missing `--unsquash` | Add flag (L2) |
| Agent stalls after first tool call | Prompt has conditional logic | Rewrite as unconditional sequence (L3) |
| Result not detected (v1) | Regex too narrow or markdown formatting | Widen regex or switch to v2 (L5, M3) |
| Session files in wrong directory | session_id drift | Verify consistent session_id across calls (M4) |
| Judge never emits verdict | Too many evaluation rounds | Check termination rule (M5) |
| Tool returns error but agent says success | Judging prose not results | Use v2 with judge persona (M1) |

### Escalation path

If the job fails repeatedly:
1. Check MCP server logs: `docker logs slurm_mcp_server --since 30m`
2. Check SSH connectivity: `make test-ssh-connection CLUSTER=deception`
3. Check workspace permissions: `make workspace ACTION=check CLUSTER=deception`
4. Run the operator skill: `/slurm-hpc-manage health`
