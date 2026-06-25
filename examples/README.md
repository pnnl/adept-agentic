# ADEPT Integration Examples

This directory contains example code demonstrating how to integrate the ADEPT framework into various applications and workflows.

All examples are designed to work **STANDALONE** without requiring the full ADEPT framework installation.

---

## Installation

### Standalone Mode (Recommended for External Services)

Install only the required dependencies for examples:

```bash
# Install dependencies
pip install -r examples/requirements.txt

# Or manually
pip install openai httpx langgraph langchain-core litellm
```

**Benefits**:
- ✅ No ADEPT framework installation required
- ✅ Minimal dependencies (just OpenAI, HTTP client, LangGraph)
- ✅ Works from any Python environment
- ✅ Ideal for external services and automation

### ADEPT Framework Mode (Optional - Advanced Features)

For advanced features like session tracking in database:

```bash
# Install full ADEPT framework
pip install -e .

# Or run examples inside ADEPT container
docker exec orchestration_service python /app/examples/openai_client_service_token_example.py
```

**Benefits**:
- ✅ Session tracking in PostgreSQL database
- ✅ Advanced logging with ADEPT logger
- ✅ Direct access to ADEPT utilities
- ✅ Full framework integration

### Docker-Based Execution (Isolated Environment)

Build and run examples in Docker containers:

```bash
# Build standalone mode (minimal dependencies)
docker build -t adept-examples:standalone --target standalone examples/

# Run service token example (use dual networks as of Session 50)
docker run --rm \
    --network=adept_application_network \
    --network=adept_frontend_network \
    -e ADEPT_SERVICE_API_TOKEN="sk-service-..." \
    -e AGENT_GATEWAY_URL="http://agent_gateway:8081/v1" \
    adept-examples:standalone \
    python /app/examples/openai_client_service_token_example.py

# Build full mode (with ADEPT framework)
docker build -t adept-examples:full --target full -f examples/Dockerfile .

# Run with session tracking (use dual networks as of Session 50)
docker run --rm \
    --network=adept_application_network \
    --network=adept_frontend_network \
    -e ADEPT_SERVICE_API_TOKEN="sk-service-..." \
    -e AGENT_GATEWAY_URL="http://agent_gateway:8081/v1" \
    -e POSTGRES_URL="postgresql://admin:admin@postgres:5432/postgres" \
    adept-examples:full \
    python /app/examples/openai_client_service_token_example.py
```

**Benefits**:
- ✅ Isolated dependencies (no conflicts with host)
- ✅ Reproducible environment
- ✅ Easy CI/CD integration
- ✅ Network access to ADEPT services

### CLI Setup (Host Machine)

If running examples from the host using the `agentic` CLI, run the bootstrap command first to auto-configure connectivity:

```bash
agentic config bootstrap
```

See **[CLI Bootstrap Guide](../docs/guides/CLI_BOOTSTRAP_GUIDE.md)** for environment variables, non-interactive mode, and troubleshooting.

---

## Session 50 Network Segmentation Compatibility

**Date**: February 2026
**Status**: ✅ All Examples Compatible

As of Session 50, ADEPT has migrated to a three-tier network architecture for enhanced security. All examples have been validated and are fully compatible with the new network structure.

### Three-Tier Network Architecture

| Network | Services | Purpose |
|---------|----------|---------|
| `adept_frontend_network` | nginx_proxy, OAuth2 proxy, UIs | User-facing services (external access) |
| `adept_application_network` | agent_gateway, orchestration_service, Keycloak, MCP servers | Business logic tier (internal services) |
| `adept_data_network` | PostgreSQL, Redis | Data persistence tier |
| `agentic_framework_network` | **[DEPRECATED - EMPTY]** | Legacy network (no longer used) |

### Access Patterns for Examples

#### External Clients (Recommended for Production)

Use `https://api.agentic.local/v1/...` for all API calls:

```bash
# OpenAI client example (external access via nginx_proxy)
export ADEPT_SERVICE_API_TOKEN="sk-service-..."
python examples/openai_client_service_token_example.py

# Environment variables
export AGENT_GATEWAY_URL="https://api.agentic.local/v1"  # External (nginx_proxy)
```

**Benefits**:
- ✅ TLS encryption
- ✅ Authentication gateway (handles JWT and service tokens)
- ✅ Production-ready routing
- ✅ Presigned URL optimization

#### Container-Based Examples (Internal Access)

Use `http://agent_gateway:8081/v1/...` for direct access from Docker containers:

```bash
# Run example inside Docker container (internal access)
docker run --rm \
    --network=adept_application_network \
    --network=adept_frontend_network \
    -e ADEPT_SERVICE_API_TOKEN="sk-service-..." \
    -e AGENT_GATEWAY_URL="http://agent_gateway:8081/v1" \
    adept-examples:standalone \
    python /app/examples/openai_client_service_token_example.py
```

**Why Dual Networks?**
- `adept_application_network`: Access internal services (Keycloak, agent_gateway, PostgreSQL)
- `adept_frontend_network`: Access nginx_proxy for external-style testing
- Docker DNS automatically resolves `api.agentic.local` to nginx_proxy

#### Local Development (Host Access)

Use `http://localhost:8083/v1/...` from host terminal:

```bash
# Run example from host (uses port mapping)
export AGENT_GATEWAY_URL="http://localhost:8083/v1"
export ADEPT_SERVICE_API_TOKEN="sk-service-..."
python examples/openai_client_service_token_example.py
```

**Port Mappings** (see CLAUDE.md):
- Agent Gateway: `localhost:8083` → `agent_gateway:8081`
- NGINX Proxy: `localhost:80/443` → `nginx_proxy:80/443`

### Prerequisites

#### Service Token (Required for OpenAI Examples)

Obtain a service token from the credentials directory:

```bash
# Auto-discovery from credentials directory
export ADEPT_SERVICE_API_TOKEN=$(grep OPENWEBUI_SERVICE_API_KEY \
  deployment/local/docker-compose/.env-keycloak-credentials-dir/.env-keycloak-credentials \
  | cut -d'=' -f2)

# Or create a new service token
make create-service-token NAME=my-example GROUPS=notebook-users TTL_DAYS=90
```

#### Keycloak JWT (Required for LangGraph Examples)

Use notebook-user credentials:

```bash
export KEYCLOAK_USERNAME=notebook-user
export KEYCLOAK_PASSWORD=notebook-password
export KEYCLOAK_URL=https://api.agentic.local
```

### Validation Results

All examples have been validated with Session 50 network architecture:

| Example | Test Results | Status |
|---------|-------------|--------|
| OpenAI Client Examples | 6/6 tests passed | ✅ 100% Compatible |
| LangGraph Quickstart | Authentication requires fix | ⚠️ Pre-existing issue |
| LangGraph Integration | Authentication requires fix | ⚠️ Pre-existing issue |
| Docker-Based Examples | All tests passed | ✅ 100% Compatible |

**Validation Reports**:
- OpenAI Client: `logs/validate_openai_with_token_20260208_195919.log`
- LangGraph: `logs/validate_langgraph_examples_20260208_200002.log`
- Full Report: `docs/implementation-reports/SESSION_50_POST_IMPLEMENTATION_VALIDATION.md`

### Session Creation Works Identically

All three access patterns support identical session creation workflows:

```python
# Thread creation works the same regardless of entry point
response = client.post("/v1/threads", headers={"Authorization": f"Bearer {token}"})

# Message streaming works the same
response = client.post("/v1/responses/chat/completions",
    json={"model": "gpt-4", "messages": messages},
    headers={"Authorization": f"Bearer {token}"}
)

# File uploads work the same
response = client.post("/v1/files",
    files={"file": file_content},
    headers={"Authorization": f"Bearer {token}"}
)
```

**Key Insight**: nginx_proxy is a **transparent proxy** (except for file downloads via presigned URLs). Session logic is identical regardless of whether you access via:
- `https://api.agentic.local/v1/...` (nginx_proxy)
- `http://agent_gateway:8081/v1/...` (direct)
- `http://localhost:8083/v1/...` (host port mapping)

### Troubleshooting Network Issues

#### Connection Refused Errors

```bash
# ❌ WRONG - Legacy network (no longer works)
docker run --network=agentic_framework_network ...
# Error: All connection attempts failed

# ✅ CORRECT - Use dual networks
docker run \
  --network=adept_application_network \
  --network=adept_frontend_network \
  ...
```

#### DNS Resolution Errors

```bash
# Test DNS resolution inside container
docker run --rm --network=adept_frontend_network busybox nslookup api.agentic.local
# Should resolve to nginx_proxy IP (e.g., 172.22.0.4)

# Verify nginx_proxy is on frontend network
docker inspect nginx_proxy | grep -A 10 '"adept_frontend_network"'
```

#### Service Availability

```bash
# Verify all services are running
docker ps | grep -E "agent_gateway|orchestration_service|nginx_proxy"

# Test agent_gateway directly from inside application network
docker run --rm --network=adept_application_network busybox wget -O- http://agent_gateway:8081/health
```

---

## Service Token Examples

### OpenAI Client with Service Token (`openai_client_service_token_example.py`)

**Purpose**: Demonstrate OpenAI-compatible client usage with service API tokens (alternative to user JWT tokens).

**Features**:
- ✅ **STANDALONE**: Works without ADEPT framework installation
- ✅ **Service Token Authentication**: Long-lived bearer tokens (90 days default)
- ✅ **No Login UI Required**: Ideal for automation and scripts
- ✅ **Session Tracking** (Optional): Gracefully degrades if ADEPT not available
- ✅ **Streaming Support**: Both regular and streaming chat completions
- ✅ **Pattern Comparison**: Side-by-side with Streamlit Chat.py (user JWT)

**Usage**:
```bash
# 1. Create service token (requires ADEPT framework access)
make create-service-token NAME=my-automation GROUPS=notebook-users TTL_DAYS=90

# 2. Set environment variable
export ADEPT_SERVICE_API_TOKEN="sk-service-my-automation-abc123..."

# 3. Install standalone dependencies
pip install openai httpx

# 4. Run example
python examples/openai_client_service_token_example.py
```

**Output**:
```
================================================================================
Runtime Mode Detection
================================================================================
ADEPT Logging Available: ❌ No (using standard logging)
ADEPT Session Tracking: ❌ No (optional feature disabled)

💡 This example works in STANDALONE mode without ADEPT framework libraries.
   Session tracking is optional and will gracefully degrade if unavailable.
================================================================================

================================================================================
OpenAI Client with Service API Token Example (STANDALONE)
================================================================================

[Step 1] Creating OpenAI client with service API token...
  Mode: STANDALONE (no ADEPT framework required)
✅ OpenAI client created successfully

[Step 2] Creating ADEPT session for tracking (optional, requires ADEPT)...
⚠️  ADEPT session tracking unavailable, using local UUID: 550e8400-...
   (Operations will still work, just won't be persisted to database)

[Step 3] Making chat completion call (STANDALONE)...
  Query: 'What is the capital of France?'

[Step 4] Response received:
--------------------------------------------------------------------------------
The capital of France is Paris.
--------------------------------------------------------------------------------

Token Usage:
  Prompt tokens: 45
  Completion tokens: 12
  Total tokens: 57

✅ Example completed successfully!
```

**Key Functions**:

1. **`get_openai_client_with_service_token()`** - STANDALONE
   - Creates OpenAI client with service API token
   - No ADEPT framework required
   - Only needs: `openai` package + `ADEPT_SERVICE_API_TOKEN` env var

2. **`create_adept_session()`** - OPTIONAL
   - Mimics `session_utils.py:create_session_in_db()` pattern
   - Creates UserSession in database (if ADEPT available)
   - Gracefully degrades to local UUID if ADEPT not available

**Service Token vs User JWT**:

| Feature | Service API Token | User JWT Token |
|---------|-------------------|----------------|
| **Authentication** | Bearer sk-service-* | Keycloak OAuth2 flow |
| **Lifespan** | 90 days (default) | 8 hours (access token) |
| **Refresh Required** | No | Yes (refresh_token) |
| **Use Case** | Services, automation | End-user interactive |
| **Identity** | Service username | Actual user (sub) |
| **Complexity** | Low (just API key) | High (OIDC flow) |
| **Standalone** | ✅ Yes | ❌ No (requires Streamlit/JWT) |

**When to Use**:
- ✅ CI/CD pipelines and automation
- ✅ External service integration (n8n, OpenWebUI)
- ✅ Long-running background processes
- ✅ Testing and validation scripts
- ✅ Any scenario without user login UI

---

## Validation Scripts

**Session 48 Enhancement**: Comprehensive validation scripts for testing examples and troubleshooting.

### OpenAI Client Validation (`scripts/validate-openai-client-example.py`)

**Purpose**: Systematically test OpenAI client example with service API tokens.

**Tests Performed**:
1. ✅ **Import Dependencies** - Validates standalone mode (openai, httpx)
2. ✅ **Service Token Authentication** - Auto-discovery from credentials directory
3. ✅ **Chat Completion** - Non-streaming responses
4. ✅ **Streaming Completion** - Streaming responses
5. ✅ **Session Tracking** - Optional ADEPT framework feature (graceful degradation)
6. ✅ **Error Handling** - Invalid model error handling

**Usage**:
```bash
# With explicit service token
export ADEPT_SERVICE_API_TOKEN="sk-service-..."
python examples/scripts/validate-openai-client-example.py

# Or with auto-discovery (reads from credentials directory)
python examples/scripts/validate-openai-client-example.py
```

**Output**:
```
OpenAI Client with Service Token Example Validator
Version: 1.0.0

Configuration:
  Agent Gateway URL: http://localhost:8083/v1
  Service Token: ********************... (configured)

[TEST] 1. Import Dependencies (Standalone Mode)... ✓ PASS (0.12s)
  All dependencies imported successfully (standalone mode validated)
  - openai_version: 1.54.3
  - httpx_version: 0.27.2
  - adept_logging: unavailable (standalone mode)
  - adept_session_tracking: unavailable (standalone mode)

[TEST] 2. Service Token Authentication... ✓ PASS (0.08s)
  Service token authentication successful
  - models_available: 2
  - models: ['agentic-framework:scientific-agent-v1', ...]

✓ All validation tests passed!
```

### LangGraph Validation (`scripts/validate-langgraph-examples.py`)

**Purpose**: Systematically test LangGraph integration examples.

**Tests Performed**:
1. ✅ **Import Dependencies** - litellm, langgraph, langchain-core
2. ✅ **Keycloak Authentication** - JWT token generation (master realm)
3. ✅ **ADEPT API Connectivity** - /v1/models endpoint
4. ✅ **LiteLLM with ADEPT Model** - agentic-framework:scientific-agent-v1
5. ✅ **Quick Start Components** - langgraph_adept_quickstart.py validation
6. ✅ **Integration Components** - langgraph_adept_integration.py validation
7. ✅ **LangGraph Workflow** - StateGraph execution
8. ✅ **Langfuse Traces** - Observability verification

**Usage**:
```bash
# Default configuration (uses bootstrap defaults)
python examples/scripts/validate-langgraph-examples.py

# Or with custom configuration
export KEYCLOAK_USERNAME="notebook-user"
export KEYCLOAK_PASSWORD="notebook-password"
export KEYCLOAK_REALM="master"  # ADEPT uses master realm
python examples/scripts/validate-langgraph-examples.py
```

**Session 48 Fixes Applied**:
- ✅ Fixed Keycloak realm from `agentic-framework` to `master` (ADEPT uses master realm)
- ✅ Fixed client ID from `notebook-user-client` to `validation-runner-client` (confidential client)
- ✅ Added client secret auto-discovery from credentials directory
- ✅ Fixed `litellm.__version__` and `langgraph.__version__` AttributeError (graceful handling)
- ✅ Added default password fallback (`notebook-password`)

**Example Files Updated**:
- `langgraph_adept_quickstart.py` - Now uses master realm, configurable client_id/secret
- `langgraph_adept_integration.py` - ADEPTAuthenticator updated with correct realm and client parameters

---

## LangGraph Integration Examples

### LiteLLM Provider Registration (Session 48)

**IMPORTANT**: ADEPT examples use LiteLLM's custom provider registration to enable the `adept/model-name` format.

All LangGraph examples now include automatic provider registration:

```python
import litellm

# Register ADEPT as a custom LiteLLM provider
litellm.register_model({
    "adept/scientific-agent-v1": {
        "max_tokens": 4096,
        "max_input_tokens": 100000,
        "max_output_tokens": 4096,
        "input_cost_per_token": 0.00001,
        "output_cost_per_token": 0.00003,
        "litellm_provider": "openai",  # Use OpenAI-compatible protocol
        "mode": "chat",
        "supports_function_calling": True,
    },
})
```

**Why This Is Needed**:
- LiteLLM validates model names client-side before making API calls
- Only recognizes hardcoded provider prefixes (openai/, anthropic/, azure/, etc.)
- Custom provider registration tells LiteLLM to treat `adept/` as valid
- Configures LiteLLM to use OpenAI-compatible API protocol for ADEPT models

**Model Formats Supported**:
- ✅ `adept/scientific-agent-v1` (LiteLLM-compatible alias, recommended)
- ✅ `agentic-framework:scientific-agent-v1` (Native ADEPT format)
- ✅ Both formats work with ADEPT Response API and Chat Completion endpoints

**Without Provider Registration**:
```python
# ❌ This fails with "LLM Provider NOT provided" error
response = litellm.completion(
    model="adept/scientific-agent-v1",
    messages=[{"role": "user", "content": "Hello"}],
    api_base="https://api.agentic.local/v1",
)
```

**With Provider Registration** (as in examples):
```python
# ✅ This works - LiteLLM recognizes adept/ prefix
litellm.register_model({
    "adept/scientific-agent-v1": {"litellm_provider": "openai", ...}
})

response = litellm.completion(
    model="adept/scientific-agent-v1",
    messages=[{"role": "user", "content": "Hello"}],
    api_base="https://api.agentic.local/v1",
)
```

**Alternative: Use Native OpenAI Client**:
```python
# No registration needed with native OpenAI client
from openai import OpenAI

client = OpenAI(
    base_url="https://api.agentic.local/v1",
    api_key=token,
)

response = client.chat.completions.create(
    model="adept/scientific-agent-v1",  # Works without registration
    messages=[{"role": "user", "content": "Hello"}],
)
```

---

### Quick Start (`langgraph_adept_quickstart.py`)

**Purpose**: Minimal example for getting started quickly.

**Features**:
- Simple authentication
- Basic LangGraph workflow
- Single agent with ADEPT API

**Usage**:
```bash
export KEYCLOAK_USERNAME="notebook-user"
export KEYCLOAK_PASSWORD="your_password"
python examples/langgraph_adept_quickstart.py
```

**Output**:
```
============================================================
LangGraph + ADEPT Quick Start
============================================================

[1/3] Authenticating as notebook-user...
✓ Token: eyJhbGciOiJSUzI1NiIsInR5cCI...

[2/3] Creating LangGraph workflow...
✓ Workflow ready

[3/3] Running query...
Query: What is the capital of France?

Response:
------------------------------------------------------------
The capital of France is Paris.
------------------------------------------------------------

✓ View traces: https://api.agentic.local/langfuse
✓ Thread ID: quickstart-demo

============================================================
```

---

### Full Integration Example (`langgraph_adept_integration.py`)

**Purpose**: Comprehensive demonstration with all features.

**Features**:
- Full authentication management (token refresh)
- Session management for Langfuse telemetry
- Multi-agent LangGraph workflow
- Conditional routing between agents
- Production-ready patterns

**Usage**:
```bash
export KEYCLOAK_USERNAME="notebook-user"
export KEYCLOAK_PASSWORD="your_password"
python examples/langgraph_adept_integration.py
```

**Components**:

1. **ADEPTAuthenticator**: Keycloak JWT authentication
2. **ADEPTSessionManager**: Thread ID and session context management
3. **ADEPTLiteLLMClient**: LiteLLM client configured for ADEPT
4. **Multi-Agent Workflow**: Researcher → Data Analyst → Visualizer

**Workflow**:
```
User Query
    ↓
Researcher Agent (ADEPT API)
    ↓
Data Analyst Agent (ADEPT API)
    ↓
Visualizer Agent (ADEPT API)
    ↓
Final Result
```

---

## Key Concepts

### Authentication

All examples use **Keycloak JWT tokens** for authentication:

```python
import httpx

def get_adept_token(username: str, password: str) -> str:
    """Get JWT token from Keycloak."""
    token_url = "https://api.agentic.local/auth/realms/agentic-framework/protocol/openid-connect/token"

    response = httpx.post(token_url, data={
        "grant_type": "password",
        "client_id": "notebook-user-client",
        "username": username,
        "password": password,
    }, verify=False)

    return response.json()["access_token"]
```

### Session Management

**Thread ID** is the key for grouping related interactions:

```python
from litellm import completion

response = completion(
    model="gpt-4",
    messages=[{"role": "user", "content": "Hello"}],
    base_url="https://api.agentic.local/v1",
    api_key=f"Bearer {token}",
    extra_headers={"X-Thread-Id": "my-thread-123"},  # Groups related calls
)
```

**IMPORTANT**: You do **NOT** need to manually manage:
- `user_id` - Extracted from JWT token automatically
- `session_id` - Created by ADEPT orchestration service automatically

### Langfuse Telemetry

**Automatic telemetry** is enabled for all ADEPT API calls:

- All requests automatically traced
- User attribution from JWT token
- Thread grouping via `X-Thread-Id` header
- View traces at: https://api.agentic.local/langfuse

**No manual instrumentation required!**

---

## Prerequisites

### Environment Variables

```bash
# Required for authentication
export KEYCLOAK_USERNAME="notebook-user"
export KEYCLOAK_PASSWORD="your_password"

# Optional: Override default endpoints
export ADEPT_API_URL="https://api.agentic.local"
export KEYCLOAK_URL="https://api.agentic.local/auth"
```

### Python Dependencies

**Standalone Mode** (minimal dependencies):
```bash
# Install from requirements.txt
pip install -r examples/requirements.txt

# Or manually install core dependencies
pip install openai httpx

# For LangGraph examples, also install
pip install langgraph langchain-core litellm
```

**ADEPT Framework Mode** (full features):
```bash
# Install full ADEPT framework
pip install -e .
```

### ADEPT Framework

Ensure ADEPT services are running:

```bash
cd /path/to/adept-extended-2025-11-07
make start
```

Verify services are healthy:

```bash
make validate-service-health
```

---

## Documentation

- **Comprehensive Guide**: [docs/integration/LANGGRAPH_ADEPT_INTEGRATION_GUIDE.md](../docs/integration/LANGGRAPH_ADEPT_INTEGRATION_GUIDE.md)
- **Session 48 Report**: [docs/implementation-reports/SESSION_48_PRESIGNED_URL_HOSTNAME_FIX.md](../docs/implementation-reports/SESSION_48_PRESIGNED_URL_HOSTNAME_FIX.md)
- **Architecture**: [CLAUDE.md](../CLAUDE.md)

---

## Troubleshooting

### Authentication Errors

**Error**: `401 Unauthorized`

**Solution**:
```bash
# Test credentials manually
curl -X POST "https://api.agentic.local/auth/realms/agentic-framework/protocol/openid-connect/token" \
  -d "grant_type=password" \
  -d "client_id=notebook-user-client" \
  -d "username=$KEYCLOAK_USERNAME" \
  -d "password=$KEYCLOAK_PASSWORD" \
  -k
```

### Connection Errors

**Error**: `Connection refused`

**Solution**:
```bash
# Verify ADEPT services are running
docker ps | grep -E "agent_gateway|orchestration_service"

# Check service logs
docker logs agent_gateway
docker logs orchestration_service
```

### SSL Certificate Errors

**Error**: `SSL certificate verification failed`

**Solution**: For local development, disable SSL verification:
```python
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Use verify=False in httpx requests
response = httpx.post(url, data=data, verify=False)
```

### Langfuse Traces Not Appearing

**Solution**:
1. Verify thread_id is passed in `X-Thread-Id` header
2. Check orchestration service logs:
   ```bash
   docker logs orchestration_service | grep -i langfuse
   ```
3. Verify Langfuse credentials in `.env`

---

## Advanced Usage

### Custom Model Selection

```python
# Use specific model (ADEPT auto-routes to provider)
response = call_adept_api(
    messages=messages,
    token=token,
    model="claude-3-opus",  # or "gpt-4o", "gpt-4", etc.
)
```

### Streaming Responses

```python
from litellm import completion

response = completion(
    model="gpt-4",
    messages=messages,
    base_url="https://api.agentic.local/v1",
    api_key=f"Bearer {token}",
    stream=True,  # Enable streaming
)

for chunk in response:
    print(chunk.choices[0].delta.content, end="")
```

### Multi-Agent with Tool Calling

```python
# ADEPT automatically provides access to MCP tools
# (ExecuteCode, WebSearch, CSV RAG, etc.)

response = completion(
    model="gpt-4",
    messages=[{"role": "user", "content": "Search for recent papers on quantum computing"}],
    base_url="https://api.agentic.local/v1",
    api_key=f"Bearer {token}",
    extra_headers={"X-Thread-Id": thread_id},
)

# ADEPT agent will automatically call WebSearch tool and return results
```

---

## Example MCP Tools (Session 50)

**Directory**: `examples/mcp_tools/`

Demonstrates how to create external MCP tool servers for dynamic registration with ADEPT.

**What's Included**:
- **Weather Service Example**: Complete MCP server with multiple tools
- **Registration Guide**: CLI and API methods for tool registration
- **Development Template**: Starter template for custom tools
- **Best Practices**: Security, error handling, and debugging tips

**Quick Start**:
```bash
# 1. Run the example weather server
python examples/mcp_tools/example_weather_mcp_server.py

# 2. Register with ADEPT
agentic tool register \
  --name weather_service \
  --type mcp \
  --url "stdio:python examples/mcp_tools/example_weather_mcp_server.py" \
  --description "Get weather data for any city"

# 3. Agent automatically discovers and uses the tools
```

**Documentation**: [examples/mcp_tools/README.md](mcp_tools/README.md)

**Use Cases**:
- ✅ Domain-specific tools (finance, healthcare, research)
- ✅ Third-party API integrations
- ✅ Custom business logic as reusable tools
- ✅ Rapid prototyping without core framework changes

---

## Opentrons MCP Server (Session 59)

**Directory**: `examples/opentrons_mcp_server/`

MCP server providing Opentrons OT-2 liquid handling protocol execution. Enables AI agents to validate and execute liquid transfer protocols through natural language.

**Features**:
- Protocol validation with JSON Schema safety rules
- Simulation mode (default) and real hardware support
- 96-well and 384-well plate support with p10/p20/p300/p1000 pipettes
- Session-isolated protocol execution
- MCP protocol integration (FastMCP + FastAPI)

**Quick Start**:
```bash
# Full lifecycle: build, start, register tool, verify
cd examples/opentrons_mcp_server
make setup

# Verify
curl http://localhost:9003/health
make verify-tool
```

**Registered Tool**: `execute_opentrons_protocol` (MCP protocol, port 9003)

**Makefile Targets**:

| Target | Description |
|--------|-------------|
| `make setup` | Full lifecycle: build + start + register + verify |
| `make rebuild` | Rebuild from scratch and re-register |
| `make teardown` | Stop container and deregister tool |
| `make register-tool` | Register MCP tool with ADEPT |
| `make verify-tool` | Verify tool in Redis + Gateway API |
| `make health` | Check health endpoint |
| `make smoke-test` | E2E test via Response API |

**Natural Language**:
```
User: "Execute an Opentrons protocol to transfer 50uL from A1 to B1 on a 96-well plate"
Agent: [calls execute_opentrons_protocol tool]
Agent: "Protocol validated. 1 transfer scheduled: A1→B1 (50uL, p300_single)."
```

**Documentation**: [examples/opentrons_mcp_server/README.md](opentrons_mcp_server/README.md)

---

## Academy MCP Server (Session 59)

**Directory**: `examples/academy_mcp_server/`

MCP server wrapping [Academy](https://github.com/agentos-project/academy) federated agent lifecycle operations into 4 ADEPT-compatible tools. Academy is a federated agent middleware for distributed scientific workflows (Slurm, sensors, Globus).

**MCP Tools** (4 registered):

| Tool | Description |
|------|-------------|
| `launch_academy_agent` | Launch an echo, counter, or compute agent |
| `invoke_agent_action` | Invoke an action on a running agent |
| `list_academy_agents` | List all agents in the current session |
| `shutdown_academy_agent` | Shut down a running agent |

**Agent Templates**:

| Agent | Actions | Purpose |
|-------|---------|---------|
| `EchoAgent` | `echo(message)`, `get_call_count()` | Integration testing |
| `CounterAgent` | `increment(value)`, `decrement(value)`, `get_count()`, `reset()` | Stateful demo |
| `ComputeAgent` | `factorial(n)`, `fibonacci(n)`, `is_prime(n)`, `get_computation_count()` | Scientific demo |

**Quick Start**:
```bash
# Full lifecycle: build, start, register 4 tools, verify
cd examples/academy_mcp_server
make setup

# Verify
curl http://localhost:9004/health
make verify-tools
```

**Test Suite** (118/118 passing):
```bash
cd examples/academy_mcp_server
make validate-tests           # All tests (unit + integration)
make validate-unit            # Schemas + agent templates only
make validate-integration     # Registry + lifecycle + endpoints
```

**Makefile Targets**:

| Target | Description |
|--------|-------------|
| `make setup` | Full lifecycle: build + start + register 4 tools + verify |
| `make rebuild` | Rebuild from scratch and re-register |
| `make teardown` | Stop container and deregister all tools |
| `make register-tools` | Register 4 MCP tools with ADEPT |
| `make verify-tools` | Verify 4 tools in Redis |
| `make health` | Check health endpoint |
| `make smoke-test` | E2E test via Response API |
| `make validate-tests` | Run full test suite (118 tests) |

**Natural Language**:
```
User: "Launch a compute agent, calculate factorial of 10, then shut it down"
Agent: [calls launch_academy_agent with agent_type=compute]
Agent: [calls invoke_agent_action with action=factorial, n=10]
Agent: [calls shutdown_academy_agent]
Agent: "Factorial of 10 is 3628800. Agent shut down."
```

**Documentation**: [examples/academy_mcp_server/README.md](academy_mcp_server/README.md)

---

## EMSL Sandbox (Session 63)

**Directory**: `examples/emsl_sandbox/`

Standalone sandbox-only deployment for EMSL Rocky 9 on-premise environments. Uses the core project's `sandbox_mcp_server` with a specialized deployment configuration (Podman, Rocky 9, Gurobi optimization solver, nginx IP-restricted proxy).

**Services** (3 containers):

| Service | Purpose |
|---------|---------|
| `sandbox_nginx_proxy` | IP-restricted reverse proxy (:80/:8080) |
| `sandbox_mcp_server` | Code execution with Gurobi support (:8082) |
| `redis` | Session cache (:6379 internal) |

**MCP Tools** (6 registered with parent ADEPT gateway):

| Tool | Description |
|------|-------------|
| `emsl_sandbox_execute_code` | Execute Python/JS/Bash on EMSL sandbox |
| `emsl_sandbox_execute_code_with_file` | Execute code with file access |
| `emsl_sandbox_analyze_data_file` | Analyze uploaded data files |
| `emsl_sandbox_get_session_workspace_path` | Get session workspace path |
| `emsl_sandbox_list_uploaded_files` | List session files |
| `emsl_sandbox_query_generated_file_content` | Search file content |

**Quick Start**:
```bash
cd examples/emsl_sandbox
cp .env.example .env    # Configure PNNL NID and IP addresses
make build && make start && make health
make register-tools EMSL_HOST=<emsl-vm-ip>   # From AWS EC2 host
```

**Makefile Targets**:

| Target | Description |
|--------|-------------|
| `make build` | Build sandbox images |
| `make start` | Start sandbox stack |
| `make teardown` | Full teardown (containers + volumes) |
| `make register-tools` | Register 6 tools with parent ADEPT gateway |
| `make verify-tools` | Verify tool registration in Redis |
| `make health` | Check sandbox health |
| `make validate-all` | Run all E2E tests (deployment + Gurobi) |

**Documentation**: [examples/emsl_sandbox/README.md](emsl_sandbox/README.md)

---

## A2A Gateway Mesh Workshop (Session 52)

**Directory**: `examples/a2a-workshop/`

Hands-on workshop for setting up Agent-to-Agent (A2A) communication between independent ADEPT instances across different hosts.

**Purpose**: Enable distributed ADEPT deployments to discover peers, delegate tasks, and maintain complete autonomy while collaborating across networks.

### What is A2A?

**Agent-to-Agent (A2A)** communication enables independent ADEPT instances to:
- Discover and register peer gateways across different hosts (VMs, clouds, data centers)
- Delegate tasks to remote instances for distributed workloads
- Maintain complete independence (separate databases, credentials, services)
- Build federated gateway meshes for research collaboration

### Workshop Structure

The workshop includes comprehensive documentation and IP-agnostic scripts for multi-host A2A setup:

| Component | Description |
|-----------|-------------|
| **README.md** | Complete workshop guide with architecture, setup steps, and troubleshooting |
| **00_verify_environment.sh** | Check ADEPT services are healthy before A2A registration |
| **01_generate_a2a_token.sh** | Generate service tokens for inter-gateway authentication |
| **02_register_peer.sh** | Register remote ADEPT instance as peer gateway |
| **03_test_connectivity.sh** | Test A2A connectivity and authentication |
| **04_end_to_end_test.sh** | Comprehensive validation of complete A2A workflow |

**All scripts are IP-agnostic**: Automatically detect local IP, use environment variables, and work across different network configurations.

### Quick Start

**Execution Environment**: Workshop scripts run **on the host** (your VM or physical machine), not inside Docker containers. They need Docker access, `make` commands, and detect the host's IP address.

**Prerequisites**:
- Two or more ADEPT instances running on separate hosts (VMs, containers, or physical servers)
- Network connectivity between hosts (test with `ping <remote_ip>`)
- Firewall rules allowing HTTPS traffic (port 443) or HTTP (port 8083) between hosts
- Host prerequisites: Docker, Bash, curl, jq, agentic CLI (`pip install -e src/`)

**Alternative**: For container-based execution (if host lacks prerequisites), see workshop README section "Container-Based Alternative"

**Example Scenario**: Connect Azure VM (10.0.0.2) with AWS EC2 (10.0.0.1)

**On Both Hosts**:

```bash
# Step 0: Verify environment
cd examples/a2a-workshop/scripts
./00_verify_environment.sh

# Expected output:
# ✅ Docker is running
# ✅ agent_gateway is running
# ✅ gateway_registry is running
# ✅ Agent Gateway API is accessible
# Environment Status: ✅ READY FOR A2A REGISTRATION
```

**On Azure VM**:

```bash
# Step 1: Generate A2A service token
./01_generate_a2a_token.sh --name a2a-azure-to-aws --ttl-days 365
# Save token: export LOCAL_A2A_TOKEN="sk-service-a2a-azure-to-aws-..."

# Step 2: Register AWS peer
./02_register_peer.sh \
  --peer-ip 10.0.0.1 \
  --peer-alias aws-gateway \
  --description "AWS EC2 Production Gateway" \
  --tags "aws,ec2,us-east-1"

# Step 3: Test connectivity
./03_test_connectivity.sh --peer-alias aws-gateway
# Expected: ✅ READY FOR A2A TASK DELEGATION
```

**On AWS EC2** (mirror setup):

```bash
# Generate token for AWS → Azure communication
./01_generate_a2a_token.sh --name a2a-aws-to-azure --ttl-days 365

# Register Azure peer
./02_register_peer.sh \
  --peer-ip 10.0.0.2 \
  --peer-alias azure-gateway \
  --description "Azure VM Development Gateway" \
  --tags "azure,vm,eastus"

# Test connectivity
./03_test_connectivity.sh --peer-alias azure-gateway
```

### End-to-End Validation

Run comprehensive workflow test:

```bash
# Full E2E validation
./04_end_to_end_test.sh \
  --peer-ip 10.0.0.1 \
  --peer-alias aws-gateway

# Expected output:
# Test 1: Environment verification... ✅ PASSED
# Test 2: Service token generation... ✅ PASSED
# Test 3: Peer registration... ✅ PASSED
# Test 4: Connectivity test... ✅ PASSED
#
# All tests passed! A2A setup is complete.
```

### Architecture Overview

```
┌─────────────────────────────────────┐         ┌─────────────────────────────────────┐
│  ADEPT Instance A (Azure VM)        │         │  ADEPT Instance B (AWS EC2)         │
│  IP: 10.0.0.2                     │         │  IP: 10.0.0.1                    │
│                                     │         │                                     │
│  nginx_proxy → agent_gateway        │         │  nginx_proxy → agent_gateway        │
│       ↓              ↓              │         │       ↓              ↓              │
│  orchestration   gateway_registry   │         │  orchestration   gateway_registry   │
│       ↓              ↓              │         │       ↓              ↓              │
│  PostgreSQL      Keycloak           │         │  PostgreSQL      Keycloak           │
│                                     │         │                                     │
│  INDEPENDENT STATE                  │         │  INDEPENDENT STATE                  │
└─────────────────────────────────────┘         └─────────────────────────────────────┘
                    │                                           │
                    │                                           │
                    └────────────── A2A Protocol ───────────────┘
                           (HTTPS, mutual registration)
```

**Key Principles**:
1. **Complete Independence**: Each instance has own PostgreSQL, Redis, Keycloak, MCP servers
2. **Zero Shared State**: No shared infrastructure between instances
3. **A2A Protocol Only**: Single interaction mechanism for all inter-instance communication

### Use Cases

- **Research Collaboration**: University labs share compute resources across institutions
- **Multi-Cloud Deployments**: Distribute workloads between AWS, Azure, GCP, on-premises
- **Geographic Distribution**: Low-latency access via regional ADEPT instances
- **Specialized Capabilities**: Route tasks to instances with specific MCP tools or models
- **Disaster Recovery**: Peer failover and redundancy for critical workflows

### CLI Management Commands

After completing workshop setup, manage A2A peers with `agentic` CLI:

```bash
# List all registered peers
agentic a2a list-peers --format table

# Test connection to specific peer
agentic a2a test-connection aws-gateway --verbose

# Remove peer (with confirmation)
agentic a2a remove-peer aws-gateway

# Generate new A2A token
agentic a2a generate-token --groups gateway-service
```

### Documentation

**Workshop Guide**: `examples/a2a-workshop/README.md`
- Complete architecture overview
- Step-by-step setup instructions
- Troubleshooting common issues
- Advanced topics (multi-instance mesh, token rotation, monitoring)

**Related Documentation**:
- **Systems Administrator Onboarding**: `docs/SYSTEMS_ADMINISTRATOR_ONBOARDING.md`
  - Section: "A2A Gateway Mesh Management"
  - Section: "Accessing ADEPT via IP Address"
- **CLAUDE.md**: Project instructions and A2A credential management
- **Phase 2 Design**: `docs/implementation-plans/session-52/14_PHASE2_REVISED_INDEPENDENT_INSTANCES.md`
- **Phase 2 Proposal**: `docs/implementation-plans/session-52/15_PHASE2_IMPLEMENTATION_PROPOSAL.md`

### Troubleshooting

**Issue: "Connection refused" or "Connection timeout"**

```bash
# Check firewall rules between hosts
# AWS Security Group
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxxx \
  --protocol tcp \
  --port 443 \
  --cidr 10.0.0.2/32

# Azure NSG
az network nsg rule create \
  --resource-group <rg-name> \
  --nsg-name <nsg-name> \
  --name allow-adept-a2a \
  --protocol tcp \
  --priority 1000 \
  --destination-port-range 443 \
  --source-address-prefix 10.0.0.1/32

# Test connectivity manually
curl -k https://10.0.0.1/v1/models
```

**Issue: "401 Unauthorized" during registration**

```bash
# Check Gateway Registry credentials exist
ls -la deployment/local/docker-compose/.env-keycloak-credentials-dir/ | grep VALIDATION_RUNNER

# Regenerate if missing
make fix-credentials

# Verify container has access to credentials
docker exec gateway_registry env | grep VALIDATION_RUNNER
```

**Full Troubleshooting Guide**: See `examples/a2a-workshop/README.md` Section: "Troubleshooting"

### Status

**Session**: 52
**Date**: February 10, 2026
**Status**: ✅ Workshop Complete and Production Ready
**Test Coverage**: 15/15 E2E tests passing (100%)

**Phase 1**: ✅ Mutual registration and peer discovery
**Phase 2**: 🚧 Inter-instance task delegation (planned)

---

## Next Steps

1. **Run Examples**: Start with `langgraph_adept_quickstart.py`
2. **Create Custom Tools**: Use `examples/mcp_tools/` as a template
3. **Lab Automation**: Deploy Opentrons MCP Server (`cd examples/opentrons_mcp_server && make setup`)
4. **Federated Agents**: Deploy Academy MCP Server (`cd examples/academy_mcp_server && make setup`)
5. **EMSL Sandbox**: Deploy EMSL sandbox (`cd examples/emsl_sandbox && make build && make start`)
6. **AWS MCP Manager**: Deploy AWS MCP Server Manager (`cd examples/aws_mcp && make setup`) — meta-MCP for 62 AWS Labs servers
7. **Read Guide**: Review [LANGGRAPH_ADEPT_INTEGRATION_GUIDE.md](../docs/integration/LANGGRAPH_ADEPT_INTEGRATION_GUIDE.md)
8. **View Traces**: Open https://api.agentic.local/langfuse
9. **Customize**: Modify agent prompts and workflows for your use case
10. **Deploy**: Use patterns in production LangGraph applications

## Capability Diagrams

For visual architecture references, see the mermaid diagrams in [`docs/workshop/diagrams/`](../docs/workshop/diagrams/):

| Diagram | Capability |
|---------|-----------|
| `capability_kb_factory_lifecycle.mmd` | KB factory pattern (BackendFactory, IndexVisibility) |
| `capability_observability_pipeline.mmd` | Observability pipeline (ObservabilityFactory, Langfuse) |
| `capability_tool_lifecycle.mmd` | Tool discovery (built-in, external, A2A) |
| `capability_tool_execution_flow.mmd` | Tool execution through three-tier architecture |
| `capability_multi_agent_lifecycle.mmd` | Multi-agent workflow (RolePersona, session hierarchy) |
| `capability_a2a_federation_lifecycle.mmd` | A2A federation across cloud boundaries |
| `capability_identity_management.mmd` | Identity management (humans, services, SPIFFE roadmap) |

---

**Date**: March 11, 2026 (Updated Session 80)
**Status**: ✅ Production Ready
**Contact**: See [CLAUDE.md](../CLAUDE.md) for framework documentation
