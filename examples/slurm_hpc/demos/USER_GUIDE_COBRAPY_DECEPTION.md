# Running COBRApy/Gurobi FBA on Deception via ADEPT

Step-by-step guide for submitting metabolic optimization jobs to PNNL Deception HPC
through ADEPT's Slurm MCP server. Covers setup, execution, and monitoring.

**Audience**: Kai (dowd665), August (geor228), Paul (rigo160)
**Prerequisites**: Account on this RC gateway host + account on Deception HPC

---

## Table of Contents

1. [One-Time Setup (10 minutes)](#1-one-time-setup)
2. [Running via Streamlit (Recommended)](#2-running-via-streamlit)
3. [Running via CLI](#3-running-via-cli)
4. [Running via Claude Code / VS Code](#4-running-via-claude-code)
5. [Monitoring and Troubleshooting](#5-monitoring-and-troubleshooting)
6. [Using Custom Models](#6-using-custom-models)
7. [Observability: Cross-Referencing Logs and Langfuse](#7-observability)

---

## 1. One-Time Setup

### Step 1a: Generate SSH keypair for Deception

Run these commands as yourself on the RC gateway host (no sudo needed):

```bash
cd /data/workspace/adept-20260317/examples/slurm_hpc

# Create your key directory
mkdir -p ssh_keys/<your-username>

# Generate ed25519 keypair
ssh-keygen -t ed25519 \
  -f ssh_keys/<your-username>/adept_deception_ed25519 \
  -N "" \
  -C "adept-mcp@deception"

# Lock down private key
chmod 600 ssh_keys/<your-username>/adept_deception_ed25519

# Verify
ls -la ssh_keys/<your-username>/
```

Replace `<your-username>` with your Deception username: `dowd665`, `geor228`, or `rigo160`.

### Step 1b: Copy public key to Deception

```bash
# Interactive (enter your Deception password once):
ssh-copy-id -i ssh_keys/<your-username>/adept_deception_ed25519.pub \
  <your-username>@deception.pnl.gov

# Verify passwordless login works:
ssh -i ssh_keys/<your-username>/adept_deception_ed25519 \
  <your-username>@deception.pnl.gov "hostname && whoami"
```

Expected output: `deception02` (or similar login node) and your username.

### Step 1c: Verify Deception environment

```bash
ssh <your-username>@deception.pnl.gov << 'EOF'
module load python/3.11 2>/dev/null || true
module load gurobi/11.0 2>/dev/null || true
python3 -c "import cobra; import gurobipy; print(f'cobra={cobra.__version__}, gurobi={gurobipy.grbversion()}')"
echo "Gurobi license server:"
timeout 3 bash -c "echo >/dev/tcp/leghorn.emsl.pnl.gov/41954" 2>/dev/null && echo "  REACHABLE" || echo "  UNREACHABLE"
EOF
```

If COBRApy/gurobipy are not available via module load, the demo will use the Apptainer
SIF container (built automatically on first run).

### Step 1d: Get your ADEPT account (Keycloak user creation)

Your Deception username needs a corresponding ADEPT user account in Keycloak. This is
created via the **Agent Gateway Management UI** by an admin (Paul).

**If you are the admin (Paul) creating accounts for Kai/August:**

1. Port-forward to the Management UI (if accessing from your laptop via VS Code SSH):
   ```
   VS Code → Ports panel → Forward port 8502 → localhost:8502
   ```
   Or from any SSH session to the RC gateway:
   ```bash
   ssh -L 8502:localhost:8502 <you>@<rc-gateway-host>
   ```

2. Open: **http://localhost:8502**

3. Log in with the `admin` account

4. Navigate to **User Management** → **Create User**

5. Create accounts with these details:

   | Field | Kai | August |
   |-------|-----|--------|
   | Username | `dowd665` | `geor228` |
   | Password | (set a temporary password) |  (set a temporary password) |
   | Groups | `notebook-users` | `notebook-users` |

6. Notify each user of their credentials

**Service endpoints:**

| Service | Container Port | Host Port | Access |
|---------|---------------|-----------|--------|
| Agent Gateway Management UI | 8502 | **8502** | Admin user management, tool registration |
| Streamlit v2 (chat) | 8503 | **8503** | User-facing agent chat interface |
| Streamlit v1 (legacy) | 8501 | **8501** | Legacy interface |

**VS Code SSH port forwarding (for Kai/August accessing from their laptops):**

Since the RC gateway host is not directly exposed to the internet, Kai and August access
ADEPT services via VS Code's built-in port forwarding over their SSH connection:

1. Open VS Code → Connect to RC gateway via Remote-SSH
2. Open the **Ports** panel (View → Ports, or Ctrl+Shift+P → "Forward a Port")
3. Forward these ports:

   | Local Port | Remote Port | Service |
   |-----------|-------------|---------|
   | 8503 | 8503 | Streamlit v2 (chat with agent) |
   | 8502 | 8502 | Management UI (admin only) |
   | 3001 | 3001 | Langfuse (observability traces) |
   | 8083 | 8083 | Agent Gateway API (for CLI/SDK access) |

4. Access Streamlit at: **http://localhost:8503** in your local browser

Alternatively, forward ports via command line:
```bash
ssh -L 8503:localhost:8503 -L 3001:localhost:3001 -L 8083:localhost:8083 \
  <your-username>@<rc-gateway-host>
```

---

## 2. Running via Streamlit (Recommended)

### Step 2a: Open Streamlit v2

Navigate to: **http://localhost:8503** (requires VS Code port forwarding — see Step 1d)

Log in with your Keycloak credentials (username: your Deception username, e.g. `dowd665`).

### Step 2b: Start a new session

Click "New Session" (or use an existing one).

### Step 2c: Submit your request

Type a natural language prompt. Examples:

**Simple test (bundled 5-reaction model, ~2 minutes):**
```
Run COBRApy FBA on the simple pathway model on Deception HPC using my account dowd665.
Use the preflight, build SIF, and run stages. Report the optimal biomass flux.
```

**Production-scale model (iJN1463, ~5 minutes):**
```
Run flux balance analysis on the iJN1463 Pseudomonas putida model on Deception.
My username is dowd665. Build the Apptainer container if it doesn't exist yet.
Report the optimal value and number of reactions.
```

**Skip preflight (workspace already provisioned):**
```
Submit a Gurobi FBA job to Deception for user dowd665.
Skip the preflight check. Use the cached SIF container.
Model: simple_pathway.xml
```

### Step 2d: Watch the agent work

The agent will:
1. Upload your model file (if specified)
2. Submit a pre-flight job (validates workspace, modules, license)
3. Submit a SIF build job (if container doesn't exist)
4. Submit the FBA execution job (with `--dependency=afterok` on previous jobs)
5. Poll job status until completion
6. Report results (optimal_value, status, runtime)

You'll see each tool call in the chat as it happens.

### Step 2e: Note your thread ID

The session/thread ID is visible in the Streamlit sidebar. You can use this ID to:
- Resume the conversation later
- Check status from CLI or Claude Code
- Find the trace in Langfuse

---

## 3. Running via CLI

### Option A: Direct SSH demo script (bypasses agent, good for testing)

```bash
cd /data/workspace/adept-20260317/examples/slurm_hpc

# Full lifecycle: preflight + build SIF + run FBA
python demos/cobrapy_fba_deception.py --user dowd665 --build-sif

# Skip preflight (already provisioned):
python demos/cobrapy_fba_deception.py --user dowd665 --skip-preflight

# With a specific model:
python demos/cobrapy_fba_deception.py --user dowd665 --model demos/models/simple_pathway.xml

# Dry run (shows what would be submitted):
python demos/cobrapy_fba_deception.py --user dowd665 --build-sif --dry-run
```

### Option B: Agent-driven via afk CLI (exercises full ADEPT path)

```bash
# Start a new session and chat with the agent
afk chat --model agentic-framework:scientific-agent-v1

# Then type your request:
> Run FBA on simple_pathway.xml on Deception for user dowd665. Full lifecycle.
```

### Option C: make perform-demo (automated, logs everything)

```bash
cd /data/workspace/adept-20260317/examples/slurm_hpc

make perform-demo USER=dowd665 MODEL=demos/models/simple_pathway.xml
```

This creates a thread, streams output to console, and prints the thread_id for later
access from any client.

---

## 4. Running via Claude Code

If you're using the ADEPT MCP connector in Claude Code (VS Code or Desktop):

### Start a new compute session

```
You: Submit a new COBRApy FBA job to Deception for user geor228.
     Use the simple pathway model and build the SIF if needed.
```

### Attach to an existing session (session portability)

After running `make perform-demo` or starting via Streamlit, you get a thread_id.
Use it to continue the conversation from Claude Code:

```
You: Check on my Deception HPC jobs. My session is thread_abc123def456.

You: What was the optimal biomass flux from my last FBA run?
     Session: thread_abc123def456
```

The Claude adaptor communicates with ADEPT via Responses API, using the same thread
persistence as Streamlit and CLI. Any thread_id created by one client is accessible
from any other client — PostgreSQL stores the canonical state.

### How it works

```
Claude Code -> ADEPT MCP Connector -> Agent Gateway -> Orchestration Service
                                                            |
                                                    thread_id (shared)
                                                            |
                                                    Same PostgreSQL state
```

The connector passes `session_id=<thread_id>` to the ADEPT `adept_chat` tool.
The orchestration service loads the full conversation history (including prior
tool calls and job IDs) and the agent can query Slurm status for those jobs.

---

## 5. Monitoring and Troubleshooting

### Check job status on Deception directly

```bash
ssh <your-username>@deception.pnl.gov "sacct --user=<your-username> --format=JobID,JobName,State,ExitCode,Elapsed --starttime=$(date -d '1 hour ago' +%Y-%m-%dT%H:%M) 2>/dev/null || squeue -u <your-username>"
```

### View job output

```bash
ssh <your-username>@deception.pnl.gov "cat /scratch/<your-username>/adept_jobs/fba-<jobid>.out"
```

### Check pre-flight report

```bash
ssh <your-username>@deception.pnl.gov "cat /people/<your-username>/adept-workspace/.adept-preflight.json"
```

### Langfuse traces

Navigate to: **http://localhost:3001** (requires port forward — see Step 1d)

Filter by thread_id or username to see full tool call traces, token usage, and timing.

### Common issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| "SSH key not provisioned" | No key in `ssh_keys/<user>/` | Complete Step 1a-1b |
| "Permission denied (publickey)" | Key not in Deception `authorized_keys` | Re-run `ssh-copy-id` (Step 1b) |
| Job state: FAILED | Check stderr: `cat /scratch/<user>/adept_jobs/fba-<jobid>.err` | Usually module load or license issue |
| "Gurobi license server unreachable" | Network issue from compute node | Contact sysadmin — leghorn.emsl.pnl.gov:41954 must be reachable |
| "No module named cobra" | SIF not built, module not available | Use `--build-sif` flag to build Apptainer container |
| Agent doesn't find Slurm tools | Slurm MCP server not registered | Run `cd examples/slurm_hpc && make register-tools` |

---

## 6. Using Custom Models

### Bundled test model

`demos/models/simple_pathway.xml` — 5 reactions, expected optimal = 10.0.
Always available, good for validation.

### Download genome-scale models from BiGG

```bash
cd /data/workspace/adept-20260317/examples/slurm_hpc/demos/models

# iJN1463 — Pseudomonas putida (2583 reactions, production-scale)
curl -L "http://bigg.ucsd.edu/static/models/iJN1463.xml.gz" | gunzip > iJN1463.xml

# E. coli Core (95 reactions, quick validation)
curl -L "http://bigg.ucsd.edu/static/models/e_coli_core.xml.gz" | gunzip > e_coli_core.xml
```

These are gitignored (too large for version control).

### Use your own SBML model

Any valid SBML Level 3 XML file works. Place it in `demos/models/` or upload via the
ADEPT file API. Reference it in your prompt:

```
Run FBA on my custom model /path/to/my_model.xml on Deception for user dowd665.
```

Or via CLI:
```bash
python demos/cobrapy_fba_deception.py --user dowd665 --model /path/to/my_model.xml
```

---

## 7. Observability: Cross-Referencing Logs and Langfuse {#7-observability}

When debugging agent-driven runs, you have four complementary data sources. Each gives
a different view of the same execution:

| Source | What It Shows | How to Access |
|--------|---------------|---------------|
| **Demo log** (`logs/perform_demo_*.log`) | Thread ID, file upload status, SSE chunks from agent | `cat logs/perform_demo_*.log` |
| **orchestration_service** Docker logs | LLM calls, tool routing, graph state, token counts | `docker logs orchestration_service --since 30m` |
| **slurm_mcp_server** Docker logs | SSH commands, sbatch output, workspace file operations | `docker logs slurm_mcp_server --since 30m` |
| **Langfuse** (http://localhost:3001) | Traces, observations, token usage, latency, cost | Web UI or API (see below) |

### Automated Cross-Reference

Run the post-run analysis script to correlate all four sources automatically:

```bash
# Analyze runs from last 60 minutes
make analyze-demo

# Analyze last 2 hours, output as JSON
make analyze-demo SINCE=120 FORMAT=json

# Or run directly
python demos/analyze_demo_run.py --since 60 --format text
```

This produces a unified report showing:
- Tool calls with duration and output size
- LLM token consumption per call (identifies context overflow)
- Error events across all services
- Warnings when a single tool output exceeds 30K tokens (context overflow risk)

### Manual Log Cross-Reference

#### Step 1: Find the thread ID

From your demo log:
```bash
grep "Created thread:" logs/perform_demo_*.log | tail -1
# Output: [perform-demo] Created thread: thread_a2b697d7d3314c01a6b55ffdf60f28d6
```

#### Step 2: Check orchestration_service for tool calls

```bash
docker logs orchestration_service --since 30m 2>&1 | \
  grep -E "(STREAMING_EXECUTOR.*completed|LLM requested tools|error)" | tail -20
```

Key patterns:
- `Tool '<name>' completed (N chars, Xs)` — successful tool execution
- `LLM requested tools: ['tool_name']` — what the LLM decided to call
- `invalid partition specified: general` — common partition error

#### Step 3: Check slurm_mcp_server for SSH/sbatch details

```bash
docker logs slurm_mcp_server --since 30m 2>&1 | \
  grep -E "(submit_job|workspace|sbatch|error)" | tail -20
```

Key patterns:
- `deception_submit_job` with `partition='general'` — invalid partition
- `workspace_upload_file` — file staging to cluster
- SSH connection timing and authentication

#### Step 4: Query Langfuse API for traces and token usage

```bash
# Get Langfuse credentials (from orchestration_service container)
LANGFUSE_PK=$(docker exec orchestration_service env | grep LANGFUSE_PUBLIC_KEY | cut -d= -f2)
LANGFUSE_SK=$(docker exec orchestration_service env | grep LANGFUSE_SECRET_KEY | cut -d= -f2)

# List recent traces
curl -s "http://localhost:3001/api/public/traces" \
  -u "$LANGFUSE_PK:$LANGFUSE_SK" | python3 -m json.tool | head -40

# Get observations (tool calls + LLM calls) for a specific trace
TRACE_ID="57cde24fa53a1538537401da747ab692"
curl -s "http://localhost:3001/api/public/observations?traceId=$TRACE_ID&limit=20" \
  -u "$LANGFUSE_PK:$LANGFUSE_SK" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for o in data.get('data', []):
    name = o.get('name','?')
    otype = o.get('type','?')
    usage = o.get('usage') or {}
    inp = usage.get('input') or usage.get('promptTokens') or 0
    out = usage.get('output') or usage.get('completionTokens') or 0
    print(f'  {otype:12} | {name:50} | in={inp} out={out}')
"
```

#### Step 5: Correlate session IDs

The Langfuse `sessionId` maps to the orchestration service's `mcp_session_id`:
- Demo log: `thread_<hash>` (the thread_id passed to Responses API)
- Langfuse: `response_<hash>` (internal session ID for the agent run)
- Docker logs: both appear in structured log fields

To find a Docker log entry for a specific Langfuse trace:
```bash
docker logs orchestration_service --since 60m 2>&1 | grep "response_57dfb22b"
```

### Common Issues Diagnosed via Logs

| Symptom | Where to Look | Root Cause |
|---------|---------------|------------|
| Agent says "no registered files" | Langfuse: first tool = `list_uploaded_files` | File not linked to session context |
| `invalid partition specified: general` | orchestration_service logs | Agent hallucinated partition name |
| Garbled/truncated output | Langfuse: check input tokens > 50K | Tool returned oversized JSON (get_cluster_summary) |
| Agent asks user for confirmation | Demo log: SSE output | Non-directive prompt; agent uncertain |
| 401 on thread creation | Demo log + agent_gateway | Token issuer mismatch (localhost vs keycloak hostname) |
| 422 on file upload | Demo log | Missing `purpose` form field in multipart body |

### Langfuse Web UI

Access http://localhost:3001 in your browser for the visual trace explorer:

1. **Traces** tab: Shows all agent runs with timing, status, and session grouping
2. Click a trace to see the full **observation tree** (LLM calls + tool events)
3. **Generations** tab: Token usage breakdown per LLM call
4. Filter by session ID to group related runs

---

## Quick Reference Card

| Action | Command |
|--------|---------|
| Generate SSH key | `ssh-keygen -t ed25519 -f ssh_keys/<user>/adept_deception_ed25519 -N ""` |
| Copy key to Deception | `ssh-copy-id -i ssh_keys/<user>/adept_deception_ed25519.pub <user>@deception.pnl.gov` |
| Full lifecycle (CLI) | `python demos/cobrapy_fba_deception.py --user <user> --build-sif` |
| Agent-driven (Streamlit) | Login → "Run FBA on Deception for user <user>" |
| Agent-driven (CLI) | `afk chat` → "Run FBA on Deception for <user>" |
| Agent-driven (API) | `make perform-demo USER=<user> PASSWORD=<pass>` |
| Post-run analysis | `make analyze-demo SINCE=60` |
| Check jobs | `ssh <user>@deception.pnl.gov "sacct -u <user> --starttime=today"` |
| View output | `ssh <user>@deception.pnl.gov "cat /scratch/<user>/adept_jobs/fba-<jobid>.out"` |
| Download model | `curl -L "http://bigg.ucsd.edu/static/models/<name>.xml.gz" \| gunzip > models/<name>.xml` |
