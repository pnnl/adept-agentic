# ADEPT — Copilot Instructions

**ADEPT**: Agentic Discovery and Exploration Platform for Tools. This is the canonical expansion — do not use any other.

Full architecture detail, port mappings, and critical safety rules live in `CLAUDE.md`. Read it before any non-trivial work. The lifecycle workflow is in `docs/development/FEATURE_DEVELOPMENT_WORKFLOW.md`; commit/branch conventions are in `docs/development/CODE_HYGIENE.md`.

---

## Build & Service Lifecycle

All lifecycle operations go through `make`. Never run ad-hoc shell commands for operations you'd repeat.

```bash
make start          # Start all services (Docker Compose)
make stop           # Stop services
make restart        # Restart services
make rebuild        # Full rebuild (no cache)
make teardown       # Remove containers, networks, volumes

# Rebuild a single service (faster iteration)
make rebuild-gateway
make rebuild-orchestrator
make rebuild-registry
make rebuild-streamlit-app-v2
make rebuild-sandbox-mcp-server
```

---

## Testing

**All tests run inside Docker containers** via Makefile targets. Do not run pytest directly on the host.

### Run a specific validate target

```bash
make validate-<target>
# Examples:
make validate-response-api-tool-calls
make validate-unit-contract-tests
make validate-e2e-rag-workflow
make validate-presigned-url-unit
```

### Run a single test file (when no Makefile target exists yet)

```bash
mkdir -p logs && nohup docker run --rm \
  --network=adept_application_network \
  --network=adept_frontend_network \
  -v "$(pwd)/src":/app/src:ro \
  -v "$(pwd)/tests":/app/tests:ro \
  agentic-framework-deps-base \
  /app/.venv/bin/pytest tests/path/to/test_file.py -v --tb=short \
  > logs/my_test_$(date +%Y%m%d_%H%M%S).log 2>&1 &
tail -f logs/my_test_*.log
```

### Test execution rules

- Always use `nohup` with a timestamped log file in `logs/`. This log is required as commit evidence.
- Mounts are **read-only** (`:ro`). Never mount source as writable.
- Use both `--network=adept_application_network` and `--network=adept_frontend_network` (dual network required since Session 50).
- Do **not** mock framework dependencies — adapters handle graceful fallback when services are unavailable.
- Use the container's existing `/app/.venv` rather than creating ephemeral venvs when a Makefile target exists.

### Test tiers and when each is required

| Tier | Required when |
|------|---------------|
| **Unit** | Any code change to a single module |
| **Integration** | Cross-component changes |
| **E2E** | API/routing changes |
| **Contract** | New or modified class — validates attribute existence + method executability |

### Credentials sync (before running E2E/integration tests)

```bash
make sync-credentials   # Copies credentials from deployment dir to project root for test containers
make validate-credentials
```

---

## Linting & Formatting

All linting runs inside Docker using read-only mounts. Order matters: Black → isort → ruff → mypy.

```bash
# Quick check via existing script
./scripts/code-check-linter.sh

# Manual Black check (dry run)
docker run --rm --user $(id -u):$(id -g) \
  -v "$(pwd)/src":/app/src:ro -w /tmp \
  agentic-framework-deps-base /bin/bash -c "
    python3 -m venv /tmp/lint_venv &&
    /tmp/lint_venv/bin/pip install -q black &&
    /tmp/lint_venv/bin/black --check /app/src/ --line-length 88 --diff &&
    rm -rf /tmp/lint_venv"
```

Configured in `pyproject.toml`: Black line-length 88, isort `--profile black`, ruff target Python 3.11.

---

## Architecture

### Three-tier system

```
[Client] → Tier 1: Agent Gateway      (auth proxy, port 8083 on host)
                ↓ JWT-validated proxy
           Tier 2: Orchestration Service  (LangGraph agent, OpenAI-compatible API, port 8084)
                ↓ direct function calls — NO HTTP self-calls
           Tier 3: MCP Tool Servers    (stateless executors)
                   mcp_server/         — CSV RAG, UniProt, PubChem, WebSearch, BLAST, file mgmt
                   sandbox_mcp_server/ — code execution via llm-sandbox/nsjail
                   hpc_mcp_server/     — Nextflow, video transcription, GitXray
```

**Critical host port mapping:**

| Service | Host Port |
|---------|-----------|
| Agent Gateway | **8083** |
| HPC MCP Server | 8081 |
| Orchestration Service | 8084 |
| Gateway Registry | 8086 |

The Agent Gateway container port is 8081 but maps to **8083** on the host. Presigned URLs or generated URLs using `localhost:8081` route to the wrong service.

### State ownership

- **Tier 2 owns all state.** MCP servers (Tier 3) are completely stateless.
- PostgreSQL: conversation state, threads, assistants, runs (via LangGraph `AsyncPostgresSaver`).
- Redis: tool configuration, file metadata, external tool ACLs.
- Each MCP tool must create **session-scoped resources** under `mcp_session_id` (e.g., `./data/uploaded_files/{mcp_session_id}/`). Cross-session data leakage is a correctness bug.

### Multi-tier session identifiers

Every agent operation carries a hierarchy of IDs that must propagate through all tool calls:

| ID | Scope |
|----|-------|
| `thread_id` | Conversation/checkpoint isolation (LangGraph) |
| `mcp_session_id` | MCP tool execution session |
| `multi_agent_session_id` | Multi-agent coordination |
| `gateway_session_id` | A2A inter-gateway communication |

Thread IDs encode scope: main agent uses `{thread_id}`; multi-agent workers use `{mcp_session_id}::{multi_agent_session_id}::{role_name}`.

### Checkpointer: shared singleton — never instantiate in routers

```python
# ✅ Correct — use shared singleton
from ...hybrid_orchestration import hybrid_service
checkpointer = hybrid_service.checkpointer

# ❌ Wrong — creates 2 new DB connections per call
from ...persistence import AsyncPostgresSaver
checkpointer = AsyncPostgresSaver()
```

The singleton lives in `hybrid_orchestration.py:46`, created at service startup, disposed at shutdown. State isolation is achieved via unique thread IDs, not separate checkpointer instances.

### API strategy: Response API is primary

```python
# ✅ New work — Response API (single endpoint, full SSE streaming)
client.responses.chat.completions.create(
    model="agentic-framework:scientific-agent-v1",
    messages=[...],
    thread_id=thread.id,
    stream=True,
)

# ⚠️ Legacy only — Assistants API (maintained for OpenWebUI backward compat)
client.beta.assistants.create(...)
client.beta.threads.runs.create(...)
```

Use Response API (`/v1/responses/chat/completions`) for all new code. New tests must not use Assistants API endpoints; mark any found as `@pytest.mark.skip(reason="Assistants API deprecated...")`.

### Tool discovery: no HTTP self-calls from orchestration service

```python
# ✅ Correct
discovered_tools = await mcp_discovery.discover_all_tools()
external_tools = await tool_manager.get_authorized_tools(user_id, groups)

# ❌ Wrong — never call own /admin/tools/list endpoint
response = await http_client.get("http://localhost:8084/admin/tools/list")
```

### File registration: dual implementation (intentional, not duplication)

- **REST API** (`orchestration_service/routers/v1/files.py`): for external HTTP clients (OpenWebUI, curl)
- **MCP Tool** (`mcp_server/tools/file_management_tools.py`): for agent workflows

Both write to the same Redis `file_metadata:{file_id}` keys. The fields `owner_id`, `current_path`, and `session_id` must stay in parity between both paths.

---

## Key Conventions

### Branch naming

```
<category>-<workstream>-<FY-quarter>-<scope>

feature-platform-optimizations-FY26Q2-add-new-mcp-tool
fix-context-overflow-sanitize-tool-output
proposals/doe-genesis
```

Branches are created from the **current parent feature branch**, not from `main`. The project uses a cascading branch model: `main → parent feature branch → child branches`.

### Commit format (Conventional Commits + documentation chain)

```
feat(bio-tools): add timeout_seconds parameter to blast_tool

What changed: Added timeout_seconds to BlastTool Pydantic model and execution logic.
Why: Long BLAST queries were blocking the agent thread indefinitely.
Validation: 47/47 unit tests pass, 3/3 integration tests pass.
  logs/bio_tools_unit_20260601_143022.log

Related documentation (this commit):
- docs/implementation-reports/SESSION_105_BIO_TOOL_TIMEOUT_SECONDS.md

Related documentation (past 5 commits):
- docs/implementation-reports/SESSION_104_VFM_COPY_RESULT.md (833cc6dd)
```

Rules:
- **No AI agents** (Claude, Copilot, etc.) in `Author` or `Co-Authored-By` trailers.
- Every commit touching `src/` or `examples/` **must** include timestamped test log evidence.
- Every such commit **must** include both `Related documentation` sections (this commit + past 5).
- Never `git add -A`; stage specific files only.

### Adding a new MCP tool

1. Create the tool module in `<server>/tools/` with `@mcp.tool()` decorator and Pydantic input models.
2. Accept `mcp_session_id: Optional[str] = None` and scope all resources under it.
3. Register the module in the server's `main.py` tool import list.
4. Tools are auto-discovered by the orchestration service via `MCPToolDiscovery` — no further registration needed.

### Contract testing pattern

For any class with >500 lines or a critical role, add contract tests that:
1. Assert every `self.*` attribute referenced in methods **exists** after `__init__`.
2. Assert incorrect attributes do **not** exist (e.g., `self.logger` — classes use module-level `logger = get_logger(__name__)`).
3. Actually call public methods with typical inputs to catch `AttributeError` at test time rather than runtime.

### Version format

```
<major>.<minor>.YYYYMMDD    # e.g., 1.0.20260601
```

All three touchpoints must carry the same date: `pyproject.toml`, `examples/adept_asopb/pyproject.toml`, `src/agentic_framework_sdk/__init__.py`. Version bump goes on the parent branch before the PR to `main`.

### Session documentation (every session with code changes)

- Bugfix → `docs/bugfixes/SESSION_NNN_<scope>.md`
- Feature → `docs/implementation-reports/SESSION_NNN_<scope>.md`
- Plus entries in `docs/CHANGELOG.md` and `docs/ROADMAP.md`

Find the next session number: `ls docs/implementation-reports/SESSION_*.md docs/bugfixes/SESSION_*.md | sort -t_ -k2 -n | tail -1`

---

## Common Pitfalls

- **Never** use `git checkout <file>`, `git reset --hard`, or `git stash` without explicit user request — these destroy uncommitted work.
- **Never** declare a feature complete without timestamped passing test logs as evidence.
- **Always** investigate before proposing fixes: read logs (`docker logs <service> --tail 50 --since 5m`), trace errors, check configs.
- If staged changes after a fast-forward look like reversions (deleting docs, removing code), **stop and ask** — do not commit.
- Docker `restart` does **not** reload `.env` values; use `make rebuild-<service>` instead.
- The `.env` symlink at `deployment/local/docker-compose/.env → ../../../.env` must exist. Fix with `make create-env-symlink`.
- `KC_ADMIN_CLI_SECRET` is required for Keycloak bootstrap. Retrieve it with `./scripts/deps/discover_admin_cli_secret.sh` if bootstrap fails with 401.

---

## Claude Code Skills (`.claude/skills/`)

ADEPT ships 30 Claude Code skills that automate every SDLC phase. Skills are invoked by typing `/<skill-name>` in Claude Code. The authoritative definitions live in `.claude/skills/` (one directory per skill, each containing a `SKILL.md`).

### Session and Lifecycle Management

| Skill | Description |
|-------|-------------|
| `/start-session` | Bootstrap session with pre-flight checks (GitHub auth, permissions), orientation context, conversation history backup |
| `/end-session` | Close session with archival, work summary (branches, commits, PRs), optional tmux detach |
| `/start-feature` | Master conductor — walks through all 10 SDLC phases with gate checks at each transition |
| `/start-sprint` | Sprint initialization — GitHub issue parity, local tracker updates, validation requirements per task |
| `/close-task` | Full closure — test, document, commit, audit, push in sequence |

### Planning and Discovery

| Skill | Description |
|-------|-------------|
| `/mcp-plan` | Analyze a Python library API surface, map functions to MCP tools, classify dependencies, identify session boundaries |

### Implementation

| Skill | Description |
|-------|-------------|
| `/mcp-scaffold` | Create new external MCP server from canonical template (port assignment, placeholder replacement) |
| `/mcp-add-tool` | Add tool to existing MCP server following `register(mcp)` + Pydantic pattern |
| `/mcp-register` | Register MCP server tools with ADEPT gateway, including pre-flight validation and schema checking |
| `/connect-adept` | Configure Claude Code to connect to an ADEPT instance (local or remote), generate `.mcp.json`, run doctor |
| `/start-stack` | Launch ADEPT stack on any deployment target (Docker Compose, Ansible, CDK, SkyPilot, Helm, host mode) |
| `/deploy-cloud` | Guided cloud deployment (AWS/Azure/GCP) — provisioning, OS prep, stack deploy, optional A2A federation |

### Testing and Security

| Skill | Description |
|-------|-------------|
| `/validate-tests` | Determine required test tiers from changed files, verify timestamped evidence exists |
| `/mcp-test` | 4-tier MCP test strategy: unit, integration, registration, E2E |
| `/promptfoo-check` | LLM adversarial red-team evaluation against a live endpoint (OWASP LLM Top 10) |
| `/triage-cve` | CVE lookup, reachability analysis, remediation (upgrade or compensating control) |
| `/token-utilization` | Aggregate LLM token consumption, classify DAST vs regular traffic, compute costs |

### Documentation

| Skill | Description |
|-------|-------------|
| `/write-session-report` | Draft implementation report or bugfix doc following project templates |
| `/update-tracking-docs` | Sync CHANGELOG, ROADMAP, KNOWN_ISSUES with current session changes |
| `/sync-docs` | Check documentation parity across Pages, wiki, CLAUDE.md, and skill registry — detects drift and safety violations |

### Commit, Audit, and Review

| Skill | Description |
|-------|-------------|
| `/prepare-commit` | Build Conventional Commit message with Related Documentation footer chains |
| `/audit-hygiene` | Walk full Code Hygiene checklist — PASS/FAIL per item |
| `/pre-push-review` | 5 semantic audits: pattern consistency, dead code, doc-code divergence, Helm logic, unreachable paths |
| `/prepare-pr` | Create PR, monitor review, address findings, resolve conversations, verify clearance |
| `/review-pr` | Assess and address PR review findings from Copilot/CodeRabbit/humans — classify, fix, reply, resolve |

### Release and Scanning

| Skill | Description |
|-------|-------------|
| `/prepare-release` | Full pre-publish workflow: ASOPB scan, staging, dry-run, publish gate (NEVER executes publish) |
| `/scan-release` | Run 7-pass ASOPB scan on staged release tree (air-gapped container, 30-75 min) |
| `/scan-path` | Run ASOPB scan on arbitrary directory with ASPI scoring |
| `/asopb-evaluate` | Full 8-domain ASPI evaluation with credential routing and baseline comparison |

### Operations

| Skill | Description |
|-------|-------------|
| `/fix-credentials` | Diagnose and fix service credential drift (Keycloak client secrets, OAuth2 proxy 401s, token exchange errors) |
| `/slurm-hpc-manage` | Manage slurm_hpc stack — SSH keys, cluster config, workspace artifacts, health, testing |

### Custom Subagents (`.claude/agents/`)

Five custom subagents auto-delegate by task type:

| Agent | Focus |
|-------|-------|
| `adept-tooling` | Gateway operations via MCP connector |
| `security-auditor` | OWASP vulnerability analysis (read-only) |
| `hpc-specialist` | Slurm/Nextflow cluster management |
| `data-scientist` | RAG workflows, bioinformatics, plotting |
| `code-reviewer` | PR review, pattern consistency (read-only) |
