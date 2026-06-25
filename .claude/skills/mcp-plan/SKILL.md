---
name: mcp-plan
description: Analyze a Python library and produce an MCP server implementation plan. Audits the API surface, maps functions to tools, classifies dependencies, and identifies session boundaries. Use during Phase 1-2 (Plan + Discover) of the feature development lifecycle.
disable-model-invocation: true
allowed-tools: Bash(pip *) Bash(python3 *) Bash(grep *) Bash(find *) Bash(ls *) Bash(git *) Bash(gh *) Read Write Edit Glob Grep
argument-hint: [optional: python-package-name]
---

You are assisting an ADEPT developer with planning a new MCP server that wraps an existing Python library. This skill covers Phase 1 (Plan) and Phase 2 (Discover) in the feature development lifecycle.

Do not use emojis in any output.
Enforce all rules in `docs/development/AGENT_CODING_RULES.md` throughout this skill execution.
Do not include any AI agent references in commit messages, trailers, or document metadata.
Pause for developer confirmation at each numbered step before proceeding.

---

## Prerequisites

Before running this skill, the developer should have completed:
- Phase 0 (Orient): Read `CLAUDE.md`, `docs/development/CODE_HYGIENE.md`, `docs/MCP_SERVER_BLUEPRINT.md`

If Phase 0 is incomplete, recommend the developer run `/start-feature` first.

---

## Step 1: Identify the Source Library

If `$ARGUMENTS` provides the package name, use it. Otherwise ask:

**"What Python library are you wrapping? (package name, local path, or GitHub URL)"**

Determine where the library lives:

**1a. Installed package**:
```bash
python3 -c "import <package>; print(<package>.__file__)" 2>/dev/null || echo "Package not installed"
pip show <package> 2>/dev/null | grep -E "^(Name|Version|Location|Requires):"
```

**1b. Local source**:
```bash
find <path> -name "*.py" -not -path "*/.venv/*" -not -path "*/__pycache__/*" | head -20
```

**1c. Not yet available**:
If the library is not installed and no source is available, ask the developer for:
- The library's documentation URL or README
- A description of the key functions they want to expose

Confirm the library identity and version with the developer before proceeding.

---

## Step 2: API Surface Audit

The goal is to find every function that is a candidate for becoming an MCP tool.

**2a. Public API enumeration**:
```bash
python3 -c "
import inspect, <package>
members = inspect.getmembers(<package>, predicate=inspect.isfunction)
members += inspect.getmembers(<package>, predicate=inspect.isclass)
for name, obj in sorted(members):
    if not name.startswith('_'):
        sig = inspect.signature(obj) if callable(obj) else ''
        print(f'{name}{sig}')
" 2>/dev/null
```

If the library has submodules, scan those too:
```bash
python3 -c "
import pkgutil, <package>
for importer, modname, ispkg in pkgutil.walk_packages(<package>.__path__, <package>.__name__ + '.'):
    print(f'{'pkg' if ispkg else 'mod':>3}  {modname}')
" 2>/dev/null
```

**2b. If the library is not installed**, fall back to static analysis:
```bash
grep -rn '^def \|^async def \|^class ' <source_path>/ --include="*.py" | grep -v '__\|test_\|_test\.' | head -40
```

**2c. Documentation/README scan** (if available):
```bash
find <source_path> -name "README*" -o -name "QUICKSTART*" -o -name "docs" -type d | head -5
```

Present the raw API surface to the developer. Do not filter yet -- the developer decides what to expose.

---

## Step 3: Tool Candidacy Assessment

For each function/class identified in Step 2, evaluate against these criteria:

| Criterion | Good Tool Candidate | Poor Tool Candidate |
|-----------|-------------------|-------------------|
| **I/O boundary** | Clear inputs -> clear outputs | Requires interactive session, callbacks, or streaming iterators |
| **Statefulness** | Stateless or session-scoped state | Requires persistent cross-session state |
| **Latency** | Completes in < 5 minutes | Unbounded or hours-long |
| **Parameters** | Serializable (str, int, float, bool, list, dict) | Complex objects, file handles, database connections |
| **Side effects** | Produces data or files | Modifies global state, sends emails, writes to external databases |
| **Error modes** | Raises well-defined exceptions | Segfaults, hangs, or produces silent corruption |
| **Dependencies** | Pure Python or well-packaged C extensions | Requires GUI, display server, or undocumented system libraries |

Present an assessment table:

```
| Function/Class | Candidate? | Reason | Proposed Tool Name |
|----------------|-----------|--------|-------------------|
| library.analyze() | YES | Stateless, clear I/O | <name>_analyze |
| library.train_model() | MAYBE | Long-running, needs async wrapper | <name>_train_model |
| library.plot_results() | NO | Requires display server | — |
| library.Config | NO | Internal config class | — |
```

Ask the developer to confirm the candidate list. For MAYBE items, discuss whether to include them with caveats (timeout, async job pattern) or defer to backlog.

---

## Step 4: Parameter Mapping

For each confirmed tool candidate, map library parameters to the ADEPT MCP tool pattern.

**4a. Inspect signatures**:
```bash
python3 -c "
import inspect, <package>
func = <package>.<function_name>
sig = inspect.signature(func)
for name, param in sig.parameters.items():
    annotation = param.annotation if param.annotation != inspect.Parameter.empty else 'Any'
    default = param.default if param.default != inspect.Parameter.empty else 'REQUIRED'
    print(f'{name}: {annotation} = {default}')
" 2>/dev/null
```

**4b. Map each parameter** to the ADEPT pattern:

| Library Parameter | MCP Pattern | Notes |
|------------------|-------------|-------|
| `str`, `int`, `float`, `bool` | `Annotated[<type>, Field(description="...")]` | Direct mapping |
| `pathlib.Path`, file path | `Annotated[str, Field(description="ADEPT file ID or filename")]` | Resolve via file management tools at runtime |
| `Optional[X]` | `Annotated[Optional[X], Field(description="...")] = None` | Preserve optionality |
| `List[str]` | `Annotated[list, Field(description="...")]` | JSON-serializable list |
| `dict`, `Dict[str, Any]` | `Annotated[dict, Field(description="...")]` | JSON-serializable dict |
| `numpy.ndarray` | Split into path + format params | Cannot serialize directly |
| Enum / literal set | `Annotated[str, Field(description="One of: a, b, c")]` | Document valid values in description |
| Complex object | Decompose into primitives or accept JSON | Must be JSON-serializable |

**4c. Mandatory framework parameters** (appended automatically, NOT in mapping):
- `mcp_session_id: str = ""` -- always last, injected by framework

Present the proposed parameter mapping for each tool. Ask the developer to confirm, paying attention to:
- Are descriptions accurate and helpful for an LLM agent?
- Are defaults sensible for the most common use case?
- Are any required params that should be optional (or vice versa)?

---

## Step 5: Dependency and Infrastructure Classification

Classify what the library needs to run inside a Docker container.

**5a. Python dependencies**:
```bash
pip show <package> 2>/dev/null | grep "^Requires:" || echo "No pip metadata"
```

Or from source:
```bash
find <source_path> -name "requirements*.txt" -o -name "pyproject.toml" -o -name "setup.py" | head -5
```

**5b. System dependencies**:
```bash
# Check for compiled extensions
python3 -c "import <package>; print([f for f in dir(<package>) if 'lib' in f.lower() or 'ffi' in f.lower()])" 2>/dev/null
find <source_path> -name "*.so" -o -name "*.pyd" 2>/dev/null | head -5
```

**5c. Classification table**:

| Category | Items | Docker Impact |
|----------|-------|--------------|
| **Python packages** | (list) | `requirements.txt` or `pip install` in Dockerfile |
| **System libraries** | (list, e.g., libhdf5, libopenblas) | `apt-get install` in Dockerfile |
| **GPU** | CUDA version, cuDNN | `docker-compose.gpu.yaml` overlay, NVIDIA runtime |
| **Large models/data** | (paths, sizes) | Volume mount (read-only), not baked into image |
| **External services** | (APIs, databases, credentials) | Environment variables in `.env.example` |
| **Credentials** | (API keys, tokens) | Keycloak service client or `.env.example` entries |

Present the classification and ask the developer to confirm. Flag anything that significantly increases container build time or image size (> 2 GB).

---

## Step 6: Session Boundary and State Design

Determine which tools need session isolation and which are stateless.

**Decision criteria**:

| Pattern | Session-Scoped (`mcp_session_id`) | Stateless |
|---------|----------------------------------|-----------|
| Produces output files | YES -- write to `/app/data/{name}/results/{mcp_session_id}/` | — |
| Reads user-uploaded files | YES -- resolve from uploaded_files/{mcp_session_id}/ | — |
| Caches intermediate results | YES -- session-scoped cache | — |
| Pure computation | — | YES -- no session dir needed |
| Model inference (no state) | — | YES -- model loaded at startup, shared across sessions |
| Job tracking / status | YES -- job ID scoped to session | — |

For session-scoped tools, note:
- File paths must use `mcp_session_id` to prevent cross-user data leakage
- The `get_job_status` tool pattern (see biofoundation, vfm exemplars) is standard for async jobs

Present the session boundary design and ask the developer to confirm.

---

## Step 7: Analogous Server Review (Phase 2 Gate)

The developer must review 3+ existing MCP servers before proceeding. Help them find the closest matches.

```bash
ls -d examples/*_mcp_server/ examples/*_mcp/ 2>/dev/null
```

For each candidate, check relevance:
```bash
# What tools does it expose?
ls <server>/*/tools/*.py 2>/dev/null
# What dependencies does it have?
head -20 <server>/requirements.txt 2>/dev/null
# Does it use GPU?
grep -l 'gpu\|nvidia\|cuda' <server>/docker-compose*.yaml 2>/dev/null
# Does it have a model directory?
ls -d <server>/*/model/ 2>/dev/null
```

Ask the developer:
**"Which 3+ servers did you review? What patterns will you reuse?"**

The developer should identify:
- Which server is closest in architecture (e.g., "biofoundation for GPU + model garden" or "academy for lightweight stateless tools")
- Which parameter patterns to reuse
- Which Dockerfile patterns to reuse (GPU overlay, model volume mounts, etc.)

**GATE CHECK**: The developer has named 3+ servers and described reusable patterns. If not, do not proceed.

---

## Step 8: Generate Implementation Plan

Write the plan document to `docs/implementation-plans/<NAME>_MCP_SERVER_PLAN.md` with this structure:

```markdown
# <DISPLAY_NAME> MCP Server Implementation Plan

**GitHub Issue**: #<N>
**Source Library**: <package> v<version>
**Analogous Servers**: <list of 3+ reviewed>
**Estimated Tool Count**: <N>

## Problem

<1-2 sentences: what capability gap this server fills>

## Approach

<Architecture: server type (GPU/CPU), session model, deployment pattern>

## Tools

| # | Tool Name | Source Function | Parameters | Session-Scoped | Priority |
|---|-----------|----------------|------------|---------------|----------|
| 1 | <name>_<verb> | <pkg>.<func> | <count> | Yes/No | P1/P2 |

## Parameter Mapping

### <tool_name>
| Library Param | MCP Param | Type | Default | Description |
|--------------|-----------|------|---------|-------------|

## Dependencies

| Category | Items | Docker Impact |
|----------|-------|--------------|

## Session Boundaries

<Which tools are session-scoped and why>

## Reusable Patterns

<From the 3+ reviewed servers>

## Tasks

- T1.1: /mcp-scaffold with NAME=<name>
- T1.2: /mcp-add-tool for <tool_1>
- T1.3: /mcp-add-tool for <tool_2>
- ...
- T2.1: Dockerfile + requirements.txt for <library> dependencies
- T2.2: docker-compose.gpu.yaml overlay (if GPU)
- T3.1: /mcp-test (unit + integration)
- T3.2: /mcp-register
- T4.1: Update QUICKSTART.md port registry

## Acceptance Criteria

- [ ] All <N> tools registered with ADEPT gateway
- [ ] 4-tier tests pass (unit, integration, registration, E2E)
- [ ] Port registry updated in QUICKSTART.md
- [ ] Session isolation validated (no cross-user data leakage)
```

Present the full plan content and ask the developer to confirm before writing.

**GATE CHECK**: Plan document exists in `docs/implementation-plans/`. Verify:
```bash
ls docs/implementation-plans/<NAME>_MCP_SERVER_PLAN.md
```

---

## Step 9: Create or Link GitHub Issue

Check if an issue already exists:
```bash
gh issue list --search "<name> MCP" --json number,title,state | head -5
```

If no issue exists, propose creating one:
```bash
gh issue create --title "feat(mcp): <DISPLAY_NAME> MCP server (<N> tools from <package>)" \
  --body "Implementation plan: docs/implementation-plans/<NAME>_MCP_SERVER_PLAN.md"
```

Do not execute until the developer approves.

---

## Step 10: Report

Present a summary:

```
Library: <package> v<version>
Candidate functions: <total audited>
Confirmed tools: <count>
Session-scoped: <count>
Stateless: <count>
Dependencies: <python count> Python, <system count> system, GPU: yes/no
Closest analogues: <server_1>, <server_2>, <server_3>
Plan: docs/implementation-plans/<NAME>_MCP_SERVER_PLAN.md
Issue: #<N>

Next steps:
1. Create server from template: /mcp-scaffold <name>
2. Add each tool: /mcp-add-tool <server-dir> <tool-name>  (repeat x<count>)
3. Run tests: /mcp-test <server-dir>
4. Register with ADEPT: /mcp-register <server-dir>
5. Close the task: /close-task (Phases 5-9)
```
