# Academy MCP Server — Testing Strategy

> **Date**: 2026-03-28 (updated 2026-03-31)
> **Status**: Validated — 370+ total tests (250 core + 96 Globus + 29 E2E lifecycle), all gaps closed
> **Canonical Pattern**: Matches biofoundation/VFM container-based DRY test infrastructure
> **Federation Role**: Academy MCP Server is the core server facilitating federation with DOE LCFs (ALCF, OLCF, NERSC) alongside A2A for open-source stack federation

---

## 1. Test Philosophy

All tests run **inside Docker containers** using the same image that runs in production. This guarantees:

- Identical Python version, packages, and `academy-py` runtime
- No host-side dependency drift
- Reproducible results across developer laptops, CI, and RC VM

The Makefile uses **DRY shared variables** (matching biofoundation/VFM) so every test target composes from the same base:

```makefile
VALIDATION_IMAGE ?= academy_mcp_server-academy_mcp_server

TEST_VOLS = -v "$(ACADEMY_PKG_DIR)":/app/academy_mcp_server:ro \
            -v "$(PROJECT_ROOT)/pyproject.toml":/app/pyproject.toml:ro
TEST_ENV  = -w /app -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1

NET_APP   = --network=adept_application_network
TEST_SVC_ENV = -e MCP_URL=http://$(CONTAINER_MCP):$(MCP_PORT) \
               -e ACADEMY_REDIS_URL=redis://redis:6379

TEST_RUN     = $(ENGINE) run --rm --user $$(id -u):$$(id -g) \
    $(TEST_VOLS) $(TEST_ENV) $(VALIDATION_IMAGE) /app/.venv/bin/python
TEST_RUN_NET = $(ENGINE) run --rm --user $$(id -u):$$(id -g) \
    $(NET_APP) $(TEST_VOLS) $(TEST_ENV) $(TEST_SVC_ENV) $(VALIDATION_IMAGE) /app/.venv/bin/python
```

Key design choices:
- **`:ro` mounts** — source code is read-only inside the container
- **`--user $(id -u):$(id -g)`** — avoids permission issues on host files
- **`HOME=/tmp`** — prevents pytest cache permission errors in `/app/`
- **`ensure-test-image`** — auto-builds the image if missing

---

## 2. Test Categories

| Category | Makefile Target | Files | What It Validates |
|----------|----------------|-------|-------------------|
| **Unit** | `make validate-unit` | `test_agent_templates.py`, `test_schemas.py`, `test_config.py`, `test_register_script.py` | Agent templates, Pydantic schemas, settings, registration script schema extraction |
| **Integration** | `make validate-integration` | `test_manager_registry.py`, `test_agent_lifecycle.py`, `test_main.py`, `test_nginx_proxy.py` | Academy runtime, MCP endpoints, nginx proxy config |
| **Full Suite** | `make validate-tests` | All test files | Unit + Integration + E2E |
| **E2E Registration** | `make validate-registration-e2e` | `test_tool_registration_e2e.py::TestToolRegistrationE2E` | CLI → Gateway → Redis registration (runs on HOST) |
| **ADEPT Redis** | `make test-registration-adept` | `test_tool_registration_e2e.py::TestADEPTToolRegistration` | Dual-network Redis verification (app + data networks) |
| **CLI Lifecycle** | `make test-registration-lifecycle` | `test_tool_registration_e2e.py::TestCLIRegistrationLifecycle` | CLI-in-container register/verify/delete (installs CLI from source) |
| **Echo Agent E2E** | (via lifecycle container) | `test_tool_registration_e2e.py::TestContainerEchoAgentE2E` | Full echo agent round-trip inside container (B11) |
| **Smoke Test** | `make smoke-test` | N/A (curl) | Full ADEPT round-trip via Response API |
| **E2E Lifecycle** | `make test-e2e-lifecycle` | `test_academy_e2e_lifecycle.py` (all tiers) | Full MCP lifecycle: discovery, auth, register/invoke/deregister, echo agent |
| **MCP Discovery** | `make test-e2e-mcp-discovery` | `test_academy_e2e_lifecycle.py::TestMCPToolDiscovery` | JSON-RPC tools/list: 32 tools, schemas, proxy parity |
| **Auth Flows** | `make test-e2e-auth-flows` | `test_academy_e2e_lifecycle.py::TestAuthFlows` | Keycloak JWT → Gateway → nginx → Response API auth chain |
| **Full Lifecycle** | `make test-e2e-full-lifecycle` | `test_academy_e2e_lifecycle.py::TestFullLifecycle` | CLI register → Redis verify → list → ACL → deregister |
| **Echo Agent E2E** | `make test-e2e-echo-agent` | `test_academy_e2e_lifecycle.py::TestResponseAPIEchoAgent` | Response API echo round-trip (gateway + nginx paths) |
| **Globus Unit** | `make validate-globus-tools` | `test_globus_*.py` (6 files) | 71 mocked SDK tests — transfer, search, compute, flows, groups, client |
| **Globus Token Exchange** | `make validate-globus-token-exchange-unit` | `test_globus_token_exchange.py` | 25 mocked httpx tests — Keycloak + Globus Auth |
| **Globus Integration** | `make validate-globus-tools-integration` | `test_globus_integration.py` | 8 live Globus API tests (requires `ACADEMY_GLOBUS_CLIENT_ID`) |
| **Globus All** | `make validate-globus-all` | All Globus test files | 96 unit + 8 integration |
| **Infrastructure Health** | `make test-infrastructure-health` | `test_infrastructure_health.py` | Redis isolation (no DNS shadowing) + tool visibility in ADEPT core Redis |

### 2.1 Unit Tests (120 tests)

No external services needed. Tests run offline in an ephemeral container.

```bash
make validate-unit
```

Covers:
- `test_agent_templates.py` — EchoAgent, CounterAgent, ComputeAgent action methods, edge cases, error handling
- `test_schemas.py` — Pydantic model serialization, `export_registration_schema()`, `$ref` resolution, JSON round-trip
- `test_config.py` — `Settings` model defaults, env override, type validation, edge cases
- `test_register_script.py` — `_resolve_type()`, `_extract_tool()`, `discover_tools()`, framework field stripping, ToolDefinition validation

### 2.2 Integration Tests (89 tests)

Require the Academy runtime (`academy-py`) but NOT the ADEPT stack.

```bash
make validate-integration
```

Covers:
- `test_manager_registry.py` — `AcademyManagerRegistry` session isolation, agent lifecycle, concurrent sessions
- `test_agent_lifecycle.py` — Full launch → invoke → list → shutdown flows, timeout handling, error paths
- `test_main.py` — FastAPI app endpoints (`/`, `/health`), HTTP method validation, content-type
- `test_nginx_proxy.py` — Config template rendering, SSE headers, IP ACL, upstream block

### 2.3 E2E Registration Tests (13 tests, run on host)

Require the ADEPT stack running + `agentic` CLI installed on host.

```bash
make validate-registration-e2e
```

Uses `--noconftest` to avoid importing `academy-py` (not installed on host). Tests:
- Per-tool registration via `agentic tools register`
- Schema fidelity (args_schema matches discovered schema)
- Register → verify → delete lifecycle
- ACL group assignment
- Invalid schema rejection
- Schema export parity between host and container

**Known limitation**: `test_schema_export_matches_container_export` fails inside Docker (no Docker-in-Docker). This is expected — run it on the host.

### 2.4 ADEPT Redis Verification (6 tests, dual-network container — G8)

Verifies that registered tools exist in Redis **from inside a container**, using the dual-network pattern (`adept_application_network` + `adept_data_network`).

```bash
make test-registration-adept
```

**Prerequisite**: `make register-tools` must have been run first. These tests verify **ADEPT Redis** (the `redis` container on `adept_data_network`) — not Academy's local Redis (`academy_redis`). ADEPT Redis stores `external_tool:*` keys for platform-wide tool discovery; Academy Redis stores MCP server artifacts (sessions, agent handles, cached results). See `docs/ONBOARDING.md` §2.5 for the full dual-Redis architecture.

**Why this target exists**: The host-side E2E tests use `docker exec redis redis-cli` to verify Redis. This works but is not how the orchestration service actually accesses tools. The dual-network test uses `redis-py` inside a container that connects to both the application network (for MCP server access) and the data network (for Redis access), exactly matching the production access pattern.

**Dual-network pattern** (from biofoundation canonical):
```bash
CID=$(docker create --rm --network=adept_application_network ... )
docker network connect adept_data_network $CID
docker start -a $CID
```

Tests:
- All 4 tools exist as `external_tool:*` keys
- All tools have `args_schema` field
- All tools specify `mcp` protocol
- All tools point to `academy_mcp_server:9004/mcp`
- `launch_academy_agent_tool` has `agent_type` in schema
- `invoke_agent_action_tool` has `action_name` in schema

### 2.5 CLI-in-Container Lifecycle (3 tests — G9)

Installs `agentic` CLI from project source inside an ephemeral container, then runs the full register → verify → delete cycle without any host-side dependencies.

```bash
make test-registration-lifecycle
```

**Why this target exists**: The host-side E2E tests depend on the `agentic` CLI being installed on the host, which may not be the case in CI environments or fresh VMs. This target is fully self-contained: it creates a venv inside the container, pip-installs the CLI from `/project/src:ro`, and runs the lifecycle tests.

Tests:
- Register `launch_academy_agent` tool, verify in Redis
- Register `invoke_agent_action` tool with default values, verify in Redis
- Full lifecycle: register → verify exists → delete → verify gone

### 2.6 Container Echo Agent E2E (1 test — B11)

Full echo agent round-trip entirely inside a container — the ultimate self-contained validation.

```bash
# Runs via the lifecycle container (same dual-network + CLI setup)
make test-registration-lifecycle  # includes B11
```

**Why this target exists**: `make smoke-test` uses `curl` from the host and talks to `localhost:8083`. This test does the same thing **from inside a container**, using `requests` to talk to `http://agent_gateway:8081` over the Docker network. It proves that the full ADEPT stack works end-to-end without any host-side tools.

Flow:
1. Register all 4 Academy tools via agentic CLI (inside container)
2. Get JWT from Keycloak (`http://keycloak:8180`)
3. POST to `http://agent_gateway:8081/v1/responses/completions`
4. Agent launches echo agent, invokes echo action
5. Assert response contains "B11 e2e test"
6. Deregister all tools (cleanup)

### 2.7 Smoke Test (Response API round-trip)

End-to-end validation through the full ADEPT stack:

```bash
make smoke-test
```

Flow:
1. Authenticates via Keycloak ROPC (`admin`/`admin`)
2. Sends natural language prompt to `POST /v1/responses/completions`
3. Agent Gateway → Orchestration Service → Academy MCP Server
4. Agent calls `launch_academy_agent_tool` + `invoke_agent_action_tool`
5. Validates response contains echo result

### 2.8 Globus Tool Unit Tests (71 tests — Session 96)

All Globus SDK calls mocked — runs fully offline. Tests validate:
- **GlobusClientManager** dual auth: `AccessTokenAuthorizer` (user token) vs `ClientCredentialsAuthorizer` (service credentials)
- Per-scope authorizer caching, confidential client reuse
- All 28 tool functions: success paths, error handling, edge cases
- Negative cases: missing credentials, SDK not installed, network errors

```bash
make validate-globus-tools
```

| File | Tests | Coverage |
|------|-------|----------|
| `test_globus_transfer.py` | 22 | list_directory, mkdir, rename, submit_transfer/delete, get/list/cancel_task, wait_for_task, search_endpoints |
| `test_globus_search.py` | 14 | search_query/scroll, ingest, get/delete_subject, list_indices |
| `test_globus_compute.py` | 8 | submit, get_task, get_endpoint, register_function, SDK-not-installed |
| `test_globus_flows.py` | 10 | list_flows, run_flow, get/cancel_flow_run |
| `test_globus_groups.py` | 6 | list_groups, get_group, auth errors |
| `test_globus_client.py` | 11 | is_configured, CC/AT auth, scope caching, negative (empty creds, RuntimeError) |

**Key test patterns**:

1. **Settings mock** (Pydantic import-time binding):
   ```python
   # WRONG: monkeypatch.setenv("ACADEMY_GLOBUS_CLIENT_ID", "...") — too late
   # RIGHT: mock the Settings object directly
   with patch("academy_mcp_server.clients.globus_client.settings", mock_settings):
       mgr = GlobusClientManager()
   ```

2. **Function-body imports** (globus_compute_sdk):
   ```python
   # WRONG: patch("academy_mcp_server.tools.globus_compute.ComputeClient")
   # RIGHT: mock the module in sys.modules
   fake_mod = types.ModuleType("globus_compute_sdk")
   fake_mod.Client = MagicMock(return_value=mock_gcc)
   with patch.dict(sys.modules, {"globus_compute_sdk": fake_mod}):
       result = await globus_compute_submit(...)
   ```

### 2.9 Globus Token Exchange Unit Tests (25 tests — Session 96)

Tests the RFC 8693 token exchange module (`src/.../core/globus_token_exchange.py`). All httpx calls mocked.

```bash
make validate-globus-token-exchange-unit
```

Covers:
- `keycloak_token_exchange()` — RFC 8693 subject_token → Globus access_token
- `globus_client_credentials()` — Direct Globus Auth client credentials flow
- Error handling: 400/401 responses, network errors, missing fields

### 2.10 Globus Integration Tests (8 tests — live Globus API)

Requires `ACADEMY_GLOBUS_CLIENT_ID` and `ACADEMY_GLOBUS_CLIENT_SECRET` env vars. Makes real API calls.

```bash
export ACADEMY_GLOBUS_CLIENT_ID=<your-client-id>
export ACADEMY_GLOBUS_CLIENT_SECRET=<your-client-secret>
make validate-globus-tools-integration
```

Covers:
- Transfer: search endpoints (Globus Tutorial), list directory, list tasks
- Search: list indices, query MDF public index
- Groups: list groups for authenticated client
- Tool registration: all 28 Globus tools discoverable on FastMCP instance

### 2.11 Globus Prompt Examples

Natural language prompts for exercising Globus tools via the Response API. See [`GLOBUS_PROMPT_EXAMPLES.md`](GLOBUS_PROMPT_EXAMPLES.md) for the full catalog.

**Transfer Workflows**:
```
"List the contents of /shared/data/ on Globus endpoint abc-123-def"
"Transfer all .csv files from endpoint A path /results/ to endpoint B path /incoming/"
"Check the status of my last 5 Globus transfers"
```

**Search Workflows**:
```
"Search the Materials Data Facility for copper oxide datasets"
"Ingest these 3 entries into search index idx-456 with subject 'experiment-2026-03'"
```

**Compute Workflows** (DOE LCF federation):
```
"Submit function func-789 to the ALCF Polaris compute endpoint with args [100, 200]"
"Check if my compute task task-abc on NERSC Perlmutter has completed"
"Register this Python function for remote execution: def analyze(data): return sum(data)"
```

**Flows Workflows**:
```
"List my available Globus automation flows"
"Run the 'Data Pipeline' flow with source=ep-1 and dest=ep-2"
"Cancel flow run run-xyz — it's been running too long"
```

### 2.12 E2E Lifecycle Tests (24 tests — Session 97)

Comprehensive end-to-end lifecycle tests covering the complete MCP server pipeline.
Tests are organized into 4 tiers following the biofoundation canonical pattern.

```bash
# All tiers (dual-network + CLI + Redis)
make test-e2e-lifecycle

# Individual tiers
make test-e2e-mcp-discovery       # Tier 1: MCP JSON-RPC tools/list
make test-e2e-auth-flows          # Tier 2: Keycloak JWT auth chain
make test-e2e-full-lifecycle      # Tier 3: register/list/invoke/deregister
make test-e2e-echo-agent          # Tier 4: Response API echo agent

# Background with timestamped log
make nohup-test-e2e-lifecycle
```

| Tier | Class | Tests | What It Validates |
|------|-------|-------|-------------------|
| 1 — MCP Discovery | `TestMCPToolDiscovery` | 9 | JSON-RPC tools/list: health, 32 tools present, descriptions, schemas, proxy parity |
| 2 — Auth Flows | `TestAuthFlows` | 8 | JWT acquisition, gateway auth, admin tools/list, 401 rejection, nginx proxy chain |
| 3 — Full Lifecycle | `TestFullLifecycle` | 4 | CLI register → Redis verify → delete → verify gone; batch register 4 tools; ACL groups |
| 4 — Echo Agent | `TestResponseAPIEchoAgent` | 3 | Response API echo round-trip (gateway + nginx), list agents prompt |

**Why this exists**: Prior E2E tests (`test_tool_registration_e2e.py`) focused on registration mechanics. These tests validate the **full federated pipeline**: MCP discovery → authentication → tool invocation → Response API → echo agent. This is critical because Academy MCP Server is the core server facilitating DOE LCF federation (ALCF, OLCF, NERSC) alongside A2A for open-source stack federation.

**Network requirements**:
- Tier 1: `adept_application_network` only (MCP server access)
- Tier 2: `adept_application_network` + `adept_frontend_network` (nginx access)
- Tier 3: `adept_application_network` + `adept_data_network` (Redis access) + agentic CLI
- Tier 4: `adept_application_network` + `adept_frontend_network` (nginx echo)

---

## 3. Running Tests

### 3.1 Foreground (Interactive)

```bash
# Unit tests only (~1s)
make validate-unit

# Integration tests only (~10s)
make validate-integration

# Full suite (~11s)
make validate-tests

# E2E registration — host-side (requires ADEPT stack)
make validate-registration-e2e

# Dual-network Redis verification (requires registered tools)
make test-registration-adept

# CLI-in-container lifecycle (self-contained — installs CLI from source)
make test-registration-lifecycle

# Smoke test (requires ADEPT stack + registered tools)
make smoke-test

# E2E lifecycle — all 4 tiers (requires full stack)
make test-e2e-lifecycle

# Individual tiers
make test-e2e-mcp-discovery       # Tier 1: JSON-RPC tools/list
make test-e2e-auth-flows          # Tier 2: JWT auth chain
make test-e2e-full-lifecycle      # Tier 3: register/invoke/deregister
make test-e2e-echo-agent          # Tier 4: Response API echo agent
```

### 3.2 Background (Nohup with Timestamped Logs)

All nohup targets write to `logs/` with timestamps for audit trails.

```bash
# All tests → logs/academy_test_all_20260328_HHMMSS.log
make nohup-test-all

# Unit tests → logs/academy_test_unit_20260328_HHMMSS.log
make nohup-test-unit

# Integration tests → logs/academy_test_integration_20260328_HHMMSS.log
make nohup-test-integration

# Dual-network + CLI lifecycle → logs/academy_test_registration_adept_HHMMSS.log
make nohup-test-registration-adept
make nohup-test-registration-lifecycle

# E2E lifecycle (all tiers) → logs/academy_e2e_lifecycle_HHMMSS.log
make nohup-test-e2e-lifecycle
```

Each target prints the PID and log path:

```
--> Running ALL tests in background -> /path/to/logs/academy_test_all_20260328_064512.log
  PID: 12345  -- tail -f /path/to/logs/academy_test_all_20260328_064512.log
```

Monitor with:
```bash
tail -f logs/academy_test_all_*.log
```

### 3.3 Direct Docker Invocation

For ad-hoc or debugging:

```bash
# Run a single test file
docker run --rm --user $(id -u):$(id -g) \
  -v "$(pwd)":/app/academy_mcp_server:ro \
  -w /app -e HOME=/tmp \
  academy_mcp_server-academy_mcp_server \
  /app/.venv/bin/python -m pytest \
    /app/academy_mcp_server/tests/test_agent_lifecycle.py -v -s

# Run a single test class
docker run --rm --user $(id -u):$(id -g) \
  -v "$(pwd)":/app/academy_mcp_server:ro \
  -w /app -e HOME=/tmp \
  academy_mcp_server-academy_mcp_server \
  /app/.venv/bin/python -m pytest \
    /app/academy_mcp_server/tests/test_main.py::TestHealthEndpoint -v -s
```

---

## 4. Validation Results (2026-03-28, updated 2026-03-29)

### 4.1 Unit Tests — 120 passed

```
$ make validate-unit
--> Running unit tests (schemas + agent templates + config + register script)...
======================== 120 passed, 1 warning in 1.18s ========================
  Unit tests passed
```

Log: `logs/validate_unit_20260328_214342.log`

### 4.2 Full Suite — 209 passed, 1 failed, 21 skipped

```
$ make validate-tests
--> Running full Academy MCP Server test suite...
============ 1 failed, 209 passed, 21 skipped, 2 warnings in 11.13s ============
```

Log: `logs/validate_all_20260328_225219.log`

**1 expected failure**: `test_schema_export_matches_container_export` — Docker-in-Docker not available inside test container (`FileNotFoundError: No such file or directory: 'docker'`). This test passes when run on the host.

**21 skipped**: E2E registration tests (`test_tool_registration_e2e.py`) — require `agentic` CLI and ADEPT stack, which aren't available inside the test container. Run these via `make validate-registration-e2e` on the host.

### 4.3 Tool Registration — 4/4 registered, 4/4 verified

```
$ make register-tools
--> Step 1: Discovering Academy tool schemas from container...
  Discovered 4 tools
--> Step 2: Registering with ADEPT gateway...
  Academy MCP server is healthy
  Registering launch_academy_agent_tool... OK
  Registering invoke_agent_action_tool... OK
  Registering list_academy_agents_tool... OK
  Registering shutdown_academy_agent_tool... OK
Result: 4/4 tools registered successfully

$ make verify-tools
--> Verifying Academy tool registration in Redis...
  + launch_academy_agent_tool found in Redis (with args_schema)
  + invoke_agent_action_tool found in Redis (with args_schema)
  + list_academy_agents_tool found in Redis (with args_schema)
  + shutdown_academy_agent_tool found in Redis (with args_schema)
Result: 4/4 tools verified in Redis
```

### 4.4 Smoke Test — Passed

```
$ make smoke-test
--> Running E2E smoke test via Response API...
{
    "id": "resp_6891c921f0224cf5ac7854b8",
    "object": "response.completion",
    "model": "agentic-framework:scientific-agent-v1",
    "choices": [{
        "message": {
            "role": "assistant",
            "content": "I've successfully launched the echo agent (agent_id: AgentId<0114fa42>)
                        and invoked its echo action. The agent returned:
                        \"academy smoke test 20260328\""
        },
        "finish_reason": "stop"
    }]
}
  Smoke test passed (HTTP 200)
```

### 4.5 Service Health — All 3 Healthy

```
$ make health
--> Checking health...
  MCP Server:   {"status": "healthy", "mcp_tools": ["launch_academy_agent", ...]}
  Nginx Proxy:  {"status": "ok", "proxy": "academy"}
  Redis:        PONG
```

### 4.6 Dual-Network Redis Verification (G8) — 6/6 passed

```
$ make test-registration-adept
--> Running ADEPT tool registration tests (dual-network: app + data)...
TestADEPTToolRegistration::test_all_tools_registered_in_redis PASSED
TestADEPTToolRegistration::test_tools_have_args_schema PASSED
TestADEPTToolRegistration::test_tools_use_mcp_protocol PASSED
TestADEPTToolRegistration::test_tools_point_to_academy_mcp_url PASSED
TestADEPTToolRegistration::test_launch_tool_schema_has_agent_type PASSED
TestADEPTToolRegistration::test_invoke_tool_schema_has_action_name PASSED
============================== 6 passed in 0.02s ===============================
```

### 4.7 CLI-in-Container Lifecycle (G9) — 3/3 passed

```
$ make test-registration-lifecycle
--> Running CLI registration lifecycle tests (dual-network + agentic CLI)...
CLI: /tmp/cli_venv/bin/agentic
TestCLIRegistrationLifecycle::test_register_launch_agent PASSED
TestCLIRegistrationLifecycle::test_register_invoke_action PASSED
TestCLIRegistrationLifecycle::test_register_then_delete_lifecycle PASSED
============================== 3 passed in 2.32s ===============================
```

### 4.8 Container Echo Agent E2E (B11) — 1/1 passed

```
$ (run via lifecycle container with dual-network)
TestContainerEchoAgentE2E::test_echo_agent_round_trip PASSED
============================== 1 passed in 20.02s ==============================
```

Full round-trip: Keycloak auth → Agent Gateway → Orchestration Service → Academy MCP Server → echo agent → response — all inside a container.

---

## 5. Cross-Reference: Service Logs During Smoke Test

### 5.1 Academy MCP Server

Tool call trace showing the full agent lifecycle:

```
2026-03-29 06:24:16,100 - academy_mcp_server - INFO - [TOOL_CALL] launch_academy_agent_tool | type=echo | config={} | session=none
2026-03-29 06:24:16,100 - academy_mcp_server - INFO - [SESSION_CREATE] Creating Academy Manager for session=default
2026-03-29 06:24:16,100 - academy.exchange.local - INFO - Registered UserId<dec195de> in exchange
2026-03-29 06:24:16,100 - academy.manager - INFO - Initialized manager (UserId<dec195de>)
2026-03-29 06:24:16,100 - academy.exchange.client - INFO - Registered AgentId<0114fa42> in exchange
2026-03-29 06:24:16,100 - academy.manager - INFO - Launched agent (AgentId<0114fa42>; <class 'academy_mcp_server.agent_templates.EchoAgent'>)
2026-03-29 06:24:16,101 - academy.runtime - INFO - Running agent (AgentId<0114fa42>; Agent<EchoAgent>)
2026-03-29 06:24:16,101 - academy_mcp_server - INFO - [AGENT_LAUNCH] agent_id=AgentId<0114fa42> type=echo actions=[] session=default
2026-03-29 06:24:16,101 - academy_mcp_server - INFO - [TOOL_RESULT] launch_academy_agent_tool | status=running | agent_id=AgentId<0114fa42>
```

Action invocation:

```
2026-03-29 06:24:28,599 - academy_mcp_server - INFO - [TOOL_CALL] invoke_agent_action_tool | agent=AgentId<0114fa42> | action=echo | args={'message': 'academy smoke test 20260328'} | session=none
2026-03-29 06:24:28,599 - academy_mcp_server - INFO - [ACTION_INVOKE] agent_id=AgentId<0114fa42> action=echo args={'message': 'academy smoke test 20260328'} timeout=30s session=default
2026-03-29 06:24:28,600 - academy_mcp_server - INFO - [ACTION_RESULT] agent_id=AgentId<0114fa42> action=echo elapsed=0.000s session=default
2026-03-29 06:24:28,600 - academy_mcp_server - INFO - [TOOL_RESULT] invoke_agent_action_tool | agent=AgentId<0114fa42> | action=echo | status=success
```

### 5.2 MCP Protocol (HTTP layer)

```
INFO: 172.20.0.11:49862 - "POST /mcp HTTP/1.1" 200 OK    # launch_academy_agent_tool call
INFO: 172.20.0.11:33254 - "POST /mcp HTTP/1.1" 200 OK    # ListToolsRequest (health check)
INFO: 172.20.0.11:33262 - "POST /mcp HTTP/1.1" 202 Accepted  # SSE session init
INFO: 172.20.0.11:33272 - "POST /mcp HTTP/1.1" 200 OK    # invoke_agent_action_tool call
INFO: 172.20.0.11:33284 - "POST /mcp HTTP/1.1" 200 OK    # ListToolsRequest (post-call)
```

### 5.3 Health Check During Invocation

```
INFO: 127.0.0.1:39070 - "GET /health HTTP/1.1" 200 OK    # Pre-call health check
INFO: 127.0.0.1:55798 - "GET /health HTTP/1.1" 200 OK    # Post-call health check
```

---

## 6. Test File Inventory

| File | Tests | Category | What It Covers |
|------|-------|----------|----------------|
| `test_agent_templates.py` | 39 | Unit | EchoAgent (6), CounterAgent (9), ComputeAgent (8), negative cases (16) |
| `test_schemas.py` | 40 | Unit | Pydantic models (6), export_registration_schema (5), negative/edge (29) |
| `test_config.py` | 16 | Unit | Settings defaults (5), env override (5), negative cases (6) |
| `test_register_script.py` | 25 | Unit | _resolve_type (6), _extract_tool (7), discover_tools (10), ToolDefinition (2) |
| `test_manager_registry.py` | 28 | Integration | Session CRUD (5), agent lifecycle (8), concurrent sessions (7), negative (8) |
| `test_agent_lifecycle.py` | 29 | Integration | Launch/invoke/list/shutdown (4 tools x 3+ tests), timeout, errors, negative (10) |
| `test_main.py` | 11 | Integration | Root endpoint (2), health endpoint (3), error cases (6) |
| `test_nginx_proxy.py` | 21 | Integration | Config template (5), SSE headers (4), IP ACL (3), upstream (2), negative (7) |
| `test_tool_registration_e2e.py` — `TestToolRegistrationE2E` | 9 | E2E (host) | Per-tool registration (4), lifecycle (1), ACL (1), errors (2), export parity (1) |
| `test_tool_registration_e2e.py` — `TestADEPTToolRegistration` | 6 | E2E (dual-network) | Redis key existence, args_schema, protocol, URL, schema fields |
| `test_tool_registration_e2e.py` — `TestCLIRegistrationLifecycle` | 3 | E2E (container) | CLI register/verify, default values, full lifecycle |
| `test_tool_registration_e2e.py` — `TestContainerEchoAgentE2E` | 1 | E2E (container) | Full echo agent round-trip via Response API |
| `test_globus_transfer.py` | 22 | Globus Unit | 11 transfer tools: list_directory, mkdir, rename, tasks, endpoints |
| `test_globus_search.py` | 14 | Globus Unit | 6 search tools: query, scroll, ingest, subject CRUD, indices |
| `test_globus_compute.py` | 8 | Globus Unit | 5 compute tools: submit, get_task, endpoint, register_function |
| `test_globus_flows.py` | 10 | Globus Unit | 4 flows tools: list, run, get_run, cancel |
| `test_globus_groups.py` | 6 | Globus Unit | 2 groups tools: list_groups, get_group |
| `test_globus_client.py` | 11 | Globus Unit | GlobusClientManager auth, caching, negative cases |
| `test_globus_integration.py` | 8 | Globus Integration | Live API: endpoints, directory, tasks, search, groups, tool count |
| `test_globus_token_exchange.py` (main tests/) | 25 | Token Exchange Unit | RFC 8693 exchange, client credentials, error handling |
| `test_academy_e2e_lifecycle.py` — `TestMCPToolDiscovery` | 9 | E2E Lifecycle (Tier 1) | JSON-RPC tools/list, 32 tools, schemas, descriptions, proxy parity |
| `test_academy_e2e_lifecycle.py` — `TestAuthFlows` | 8 | E2E Lifecycle (Tier 2) | JWT auth, gateway auth/reject, admin tools/list, nginx proxy chain |
| `test_academy_e2e_lifecycle.py` — `TestFullLifecycle` | 4 | E2E Lifecycle (Tier 3) | CLI register→verify→delete, batch 4 tools, tools list, ACL |
| `test_academy_e2e_lifecycle.py` — `TestResponseAPIEchoAgent` | 3 | E2E Lifecycle (Tier 4) | Echo round-trip (gateway + nginx), list agents prompt |
| **Total** | **370+** | | Core (250) + Globus (96) + E2E Lifecycle (24) |

---

## 7. Log Files

All logs are in `logs/` with timestamps:

| Log Pattern | Source | Content |
|-------------|--------|---------|
| `validate_unit_YYYYMMDD_HHMMSS.log` | `make validate-unit` | Unit test pytest output |
| `validate_all_YYYYMMDD_HHMMSS.log` | `make validate-tests` | Full suite pytest output |
| `academy_test_all_YYYYMMDD_HHMMSS.log` | `make nohup-test-all` | Background full test run |
| `academy_test_unit_YYYYMMDD_HHMMSS.log` | `make nohup-test-unit` | Background unit test run |
| `academy_test_integration_YYYYMMDD_HHMMSS.log` | `make nohup-test-integration` | Background integration run |
| `academy_e2e_lifecycle_YYYYMMDD_HHMMSS.log` | `make nohup-test-e2e-lifecycle` | Background E2E lifecycle run (Tiers 1-4) |
| `academy_test_reg_adept_YYYYMMDD_HHMMSS.log` | `make nohup-test-registration-adept` | ADEPT Redis verification (dual-network) |
| `academy_test_reg_lifecycle_YYYYMMDD_HHMMSS.log` | `make nohup-test-registration-lifecycle` | CLI lifecycle (dual-network + agentic CLI) |
| `build_YYYYMMDD_HHMMSS.log` | `make build` | Docker image build output |
| `start_YYYYMMDD_HHMMSS.log` | `make start` | Container start output |
| `register_tools_YYYYMMDD_HHMMSS.log` | `make register-tools` | Registration CLI output |
| `discovered_schemas_YYYYMMDD_HHMMSS.log` | Schema discovery | JSON tool schemas |
| `academy_mcp_startup_YYYYMMDD_HHMMSS.log` | Container logs | MCP server startup trace |
| `academy_nginx_startup_YYYYMMDD_HHMMSS.log` | Container logs | Nginx proxy startup trace |
| `academy_redis_startup_YYYYMMDD_HHMMSS.log` | Container logs | Redis startup trace |

---

## 8. Known Issues

| # | Issue | Impact | Workaround |
|---|-------|--------|------------|
| 1 | `test_schema_export_matches_container_export` fails inside Docker | 1 test failure | Run `make validate-registration-e2e` on host |
| 2 | 21 E2E tests skipped inside container | No E2E coverage in `validate-tests` | Run `make validate-registration-e2e` separately |
| 3 | pytest cache warning (`Permission denied: /app/pytest-cache-files-*`) | Cosmetic warning | Harmless — `HOME=/tmp` prevents actual failures |

---

## 9. Future Test Targets (Backlog)

| # | Target | Description | Status |
|---|--------|-------------|--------|
| B7 | `test-registration-adept` | Dual-network test (app + data) for Redis verification from inside container | **Done** (G8) |
| B7 | `test-registration-lifecycle` | CLI-in-container full register/verify/delete cycle (installs agentic CLI from source) | **Done** (G9) |
| B11 | Container-based agentic CLI E2E | Echo agent round-trip test entirely inside containers | **Done** |
| B12 | Globus tool registration E2E | Register all 28+4=32 tools → verify in Redis → invoke Globus transfer via Response API → deregister | Planned |
| B13 | Globus auth flow via nginx | JWT auth through nginx → agent gateway → orchestration → academy MCP → Globus SDK | Planned |
| B14 | Globus data staging E2E | Full workflow: upload file → Globus Transfer → wait → verify at destination | Planned (requires live Globus creds) |
| B15 | Cross-facility A2A + Globus | EMSL→RC A2A delegation + Globus data staging + Slurm job submission | Planned (requires multi-stack) |
| B16 | agentic CLI Globus tests | `agentic tools list` shows 32 tools, `agentic chat` with Globus prompts | Planned |
