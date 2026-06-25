# Academy MCP Server — Onboarding Guide

> **Audience**: Systems administrators deploying the Academy MCP server on RC/EMSL VMs, and Academy developers adding new agent templates or tools.
>
> **Date**: 2026-03-28

---

## 1. What Is This?

The Academy MCP Server wraps [Academy](https://github.com/agentos-project/academy) — a federated agent middleware for distributed scientific workflows — into 4 MCP tools that ADEPT's ScientificWorkflowAgent can call via natural language.

```
User prompt: "Launch an echo agent and send it the message 'Hello Academy'"
         ↓
ADEPT Orchestration Service (ScientificWorkflowAgent)
         ↓ discovers tools via Redis external_tool:*
Academy MCP Server (FastAPI + FastMCP, port 9004)
         ↓ Academy API
AcademyManagerRegistry → Manager → Handle → Agent
```

### 1.1 MCP Tools

| Tool | Description |
|------|-------------|
| `launch_academy_agent` | Launch an echo, counter, or compute agent |
| `invoke_agent_action` | Invoke an action on a running agent |
| `list_academy_agents` | List all agents in the current session |
| `shutdown_academy_agent` | Shut down a running agent |

### 1.2 Agent Templates

| Agent | Actions | Purpose |
|-------|---------|---------|
| `EchoAgent` | `echo(message)`, `get_call_count()` | Integration testing |
| `CounterAgent` | `increment(value)`, `decrement(value)`, `get_count()`, `reset()` | Stateful demo |
| `ComputeAgent` | `factorial(n)`, `fibonacci(n)`, `is_prime(n)`, `get_computation_count()` | Scientific compute demo |

---

## 2. For Systems Administrators

### 2.1 Prerequisites

| Requirement | How to Verify |
|-------------|---------------|
| ADEPT core stack running | `docker ps \| grep agent_gateway` shows healthy |
| `adept_application_network` exists | `docker network ls \| grep adept_application_network` |
| `agentic` CLI installed | `which agentic` or check `.venv311/bin/agentic` |
| `/etc/hosts` has `keycloak` entry | `grep keycloak /etc/hosts` → `127.0.0.1 keycloak` |
| Docker engine running | `docker info` succeeds |

**Critical**: The `keycloak` hostname must resolve to `127.0.0.1` on the host. The `agentic` CLI gets JWTs from Keycloak, and the JWT's `iss` claim must match what `agent_gateway` expects (`http://keycloak:8180`). Without this `/etc/hosts` entry, tool registration will fail with 401 errors.

### 2.2 Quick Start (Full Setup)

```bash
cd examples/academy_mcp_server

# Full lifecycle: build → start → wait-healthy → register → verify
make setup
```

This runs:
1. `check-prerequisites` — verifies CLI and network
2. `build` — builds the Docker image
3. `start` — starts 3 containers (MCP server, nginx proxy, Redis)
4. `wait-healthy` — polls `/health` for up to 60 seconds
5. `register-tools` — discovers schemas from container, registers with ADEPT
6. `verify-tools` — confirms all 4 tools exist in Redis with `args_schema`

### 2.3 Manual Step-by-Step

```bash
# 1. Check prerequisites
make check-prerequisites

# 2. Build the Docker image
make build
# Log: logs/build_YYYYMMDD_HHMMSS.log

# 3. Start the 3-service stack
make start

# 4. Wait for health (polls up to 60s)
make wait-healthy

# 5. Verify all 3 services
make health
# Expected:
#   MCP Server:  {"status": "healthy", "mcp_tools": [...]}
#   Nginx Proxy: {"status": "ok", "proxy": "academy"}
#   Redis:       PONG

# 6. Register tools with ADEPT gateway
make register-tools
# Expected: 4/4 tools registered successfully

# 7. Verify in Redis
make verify-tools
# Expected: 4/4 tools verified in Redis

# 8. Smoke test (optional — requires ADEPT core stack)
make smoke-test
# Expected: HTTP 200, echo response from agent
```

### 2.4 The 3-Service Stack

| Container | Port | Purpose |
|-----------|------|---------|
| `academy_mcp_server` | 9004 | FastMCP app (MCP JSON-RPC + HTTP health) |
| `academy_nginx_proxy` | 9050 (HTTP), 9051 (HTTPS) | Reverse proxy, SSE buffering off, IP ACL |
| `academy_redis` | 6384 | Session state |

All containers join `adept_application_network` for service discovery.

### 2.5 Redis Architecture (Two Redis Instances)

Academy uses **two separate Redis instances** for different purposes. Understanding this distinction is critical for debugging registration and test failures.

| Redis Instance | Container | Network | Port (host) | Purpose |
|----------------|-----------|---------|-------------|---------|
| **Academy Redis** | `academy_redis` | `adept_application_network` | 6384 | MCP server artifact management: session state, agent handles, cached results |
| **ADEPT Redis** | `redis` | `adept_data_network` | 6379 | Platform-wide tool registration (`external_tool:*` keys), conversation state |

**How they interact**:

```
make register-tools
  └─→ agentic CLI → Agent Gateway → ADEPT Redis
      writes: external_tool:launch_academy_agent_tool  (tool metadata + args_schema)

User invokes "Launch an echo agent"
  └─→ Agent Gateway → Orchestration Service → Academy MCP Server
      └─→ Academy Redis: stores session/agent state
```

**Key points**:
- `make register-tools` and `make verify-tools` read/write **ADEPT Redis** (the `redis` container on `adept_data_network`)
- The Academy MCP server itself reads/writes **Academy Redis** (`academy_redis` on `adept_application_network`) for session state
- The `ACADEMY_REDIS_URL` env var in `.env` / `docker-compose.yaml` controls which Redis the MCP server uses — this is **always** Academy Redis
- Test targets that verify registration (`test-registration-adept`) need dual-network access: `adept_application_network` + `adept_data_network`

**Troubleshooting Redis-related issues**:

```bash
# Check Academy Redis (session state)
docker exec academy_redis redis-cli KEYS "*"

# Check ADEPT Redis (tool registration)
docker exec redis redis-cli KEYS "external_tool:*academy*"

# Verify a specific tool's metadata in ADEPT Redis
docker exec redis redis-cli GET "external_tool:launch_academy_agent_tool" | python3 -m json.tool

# If tools missing from ADEPT Redis after register-tools
make register-tools   # Re-register
make verify-tools     # Verify
```

### 2.6 Tool Registration (Two-Step Pattern)

Academy uses a **two-step registration** because `academy-py` is only installed inside the container:

```
Step 1 (container): Discover tool schemas via Python import
  docker exec -w /app/academy_mcp_server academy_mcp_server \
    python3 -c "from scripts.register_academy_tools import ..."
  → produces JSON with name, description, args_schema for each tool

Step 2 (host): Register with ADEPT via agentic CLI
  agentic tools register <name> -d <desc> -p mcp -u <mcp_url> \
    --tool-name <name> --args-schema '<json>' \
    --username admin --password admin
  → writes to Redis as external_tool:<name>
```

`make register-tools` automates both steps.

### 2.7 Teardown

```bash
# Deregister tools + stop containers
make teardown

# Just stop (keep tools registered)
make stop

# Rebuild from scratch
make rebuild
```

### 2.8 Operational Commands

```bash
# View logs
make logs           # All 3 containers
make logs-mcp       # MCP server only
make logs-proxy     # Nginx proxy only
make logs-short     # Last 50 lines each

# Health check
make health

# Show registered tool schemas
make show-schemas

# Rebuild (cached, no re-register)
make rebuild-quick
```

### 2.9 Configuration

Copy `.env.example` to `.env` to customize. Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `ACADEMY_PORT` | `9004` | MCP server port |
| `ACADEMY_REDIS_URL` | `redis://academy_redis:6379/0` | Redis connection |
| `ACADEMY_LOG_LEVEL` | `INFO` | Log verbosity |
| `ENGINE` | `docker` | Container engine (`docker` or `podman`) |
| `KEYCLOAK_URL` | `http://keycloak:8180` | Must use Docker service name |
| `GATEWAY_URL` | `http://localhost:8083` | Agent Gateway host port |
| `ADMIN_USER` | `admin` | ADEPT admin for registration |
| `ADMIN_PASS` | `admin` | ADEPT admin password |

### 2.10 Podman Mode

```bash
ENGINE=podman make setup
```

Uses `docker-compose.podman.yaml` overrides if present.

### 2.11 Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `register-tools` fails with 401 | JWT `iss` mismatch | Ensure `/etc/hosts` has `127.0.0.1 keycloak` |
| `register-tools` fails with "agentic CLI not found" | CLI not installed | `pip install -e ../../src/` from project root |
| `wait-healthy` times out | Container startup failure | `make logs-mcp` to see error |
| `verify-tools` shows "NOT found in Redis" | Registration didn't run | `make register-tools` first |
| Health check shows MCP unhealthy | Port conflict or crash | `docker restart academy_mcp_server` |
| Smoke test fails | Tools not registered or ADEPT stack down | `make verify-tools` then `make smoke-test` |
| Stale JWT token causes 401 | Cached token has wrong issuer | Delete `~/.adept-agentic/cache/admin_token.json` |

---

## 3. For Academy Developers

### 3.1 Project Structure

```
examples/academy_mcp_server/
├── academy_mcp_server/           # Python package
│   ├── main.py                   # FastAPI + FastMCP app
│   ├── config.py                 # Settings (Pydantic BaseSettings)
│   ├── schemas.py                # Pydantic models + export_registration_schema()
│   ├── manager_registry.py       # Session-scoped AcademyManagerRegistry
│   ├── agent_templates.py        # EchoAgent, CounterAgent, ComputeAgent
│   └── tools/
│       └── agent_lifecycle.py    # 4 MCP tool functions + register()
├── scripts/
│   ├── register_academy_tools.py # Container-side: schema discovery via MockMCP
│   └── register_from_schemas.py  # Host-side: registration from JSON via agentic CLI
├── tests/                        # 231 tests across 9 files
├── docs/                         # Architecture, testing, onboarding
├── nginx/                        # Proxy config template
├── docker-compose.yaml           # 3-service stack
├── Dockerfile                    # Multi-stage build
├── Makefile                      # Full lifecycle management
└── .env.example                  # Configuration template
```

### 3.2 Adding a New Agent Template

1. **Create the agent class** in `agent_templates.py`:

```python
from academy.agent import Agent

class MyNewAgent(Agent):
    """My new agent description."""

    async def my_action(self, param: str) -> dict:
        """Perform my action."""
        return {"result": param}
```

2. **Register it** in the agent type map in `tools/agent_lifecycle.py`:

```python
AGENT_TYPES = {
    "echo": EchoAgent,
    "counter": CounterAgent,
    "compute": ComputeAgent,
    "my_new": MyNewAgent,  # Add here
}
```

3. **Add tests** in `tests/test_agent_templates.py`:

```python
class TestMyNewAgent:
    @pytest.fixture
    def agent(self):
        return MyNewAgent()

    @pytest.mark.asyncio
    async def test_my_action(self, agent):
        result = await agent.my_action("hello")
        assert result["result"] == "hello"
```

4. **Rebuild and re-register**:

```bash
make rebuild
# This rebuilds the image, restarts containers, and re-registers tools
```

No schema changes needed — `launch_academy_agent` already accepts `agent_type` as a string parameter.

### 3.3 Adding a New MCP Tool

1. **Define the tool function** in `tools/agent_lifecycle.py`:

```python
async def my_new_tool(param1: str, param2: int = 10, mcp_session_id: str = "") -> dict:
    """Brief description of what this tool does.

    Detailed description for the LLM agent.
    """
    # Implementation
    return {"result": "..."}
```

2. **Register it** in the `register()` function:

```python
def register(mcp):
    @mcp.tool()
    async def launch_academy_agent_tool(...): ...

    @mcp.tool()
    async def my_new_tool_tool(param1: str, param2: int = 10, mcp_session_id: str = ""):
        """Brief description."""
        return await my_new_tool(param1, param2, mcp_session_id)
```

3. **Update test expectations** in `test_main.py`:

```python
# test_health_lists_four_tools → update count and set
assert len(data["mcp_tools"]) == 5  # was 4
expected_tools.add("my_new_tool")
```

4. **Add tool-specific tests** in `tests/test_agent_lifecycle.py`.

5. **Rebuild and re-register**:

```bash
make rebuild
```

The registration scripts auto-discover all `@mcp.tool()` decorated functions — no hardcoded schemas to maintain.

### 3.4 Running Tests During Development

```bash
# Fast unit tests (~1s, no runtime needed)
make validate-unit

# Full suite with integration (~11s)
make validate-tests

# Background run while you work
make nohup-test-all
tail -f logs/academy_test_all_*.log

# After registering, verify tools
make verify-tools

# Full round-trip smoke test
make smoke-test
```

### 3.5 Schema Discovery (How It Works)

The registration script uses a **MockMCP pattern** to discover tools without starting the FastMCP server:

```python
class _MockMCP:
    def tool(self):
        def decorator(func):
            captured.append(func)
            return func
        return decorator

mock = _MockMCP()
mod.register(mock)  # Captures all @mcp.tool() functions
```

For each captured function:
- `inspect.signature()` extracts parameter names and types
- `get_type_hints()` resolves `Optional`, `Annotated`, `Union` types
- `_FRAMEWORK_INJECTED_FIELDS` (10 fields like `mcp_session_id`, `user_id`, `ctx`) are stripped
- Result is a flat JSON schema: `{param: {type, description?, default?}}`

### 3.6 Key Design Constraints

1. **`academy-py` is container-only** — never import it on the host. Use the two-step registration pattern.
2. **`KEYCLOAK_URL` must be `http://keycloak:8180`** — Docker service name, not localhost. JWT `iss` claim validation requires this.
3. **Session isolation** — each `mcp_session_id` gets its own `AcademyManager` instance. Don't share state between sessions.
4. **Framework-injected fields** — `mcp_session_id`, `user_id`, `username`, `ctx`, etc. are injected by the ADEPT framework at call time. Don't include them in your tool's business logic parameters.

---

## 4. Architecture Reference

See `docs/ACADEMY_MCP_SERVER_LIFECYCLE_ARCHITECTURE.md` for:
- Three-plane architecture (self-contained, ADEPT integration, test)
- Canonical pattern comparison with biofoundation/VFM
- Gap analysis and backlog
- Port allocation across all MCP servers on RC VM

See `tests/TESTING.md` for a quick-reference test category table.

See `docs/TESTING_STRATEGY.md` for full testing strategy with validation evidence.
