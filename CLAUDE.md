# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Identity

**ADEPT**: Agentic Discovery and Exploration Platform for Tools

This is the canonical expansion of the ADEPT acronym. Do not use any other expansion.

## Getting Started with Claude Code

If you are using Claude Code with this repository, these skills are available:

| Phase | Skills | Purpose |
|-------|--------|---------|
| Orient | `/start-session`, `/start-feature` | Bootstrap session, load context |
| Plan | `/start-feature`, `/start-sprint`, `/mcp-plan` | Implementation plans, GitHub issues |
| Implement | `/mcp-scaffold`, `/mcp-add-tool`, `/connect-adept`, `/start-stack`, `/deploy-cloud`, `/slurm-job-submit` | Code, scaffold, deploy, HPC |
| Test | `/validate-tests`, `/mcp-test`, `/promptfoo-check` | Required test tiers, red-team |
| Document | `/write-session-report`, `/update-tracking-docs` | Session reports, CHANGELOG |
| Commit | `/prepare-commit` | Conventional Commits with doc references |
| Audit | `/audit-hygiene`, `/pre-push-review`, `/sync-docs` | Code hygiene, semantic self-review, doc parity |
| Close | `/close-task`, `/prepare-pr`, `/review-pr`, `/mcp-register`, `/end-session` | Push, PR, review |
| Release | `/prepare-release`, `/scan-release`, `/asopb-evaluate`, `/triage-cve` | ASOPB scan, publish gate, CVE triage |

Key workflow references:
- `docs/development/FEATURE_DEVELOPMENT_WORKFLOW.md` — 10-phase canonical lifecycle
- `docs/development/CODE_HYGIENE.md` — Branch naming, commit format, testing tiers

## Architecture Overview

### Three-Tier Secure Architecture

ADEPT implements a secure three-tier architecture with strict separation of concerns:

**Tier 1: Agent Gateway** (`src/agentic_framework_pkg/agent_gateway/`)
- Pure authentication proxy (no business logic)
- Keycloak JWT validation with RBAC
- CORS handling, transparent proxying to Tier 2, A2A mesh communication

**Tier 2: Orchestration Service** (`src/agentic_framework_pkg/orchestration_service/`)
- Core "brain" implementing full OpenAI-compatible API and agent logic
- PostgreSQL-backed persistence via LangGraph checkpointing
- ScientificWorkflowAgent, dynamic tool management, multi-agent orchestration

**Tier 3: MCP Tool Servers** (Stateless executors)
- `mcp_server/` - General scientific tools (BLAST, UniProt, PubChem, websearch, RAG)
- `hpc_mcp_server/` - HPC pipelines (Nextflow, video processing)
- `sandbox_mcp_server/` - Secure code execution via llm-sandbox

**Supporting Services:**
- **Gateway Registry** (`src/agentic_framework_pkg/gateway_registry/`) - A2A service discovery
- **Identity & Security** (Keycloak) - Central IAM with JWT authentication and RBAC

### API Strategy

**Dual API Support** — use Response API for all new implementations:

- **Response API** (primary): `/v1/responses/chat/completions` — single endpoint, full SSE streaming, simpler state management
- **Assistants API** (legacy): `/v1/assistants/*`, `/v1/threads/*`, `/v1/runs/*` — supported for backward compatibility

Architecture docs: `docs/architecture/RESPONSE_API_ARCHITECTURE.md`, `docs/architecture/DUAL_API_STRATEGY.md`

### Key Design Principles

- **State ownership**: All state lives in Tier 2. MCP servers (Tier 3) are completely stateless.
- **Session isolation**: Multi-tier session IDs (`session_id`, `mcp_session_id`, `multi_agent_session_id`, `gateway_session_id`) prevent cross-user data leakage.
- **Tool architecture**: Built-in MCP tools (18 core) + external tools via dynamic discovery from gateway_registry with ACL filtering.
- **No HTTP self-calls**: Orchestration service uses direct tool_manager, never calls its own endpoints for tool discovery.

## Essential Commands

### Lifecycle Management

```bash
make start              # Start all services
make stop               # Stop services
make restart            # Restart services
make rebuild            # Full rebuild (no cache)
make teardown           # Complete teardown (containers, networks, volumes)
```

### Service-Specific Rebuilds

```bash
make rebuild-gateway           # Agent Gateway (Tier 1)
make rebuild-orchestrator      # Orchestration Service (Tier 2)
make rebuild-registry          # Gateway Registry
```

### Validation and Testing

```bash
make validate                  # All E2E tests
make validate-unit-all         # All unit tests with coverage
make validate-data             # Data-plane authentication flow
make validate-multi-agent      # Multi-agent orchestration
make validate-service-health   # Service credentials and MCP tool discovery
```

### Port Mappings

| Service | Container Port | Host Port | Access URL |
|---------|----------------|-----------|------------|
| Agent Gateway | 8081 | **8083** | `http://localhost:8083` |
| HPC MCP Server | 8081 | **8081** | `http://localhost:8081` |
| Orchestration Service | 8084 | 8084 | `http://localhost:8084` |
| Gateway Registry | 8086 | 8086 | `http://localhost:8086` |

## Docker Compose Architecture

```
docker-compose.base.yaml       # Infrastructure (Keycloak, PostgreSQL, Redis)
docker-compose.core.yaml       # Application services (3-tier + registry)
docker-compose.multi-stack.yaml # Multi-instance deployments
```

The `start-chapter-resources.sh` script orchestrates the complete lifecycle. The `Makefile` defines all test execution patterns. Tests live in `tests/e2e/`.

## Development Patterns

### Adding New MCP Tools

1. Create tool module in appropriate MCP server (`*/tools/`)
2. Decorate function with `@mcp.tool()`
3. Register in server's `main.py` tool list
4. Tools are auto-discovered by orchestration service

### Multi-Agent Orchestration

Two execution modes via `orchestration_service/multi_agent/`:
- **Router Mode**: Static plan generation followed by supervised execution
- **Graph Mode**: Dynamic LangGraph-based task routing with state machine logic

Workers support purpose-specific LLM routing via `RolePersona` with `llm_purpose` parameter (e.g., `coding_agent` for code generation, `agent_main` for general reasoning).

### YAML Model Catalog (`config/model_catalog.yaml`)

Declarative LLM purpose routing without code changes. The catalog defines 14 LLM purposes, 23 role aliases, and additive model routing:

- **Known roles** (e.g., "biologist", "coder"): Routed to declared domain-specific model
- **Arbitrary roles** (e.g., "archaeologist"): Fall back to `DEFAULT_LLM_MODEL` automatically
- **Adding a new domain model**: Add a purpose entry with `env_var` field + role aliases to YAML; no Python changes

```python
CreateMultiAgentSession(roles=[
    "chemist",  # Uses agent_main (default)
    RolePersona(name="coder", llm_purpose="coding_agent"),  # Uses Opus
])
```

### Knowledge Base and RAG

- **Hybrid backend**: ChromaDB (vector) + pgvector (relational) with automatic backend selection
- **Visibility-scoped collections**: Session (`s_`), User (`u_`), World (`w_`) access levels
- **Batch processing**: Parallel file indexing with configurable concurrency and timeouts
- **Processing types**: Auto, RAG, SQL, DataFrame, Text — routed by content analysis

### Session Isolation

- File uploads: `./data/uploaded_files/{mcp_session_id}/` per session
- Sandbox execution: Session-scoped containers via llm-sandbox
- RAG indexes: Visibility-scoped collections (`session`, `user`, `world`)
- Each MCP tool must create session-scoped resources to prevent cross-user data leakage

### A2A Federation

CLI commands for multi-gateway communication:
```bash
afk a2a register-peer <alias> <url> --registry-url http://gateway_registry:8086
afk a2a list-peers --format table
afk a2a test-connection <alias>
afk a2a remove-peer <alias> --yes
```

## Security Considerations

- **Sandbox**: `sandbox_mcp_server` requires `privileged: true` for nsjail isolation
- **JWT**: Always preserve user context in service-to-service calls
- **ACL**: Tool access controlled by user group membership in Keycloak
- **Credentials**: Generated during bootstrap (`make fix-credentials`), synced via `make sync-credentials`

## Production Deployment

### Multi-Cloud Strategy

- **Azure**: Pulumi IaC + AKS + Helm (`infra/azure/`, `infra/helm/agentic-framework-azure/`)
- **AWS**: CDK IaC + EKS + Helm (`infra/aws/`)
- **GCP**: Terraform IaC + GKE (planned)

### Container Strategy

- Internalized images built from public bases
- Pre-warmed ChromaDB with sentence transformers
- ACR/ECR registry for production artifacts

## Testing Strategy

ADEPT uses **container-based testing exclusively** — never run pytest directly on the host. All test execution uses the `agentic-framework-deps-base` Docker image which contains pre-installed dependencies.

### Testing Philosophy

- **Zero-mock**: Use real framework components with graceful fallback, not mocks
- **State isolation**: Unique thread IDs and session-scoped fixtures prevent test interference
- **Container-first**: Tests run inside Docker with network access to the service mesh
- **Makefile-driven**: All validated test patterns are encoded as `make validate-*` targets

### Container Test Execution Pattern

```bash
docker run --rm --user $(id -u):$(id -g) \
  --network=adept_application_network \
  --network=adept_frontend_network \
  -v "$(pwd)/src":/app/src:ro \
  -v "$(pwd)/tests":/app/tests:ro \
  agentic-framework-deps-base \
  /app/.venv/bin/pytest tests/e2e/<test_file>.py -v
```

### Key Patterns

- Always use `:ro` (read-only) for source/test volume mounts to prevent permission issues
- Use dual networks (`adept_application_network` + `adept_frontend_network`) for service access
- Use `--user $(id -u):$(id -g)` to preserve file ownership on host
- Work in `/tmp` for ephemeral venvs and intermediate files
- Use `--env-file .env` for integration/E2E tests requiring LLM API keys

### Three-Tier Network Architecture

| Network | Services | Purpose |
|---------|----------|---------|
| `adept_frontend_network` | nginx_proxy, OAuth2 proxy, UIs | External access |
| `adept_application_network` | agent_gateway, orchestration_service, Keycloak, MCP servers | Internal services |
| `adept_data_network` | PostgreSQL, Redis | Data persistence |

### Validation Targets

```bash
make validate                  # Full E2E suite
make validate-unit-all         # All unit tests
make validate-data             # Data-plane authentication
make validate-multi-agent      # Multi-agent orchestration
make validate-service-health   # Service credentials and tool discovery
make validate-bedrock-connectivity  # AWS Bedrock integration
```

### Linting and Formatting (Container-Based)

```bash
# Linting order: black -> isort -> ruff -> mypy
docker run --rm --user $(id -u):$(id -g) \
  -v "$(pwd)/src":/app/src:ro -w /tmp \
  agentic-framework-deps-base /bin/bash -c "
    python3 -m venv /tmp/lint_venv && \
    /tmp/lint_venv/bin/pip install -q black ruff && \
    /tmp/lint_venv/bin/black --check /app/src/ --line-length 88 --diff && \
    /tmp/lint_venv/bin/ruff check /app/src/ --target-version py311
  "
```

See `docs/testing-strategy/` for the full testing framework design.

## CI/CD Workflows

| Workflow | File | Trigger | Purpose |
|----------|------|---------|---------|
| Continuous Integration | `ci.yml` | push, PR | Orchestrator — triggers lint, test, scan |
| Lint and Test | `lint-and-test.yml` | push, PR | Black, ruff, mypy, pytest |
| Infrastructure Linting | `test-infrastructure.yml` | push, PR | Helm lint, Terraform validate, CDK synth |
| ASOPB Pre-Release Scan | `asopb-pre-release-scan.yml` | push, PR, manual | Two-phase security pipeline |
| Build and Push | `build-and-push.yml` | manual | Build Docker images, push to GHCR |
| Publish Public Release | `publish-public-release.yml` | manual | Stage, scan, publish gate |

### ASOPB Security Pipeline

The Agentic Security & Operations Performance Benchmark (ASOPB) runs a 7-pass scan:
- **Phase 1**: Lightweight regex SAST (blocking, ~30s)
- **Phase 2**: Full pipeline — Grype SCA, TruffleHog secrets, NER/PII, toxicity, promptfoo red-team (parallel, 5-60 min)
- **ASPI Score**: `D5*0.4 + D8*0.4 + D7*0.2` — gate threshold >= 90 (S4 Hardened)
- **Scanner image**: `ghcr.io/pnnl/adept-release-scanner:latest`

## Environment Configuration

Key environment categories:
- `KEYCLOAK_*` - Authentication configuration
- `POSTGRES_*` - State persistence
- `GATEWAY_*` - Service mesh and registry
- `*_MCP_SERVER_*` - Tool server endpoints
- LLM provider settings (OpenAI, Azure, AWS Bedrock)

Credentials are managed via `make fix-credentials` (generates) and `make sync-credentials` (distributes). See `.env.example` for full reference.

## Contributing

1. Fork the repository
2. Create a feature branch: `<type>-<scope>-<quarter>-<description>`
3. Follow the 10-phase lifecycle in `docs/development/FEATURE_DEVELOPMENT_WORKFLOW.md`
4. Run required test tiers based on changed files (see `/validate-tests` skill)
5. Commit with Conventional Commits format: `type(scope): description`
6. Submit PR — CI will run lint, test, and ASOPB scan automatically

For MCP server development, see `docs/development/MCP_SERVER_DEVELOPMENT_GUIDE.md` and the canonical template in `examples/mcp_server_template/`.
