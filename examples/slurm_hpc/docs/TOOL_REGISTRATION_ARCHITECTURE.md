# Tool Registration Architecture

## Overview

The Slurm HPC example stack uses a two-stage architecture for registering MCP tools
with the ADEPT gateway:

1. **Python introspection** generates a JSON contract (`tool_registry.json`)
2. **Shell script** reads that JSON and performs registration/deregistration via the `agentic` CLI

This separation eliminates the class of bugs where embedded JSON inside bash strings
breaks on special characters (single quotes, backslashes, unicode) and ensures
the source of truth is always the Python function signatures.

## Architecture Diagram

```
FastMCP app (Python source of truth)
    |
    | @app.tool decorator → function signature + Pydantic models
    v
generate-registration-schemas.py
    |
    | Introspects app._tool_manager._tools
    | Validates via Pydantic ToolEntry/ToolRegistry models
    v
scripts/tool_registry.json (generated artifact, not version-controlled)
    |
    | jq reads registered_name, remote_name, description, args_schema
    v
register-slurm-tools.sh register|deregister|verify
    |
    | agentic tools register ... --args-schema <json>
    v
ADEPT Gateway → Redis (external_tool:<name>)
```

## Components

### generate-registration-schemas.py

**Location**: `scripts/generate-registration-schemas.py`

Introspects the FastMCP app and generates `tool_registry.json`. Uses Pydantic models
as the contract definition — if introspection produces invalid data, it fails at
generation time (not at registration time inside bash).

**Pydantic models**:

```python
class ToolEntry(BaseModel):
    registered_name: str    # Gateway-facing name (e.g., "slurm_hpc_deception_submit_job")
    remote_name: str        # MCP tool name (e.g., "deception_submit_job")
    description: str        # LLM-facing description
    args_schema: Dict       # Simplified JSON Schema for LangChain _create_args_schema()

class ToolRegistry(BaseModel):
    tool_prefix: str        # "slurm_hpc"
    tools: List[ToolEntry]  # All 27 tools
```

**Modes**:

| Mode | Command | Purpose |
|------|---------|---------|
| Generate (default) | `python3 scripts/generate-registration-schemas.py` | Write `tool_registry.json` |
| Check | `python3 scripts/generate-registration-schemas.py --check` | Compare live vs JSON (exit 1 on drift) |
| Single tool | `python3 scripts/generate-registration-schemas.py --tool <name>` | Inspect one tool's entry |

**Name mapping**: 23 of 27 tools use uniform `{prefix}_{remote_name}`. Four local tools
have shortened registered names via `REGISTERED_NAME_OVERRIDES`:

| Remote Name | Registered Name |
|-------------|----------------|
| `submit_slurm_job` | `slurm_hpc_submit_job` |
| `cancel_slurm_job` | `slurm_hpc_cancel_job` |
| `list_cluster_jobs` | `slurm_hpc_list_jobs` |
| `get_cluster_summary` | `slurm_hpc_cluster_summary` |

### tool_registry.json

**Location**: `scripts/tool_registry.json` (gitignored)

Generated artifact containing all tool metadata. Structure:

```json
{
  "tool_prefix": "slurm_hpc",
  "tools": [
    {
      "registered_name": "slurm_hpc_deception_submit_job",
      "remote_name": "deception_submit_job",
      "description": "Submit a batch job to PNNL Deception HPC cluster...",
      "args_schema": {
        "request": { "type": "object", "properties": {...} },
        "mcp_session_id": { "type": "string", "default": null }
      }
    }
  ]
}
```

This file is regenerated every time `make register-tools` runs (it depends on
`generate-schemas`). It should never be committed — any developer can regenerate it
from the Python source.

### register-slurm-tools.sh

**Location**: `scripts/register-slurm-tools.sh`

Reads `tool_registry.json` via `jq` and performs registration/deregistration/verification.
Requires:
- `jq` (JSON parser)
- `agentic` CLI (ADEPT SDK)
- ADEPT stack running (Keycloak, Redis, agent_gateway)

**Actions**:

| Action | Command | What It Does |
|--------|---------|--------------|
| `register` | `./scripts/register-slurm-tools.sh register` | Health check + register all tools |
| `deregister` | `./scripts/register-slurm-tools.sh deregister` | Remove all tools from gateway |
| `verify` | `./scripts/register-slurm-tools.sh verify` | Check Redis for each tool's key |

## Makefile Targets

```bash
# Generate tool_registry.json from FastMCP introspection
make generate-schemas

# Check if tool_registry.json matches live app (CI gate)
make check-schemas

# Full registration flow (generates JSON first, then registers)
make register-tools

# Remove tools
make deregister-tools

# Verify tools in Redis
make verify-tools
```

`register-tools` depends on `generate-schemas` — the JSON file is always fresh before
registration. This eliminates the drift class of bugs entirely.

## Schema Simplification

The `_simplify_schema()` function converts FastMCP's full JSON Schema output into the
flat format that `_create_args_schema()` in `external_tool_manager.py` expects:

- Resolves `anyOf` patterns (from `Optional[T]`) to simple type strings
- Preserves nested object properties recursively
- Strips metadata that `_create_args_schema()` doesn't consume (`title`, `$defs`)
- Keeps `default` values for fields with defaults

## Framework-Injected Fields

The `mcp_session_id` field appears in tool schemas for tools that accept it as a
function parameter. The framework's `_FRAMEWORK_INJECTED_FIELDS` frozenset
(in `external_tool_manager.py`) makes these fields Optional with None default in the
LangChain args schema, so the LLM never needs to provide them — the
`StreamingToolExecutor` injects them at runtime.

## Drift Detection

Two mechanisms prevent schema drift:

1. **`make check-schemas`** — Compares live introspection against `tool_registry.json`.
   Run in CI or pre-commit to catch when Python signatures change without regenerating.

2. **`test_schema_discovery.py::TestRegistrationSchemaDrift`** — Pydantic round-trip
   test that validates the generated registry matches the live app and serializes
   cleanly.

## Adding a New Tool

1. Add the `@app.tool` decorated function in the appropriate module
2. Run `make generate-schemas` to regenerate `tool_registry.json`
3. Run `make register-tools` to register with the gateway
4. Run `make verify-tools` to confirm Redis has the entry

The shell script auto-discovers the new tool from the JSON — no manual array editing.

## Troubleshooting

**"ERROR: tool_registry.json not found"**
- Run `make generate-schemas` first (or `make register-tools` which does it automatically)

**"ERROR: jq is required"**
- Install: `sudo apt-get install jq` or `brew install jq`

**"ERROR: agentic CLI not found"**
- Activate conda env: `conda activate adept-session`
- Or install: `pip install -e src/`

**Schema drift detected by --check**
- Run `make generate-schemas` to regenerate from current Python source
- Then `make register-tools` to push updated schemas to the gateway

**Registration fails with auth errors**
- Verify `/etc/hosts` has `127.0.0.1 keycloak`
- Check `KEYCLOAK_URL` matches JWT issuer (must use Docker service name)
- Clear stale token cache: `rm ~/.adept-agentic/cache/admin_token.json`
