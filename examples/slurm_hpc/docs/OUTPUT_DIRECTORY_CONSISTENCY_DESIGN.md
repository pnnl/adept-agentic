# Output Directory Consistency Design

## Problem Statement

When the ADEPT agent submits Slurm jobs, three independent mechanisms determine where
job output lands:

1. `#SBATCH --output=<path>` directives inside the script (hardcoded by template authors)
2. `--chdir=<dir>` on the sbatch command line (set by FabricSSHTransport)
3. `workspace_read_file` tool path resolution (`~/adept-workspace/{session_id}/`)

If these three paths disagree, the agent cannot read job output after submission.

## Root Cause Analysis

Prior to this fix:
- Template scripts had hardcoded absolute `#SBATCH --output=/scratch/%u/...` paths
- The transport layer set `--chdir` to the workspace but did NOT set `--output`
- `#SBATCH --output` (absolute path) takes precedence over `--chdir` for output routing
- The LLM agent inconsistently passes `session_id` across tool calls within the same
  conversation, causing some jobs to land in /scratch and others in the workspace

## Design Decision

**When session_id is provided, the transport layer owns output routing.**

The transport layer now injects `--output` and `--error` sbatch CLI options pointing
at the workspace directory. sbatch CLI options override in-script `#SBATCH` directives
(this is documented Slurm behavior). This makes output retrieval deterministic regardless
of what the script template contains.

### sbatch Precedence Rule (from Slurm documentation)

```
CLI options  >  environment variables  >  #SBATCH directives in script
```

By injecting `--output=~/adept-workspace/{session_id}/slurm-%j.out` on the command line,
we guarantee the output location regardless of template content.

## Implementation

### Transport Layer (fabric_transport.py)

When `session_id` is provided to `submit_job()`:

```python
output_path = f"{workspace_dir}/slurm-%j.out"
error_path = f"{workspace_dir}/slurm-%j.err"
```

These are passed through `build_sbatch_options()` which appends `--output=` and
`--error=` to the sbatch command line.

### Parser Layer (slurm_parsers.py)

`build_sbatch_options()` accepts optional `output_path` and `error_path` parameters.
When non-None, they produce `--output=` and `--error=` CLI flags.

### Template Scripts

All `#SBATCH --output` and `#SBATCH --error` directives removed from:
- `demos/preflight/preflight_workspace.sh`
- `demos/apptainer/build_sif.sh`
- `demos/apptainer/run_fba.sh`

These are dead code when submitted via the transport layer (CLI overrides them) and
misleading to readers who might think they control output routing.

### Demo Driver (perform_demo.py)

Turn 1 prompt now explicitly instructs the agent to pass `session_id` to ALL tool calls.
This ensures consistent session_id propagation across the multi-tool conversation.

## Guarantees

With this design:

| Scenario | Output Location |
|----------|----------------|
| session_id provided | `~/adept-workspace/{session_id}/slurm-{jobid}.out` |
| session_id omitted | Default Slurm behavior (CWD or script-defined path) |

`workspace_read_file` uses the same `~/adept-workspace/{session_id}/` path convention,
so output retrieval is guaranteed to succeed when session_id is consistently passed.

## session_id as the Single Coordination Key

```
deception_submit_job(session_id=X)
    → sbatch --output=~/adept-workspace/X/slurm-%j.out ...
    → slurm-{jobid}.out written to ~/adept-workspace/X/

workspace_read_file(session_id=X, remote_filename="slurm-{jobid}.out")
    → reads from ~/adept-workspace/X/slurm-{jobid}.out
```

The session_id is the ONLY coordination key between submit and read. No other state
(job working directory, script directives, scratch paths) influences the output location
when session_id is provided.

## mcp_session_id Fallback (Session 67)

When this MCP server is accessed through the ADEPT orchestration service, the
MCPToolWrapper injects `mcp_session_id` into tool call parameters. The tools now
accept this as an explicit function parameter and use it as a fallback when
`request.session_id` is None:

```python
@app.tool
async def deception_submit_job(
    request: DeceptionJobSubmissionRequest,
    mcp_session_id: Optional[str] = None,  # Injected by ADEPT orchestration
) -> Dict[str, Any]:
    effective_session_id = request.session_id or mcp_session_id
```

This makes the system robust against LLM prompt engineering fragility — even if the
reasoning model doesn't include session_id in the tool call arguments, the framework
automatically provides it.

### Known Caveat: Streaming Executor Schema Guard

The ADEPT orchestration's `StreamingToolExecutor` (line 108 of
`streaming_tool_executor.py`) only injects `mcp_session_id` when the LangChain tool's
`args_schema` declares it as a model field:

```python
if (self.mcp_session_id
    and "mcp_session_id" not in tool_args
    and "mcp_session_id" in getattr(tool.args_schema, "model_fields", {})):
```

For external SSE-based MCP tools (like this slurm_mcp_server), the LangChain tool schema
is generated from the MCP tool's JSON schema — which only declares the top-level `request`
property. The `mcp_session_id` function parameter is exposed in FastMCP's schema but NOT
in the LangChain wrapper's `args_schema.model_fields`. This means:

- **MCPToolWrapper._arun() (line 622)**: Injects unconditionally — WORKS for built-in tools
- **StreamingToolExecutor (line 108)**: Conditional on schema — SKIPPED for external SSE tools

**Impact**: When the streaming executor handles external MCP tool calls (which it does
for long-running tools like job submission), `mcp_session_id` arrives as `None` even
though the orchestration has it. The LLM must include `session_id` in the request body.

**Mitigation**: The prompt in perform_demo.py explicitly instructs the agent to pass
session_id. The `mcp_session_id` fallback remains correct for the non-streaming path
and for future fixes to the streaming executor.

**Fix location**: `src/agentic_framework_pkg/orchestration_service/scientific_workflow/streaming_tool_executor.py` line 108 — replace the LangChain `args_schema` check with an MCP `inputSchema` check (the unconditional removal is unsafe because FastMCP 2.x TypeAdapter raises ValidationError on tools that don't declare `mcp_session_id`). See `docs/bugfixes/SESSION_67_STREAMING_EXECUTOR_MCP_SESSION_ID_INJECTION_BUG.md` for full analysis.

## Test Coverage

- `tests/unit/test_fabric_transport.py::TestSubmitJobWorkspaceCWD`
  - `test_session_id_injects_output_path` — verifies --output/--error in sbatch command
  - `test_no_session_id_omits_output_path` — verifies no injection without session_id
- `tests/unit/test_slurm_parsers.py::TestBuildSbatchOptions`
  - `test_output_path_included_when_set` — verifies flag generation
  - `test_output_path_omitted_when_none` — verifies no flag when None
- `tests/unit/test_deception_tools.py::TestMcpSessionIdFallback`
  - `test_submit_uses_mcp_session_id_when_request_has_none` — mcp_session_id fills in
  - `test_submit_explicit_session_id_wins_over_mcp` — request.session_id takes precedence
  - `test_submit_no_session_id_at_all` — no workspace when both None
  - `test_submit_mcp_session_id_logged` — info log emitted on auto-injection
- `tests/unit/test_workspace_tools.py::TestMcpSessionIdFallback`
  - `test_list_files_uses_mcp_session_id` — mcp_session_id fills in for workspace_list
  - `test_list_files_explicit_session_id_wins` — explicit takes precedence
  - `test_read_file_uses_mcp_session_id` — mcp_session_id fills in for workspace_read
  - `test_no_session_id_at_all_returns_error` — proper error when both None
- `tests/unit/test_workspace_tools.py::TestSessionIdOptional`
  - 10 regression tests for Optional session_id + runtime guard behavior
