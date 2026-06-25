# Academy MCP Server: Existing Test Infrastructure Analysis

**Date**: 2026-03-31
**Source**: Automated codebase exploration of `examples/academy_mcp_server/`
**Purpose**: Comprehensive inventory of what exists before designing new E2E lifecycle tests

---

## 1. Directory Structure

```
examples/academy_mcp_server/
├── tests/
│   ├── conftest.py                      # Shared fixtures (registry, session_id, wait_for_agent)
│   ├── test_agent_lifecycle.py          # Agent lifecycle: launch, invoke, list, shutdown (async)
│   ├── test_agent_templates.py          # EchoAgent, CounterAgent, ComputeAgent implementations
│   ├── test_config.py                   # Settings validation (port, redis_url, log_level)
│   ├── test_main.py                     # FastAPI endpoints (/health, /)
│   ├── test_manager_registry.py         # AcademyManagerRegistry: sessions, agents, concurrency
│   ├── test_nginx_proxy.py              # nginx reverse proxy: health, mcp route, streaming headers
│   ├── test_register_script.py          # Schema discovery: _resolve_type, _extract_tool, discover_tools
│   ├── test_tool_registration_e2e.py    # E2E: agentic CLI -> Gateway -> Redis (4 tiers)
│   ├── test_schemas.py                  # Pydantic validation + export_registration_schema()
│   ├── test_globus_transfer.py          # Globus transfer tools (mocked SDK, 22 tests)
│   ├── test_globus_search.py            # Globus search tools (mocked SDK, 14 tests)
│   ├── test_globus_compute.py           # Globus compute tools (mocked SDK, 8 tests)
│   ├── test_globus_flows.py             # Globus flows tools (mocked SDK, 10 tests)
│   ├── test_globus_groups.py            # Globus groups tools (mocked SDK, 6 tests)
│   ├── test_globus_client.py            # GlobusClientManager auth + caching (11 tests)
│   └── test_globus_integration.py       # Live Globus API tests (requires credentials)
├── main.py                              # FastAPI app + MCP mount + /health + /
├── server.py                            # FastMCP server registration (6 tool modules)
├── config.py                            # Pydantic Settings (port, redis_url, log_level, globus_*)
├── schemas.py                           # Pydantic models + export_registration_schema()
├── manager_registry.py                  # Session/agent lifecycle management
├── agent_templates.py                   # EchoAgent, CounterAgent, ComputeAgent
├── scripts/
│   ├── register_academy_tools.py        # Tool discovery + schema extraction + registration
│   └── register_from_schemas.py         # Host-side CLI wrapper (registration/deregistration/verify)
├── clients/
│   ├── __init__.py
│   └── globus_client.py                 # GlobusClientManager (dual auth, per-scope caching)
├── tools/
│   ├── agent_lifecycle.py               # 4 agent lifecycle tools
│   ├── globus_transfer.py               # 11 transfer tools
│   ├── globus_search.py                 # 6 search tools
│   ├── globus_compute.py                # 5 compute tools
│   ├── globus_flows.py                  # 4 flows tools
│   └── globus_groups.py                 # 2 groups tools
├── Makefile                             # 60+ targets (canonical pattern)
├── docker-compose.yaml                  # 3-service stack: Redis + MCP + nginx
├── docker-compose.cpu.yaml              # CPU-only override
└── Dockerfile                           # Container image build
```

---

## 2. Test Files Inventory (18 files)

| File | Type | Tests | Purpose | Coverage |
|------|------|-------|---------|----------|
| **conftest.py** | Fixtures | -- | Shared registry, session IDs, wait_for_agent | -- |
| **test_agent_lifecycle.py** | Unit/Async | 35+ | Launch/invoke/list/shutdown agents + error handling | Core workflow |
| **test_agent_templates.py** | Unit | 20+ | EchoAgent, CounterAgent, ComputeAgent behavior | Agent logic |
| **test_config.py** | Unit | 14 | Settings validation, env overrides, edge cases | Configuration |
| **test_main.py** | Unit | 10 | FastAPI endpoints (/health, /), content-type validation | API surface |
| **test_manager_registry.py** | Integration | 30+ | Session lifecycle, agent mgmt, concurrency, cleanup | Registry state |
| **test_nginx_proxy.py** | Integration | 16 | Health endpoint, MCP proxying, SSE headers, config validation | Reverse proxy |
| **test_register_script.py** | Unit | 40+ | _resolve_type, _extract_tool, discover_tools, ToolDefinition | Schema extraction |
| **test_tool_registration_e2e.py** | E2E | 30+ | CLI -> Gateway -> Redis (4 tiers), ACL, lifecycle | Full registration |
| **test_schemas.py** | Unit | 50+ | Pydantic validation, defaults, bounds, export_registration_schema | Schema modeling |
| **test_globus_transfer.py** | Unit | 22 | Transfer operations (mocked SDK) | Globus Transfer |
| **test_globus_search.py** | Unit | 14 | Search operations (mocked SDK) | Globus Search |
| **test_globus_compute.py** | Unit | 8 | Compute submission (mocked SDK) | Globus Compute |
| **test_globus_flows.py** | Unit | 10 | Flow management (mocked SDK) | Globus Flows |
| **test_globus_groups.py** | Unit | 6 | Groups operations (mocked SDK) | Globus Groups |
| **test_globus_client.py** | Unit | 11 | Globus client initialization and caching | Globus SDK |
| **test_globus_integration.py** | Integration | 8 | Live Globus API (requires env credentials) | Live API |
| **TOTAL** | -- | **~350** | -- | -- |

---

## 3. Key Infrastructure Components

### 3.1 Test Fixtures (conftest.py)

```python
@pytest.fixture
def registry():
    """Return a fresh AcademyManagerRegistry (not the module singleton)."""
    return AcademyManagerRegistry()

@pytest.fixture
def session_id():
    """Return a unique session ID for test isolation."""
    return f"test-session-{uuid.uuid4().hex[:12]}"

@pytest.fixture
def session_id_alt():
    """Return a second unique session ID for cross-session tests."""
    return f"test-session-alt-{uuid.uuid4().hex[:12]}"

async def wait_for_agent():
    """Wait briefly for Academy exchange background tasks to settle."""
    await asyncio.sleep(0.15)
```

### 3.2 Configuration (config.py)

```python
class Settings(BaseSettings):
    port: int = 9004
    redis_url: str = "redis://academy_redis:6379/0"
    log_level: str = "INFO"
    globus_client_id: str = ""
    globus_client_secret: str = ""
    globus_default_transfer_endpoint: str = ""
    globus_default_compute_endpoint: str = ""
    globus_default_search_index: str = ""
    model_config = {"env_prefix": "ACADEMY_", "env_file": ".env", "extra": "ignore"}
```

### 3.3 Schema Export (schemas.py)

```python
# Pydantic model -> ADEPT args_schema JSON
export_registration_schema(InvokeActionInput)
# Output:
{
  "agent_id": {"type": "string", "description": "..."},
  "action_name": {"type": "string", "description": "..."},
  "action_args": {"type": "object", "description": "...", "default": {}},
  "timeout": {"type": "integer", "description": "...", "default": 30, "ge": 1, "le": 300}
}
```

- Flattens Pydantic $ref and allOf references
- Preserves type, description, default, enum
- Strips Optional -> nullable: true
- Handles default_factory (dict, list)

### 3.4 Server (server.py)

```python
mcp = FastMCP("Academy MCP Server")

def register_tools():
    from .tools.agent_lifecycle import register as register_lifecycle
    from .tools.globus_transfer import register as register_transfer
    from .tools.globus_search import register as register_search
    from .tools.globus_compute import register as register_compute
    from .tools.globus_flows import register as register_flows
    from .tools.globus_groups import register as register_groups

    register_lifecycle(mcp)
    register_transfer(mcp)
    register_search(mcp)
    register_compute(mcp)
    register_flows(mcp)
    register_groups(mcp)

register_tools()  # 32 tools total (4 agent + 28 Globus)
```

---

## 4. E2E Registration Tiers (test_tool_registration_e2e.py)

### Tier 1: CLI Host Tests (TestToolRegistrationE2E, 9 tests)

- Register launch/invoke/list/shutdown via agentic CLI
- Verify schemas survive CLI -> Gateway -> Redis round-trip
- Test ACL groups, schema validation, lifecycle
- Run: `make validate-registration-e2e`

### Tier 2: ADEPT Redis Verification (TestADEPTToolRegistration, 6 tests)

- Verify tools exist in ADEPT's Redis from inside a container
- Dual-network: `adept_application_network` + `adept_data_network`
- Check protocol, URL, args_schema presence
- Run: `make test-registration-adept`

### Tier 3: CLI-in-Container Lifecycle (TestCLIRegistrationLifecycle, 3 tests)

- Install agentic CLI -> full register/verify/delete cycle
- Dual-network + ephemeral venv inside container
- Run: `make test-registration-lifecycle`

### Tier 4: Echo Agent E2E (TestContainerEchoAgentE2E, 1 test)

- Full round-trip via Response API
- Register tools -> Keycloak auth -> Gateway -> MCP -> echo response
- Run: `make test-registration-lifecycle` (same target)

---

## 5. Docker Compose Architecture (3-Service Stack)

```yaml
academy_redis:
  - Redis 7-alpine
  - Port: 6384 (host) -> 6379 (container)
  - Network: adept_application_network
  - Health: redis-cli ping

academy_mcp_server:
  - Built from Dockerfile (FastAPI + FastMCP)
  - Port: 9004
  - Environment: ACADEMY_* settings
  - Network: adept_application_network
  - Health: curl /health
  - Depends-on: academy_redis (healthy)

academy_nginx_proxy:
  - nginx:alpine
  - Ports: 9020 (HTTP), 9021 (HTTPS)
  - Volumes: academy_proxy.conf.template, certs/
  - Environment: MCP_SERVER_HOST, MCP_SERVER_PORT
  - Network: adept_application_network
  - Health: wget /health
  - Depends-on: academy_mcp_server (healthy)
```

---

## 6. Registration Flow (2-Step Pattern)

```
Step 1: Container Discovery
  -> docker exec academy_mcp_server python -c \
     "from scripts.register_academy_tools import discover_tools, show_schemas; \
      show_schemas(discover_tools())"
  -> Outputs 4 tool JSON schemas to /tmp/academy_schemas.json
  (Only in container because academy-py not installed on host)

Step 2: Host CLI Registration
  -> KEYCLOAK_URL=$(KEYCLOAK_URL) AGENT_GATEWAY_URL=$(GATEWAY_URL) ...
  -> python scripts/register_from_schemas.py /tmp/academy_schemas.json
  -> Runs agentic CLI: "tools register <name> --tool-name <name> --args-schema <json> ..."
  -> CLI -> Keycloak ROPC -> Gateway JWT auth -> tool stored in Redis
```

---

## 7. Makefile Test Targets (60+)

### Lifecycle Targets
```bash
make setup                 # Full: build -> start -> register -> verify
make rebuild               # Stop -> build -> start -> deregister -> register
make rebuild-quick         # Cached build, no re-register
make teardown              # Stop + deregister
```

### Test Targets (Interactive)
```bash
make validate-tests              # ALL tests (unit + integration)
make validate-unit               # Schemas, templates, config, register script
make validate-integration        # Registry, lifecycle, endpoints, nginx
make validate-registration-e2e   # agentic CLI -> Gateway -> Redis
make test-registration-adept     # Dual-network Redis verification
make test-registration-lifecycle # CLI-in-container register/verify/delete
make validate-globus-tools       # 71 Globus unit tests (mocked SDK)
make validate-globus-tools-integration  # 8 live Globus API tests
make validate-globus-all         # Combined Globus tests
```

### Nohup Background Test Targets
```bash
make nohup-test-all                    # Background ALL
make nohup-test-unit                   # Background unit tests
make nohup-test-integration            # Background integration
make nohup-test-registration-adept     # Background ADEPT registration
make nohup-test-registration-lifecycle # Background CLI lifecycle
make nohup-test-globus                 # Background Globus tests
```

---

## 8. What's Missing for Full Lifecycle E2E

Based on the current test infrastructure, the following are NOT covered:

1. **MCP Protocol Level Testing**
   - Raw MCP JSON-RPC calls to /mcp endpoint (not through ADEPT Gateway)
   - Tool list discovery via MCP protocol (biofoundation has `_mcp_rpc()` helper)
   - Streaming response handling

2. **Authentication Flow Testing**
   - JWT token validation at each tier
   - Auth rejection for unauthenticated/invalid tokens
   - Auth chain through nginx -> gateway -> orchestration

3. **Multi-Tool Orchestration E2E**
   - Chain of tool calls (launch -> invoke -> list -> shutdown in single flow)
   - Tool output validation through full response pipeline
   - Agent workflow state transitions

4. **ADEPT Nginx Proxy Testing** (not Academy's nginx)
   - Full auth chain: client -> nginx_proxy -> agent_gateway -> orchestration -> academy MCP
   - Response API round-trip through nginx

5. **Performance/Load Testing**
   - Concurrent agent launches
   - Memory usage under session load
   - Response latency benchmarks

6. **Globus Integration E2E**
   - End-to-end Globus Transfer/Search/Compute workflows through Response API
   - Credential management validation

7. **Security Testing**
   - ACL enforcement (group-based tool access)
   - Session isolation verification

---

## 9. Key Design Patterns Observed

1. **Fresh Registry Per Test**: Every test gets a new AcademyManagerRegistry, not the module singleton (prevents state leakage)
2. **Two-Step Registration**: Container discovery + host CLI registration (schemas only available in container)
3. **Framework Field Stripping**: Automatically removes ADEPT-injected parameters before registration
4. **Pydantic Export Utility**: Single source of truth: Pydantic model -> JSON schema -> ADEPT registration
5. **Fixture-Based Session Isolation**: UUID-based session IDs ensure tests don't interfere
6. **Makefile Canonical Pattern**: Mirrors biofoundation_mcp_server and vfm_mcp_server (DRY principle)
7. **Dual-Network Testing**: Integration tests join both app and data networks for full stack access
8. **Nohup Background Execution**: All tests can run in background with timestamped logs
