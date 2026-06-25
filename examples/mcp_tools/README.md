# Example MCP Tools for Dynamic Registration

This directory contains example MCP tool servers demonstrating how to create and register external tools with the ADEPT framework.

## Overview

ADEPT supports dynamic tool registration, allowing you to extend the framework with custom external tools without modifying the core codebase. This is powerful for:

- **Domain-Specific Tools**: Add specialized tools for your industry (finance, healthcare, research)
- **Third-Party Integrations**: Connect to external APIs and services
- **Custom Workflows**: Implement business logic as reusable tools
- **Rapid Prototyping**: Test new tool ideas without framework changes

## Example Tools

### 1. Weather Service - stdio Transport (`example_weather_mcp_server.py`)

**Purpose**: Demonstrates MCP tool server with stdio transport (standard MCP pattern)

**Transport**: stdio (process-based communication)

**Tools Provided**:
- `get_weather(city, units)` - Get current weather for a city
- `get_forecast(city, days)` - Get weather forecast

**Use Case**: Local tool servers, containerized tools, simple integrations

**Registration**:
```bash
agentic tool register \
  --name weather_service \
  --type mcp \
  --url "stdio:python examples/mcp_tools/example_weather_mcp_server.py" \
  --description "Get weather data for any city"
```

### 2. Weather Service - HTTP Transport (`example_weather_http_server.py`)

**Purpose**: Demonstrates HTTP-based MCP server using FastAPI

**Transport**: HTTP (RESTful API)

**Tools Provided**:
- `get_weather(city, units)` - Get current weather for a city
- `get_forecast(city, days)` - Get weather forecast

**Use Case**: Remote tool servers, microservices, existing FastAPI apps

**Endpoints**:
- `GET /tools/list` - List available tools
- `POST /tools/call` - Execute a tool

**Registration**:
```bash
# Start server
python examples/mcp_tools/example_weather_http_server.py
# Or with uvicorn:
uvicorn examples.mcp_tools.example_weather_http_server:app --host 0.0.0.0 --port 8090

# Register with ADEPT
agentic tool register \
  --name weather_http \
  --type mcp \
  --url http://localhost:8090 \
  --description "HTTP-based weather service"
```

**Testing HTTP Endpoints**:
```bash
# List tools
curl http://localhost:8090/tools/list

# Call tool
curl -X POST http://localhost:8090/tools/call \
  -H "Content-Type: application/json" \
  -d '{"name": "get_weather", "arguments": {"city": "Paris"}}'
```

## Choosing Between stdio and HTTP

| Feature | stdio Transport | HTTP Transport |
|---------|----------------|----------------|
| **Setup Complexity** | Simple | Moderate |
| **Network Required** | No (local process) | Yes (TCP/IP) |
| **Concurrent Requests** | Single process | Multi-threaded |
| **Remote Access** | No | Yes |
| **Use Case** | Local tools, containers | Microservices, remote tools |
| **Example** | `example_weather_mcp_server.py` | `example_weather_http_server.py` |

**Recommendation**:
- Use **stdio** for simple local tools and containerized services
- Use **HTTP** for remote tools, microservices, or existing web apps

## Quick Start

### 🔐 Security Note: Authentication for Tool Registration

**IMPORTANT**: These examples use service tokens for demonstration. In production:

**For Human Users (Recommended)**:
```bash
# Use Keycloak JWT authentication (supports MFA)
agentic auth login  # Opens browser for Keycloak login
# JWT token stored in ~/.agentic/auth_token
# All tool operations use your user identity
```

**For Services/Automation**:
```bash
# Use service tokens from secrets manager
export ADEPT_API_KEY=$(aws secretsmanager get-secret-value \
  --secret-id adept/service-tokens/ci-pipeline \
  --query SecretString --output text)
```

**Why This Matters**:
- ✅ Zero-trust: Every request validates authentication
- ✅ User attribution: Operations logged with actual username
- ✅ MFA support: Keycloak supports TOTP, WebAuthn, SMS
- ✅ Group-based ACLs: Tool access based on user groups
- ❌ Never share service tokens across users/teams

**Documentation**: See [docs/security/MCP_TOOL_REGISTRATION_AUTHENTICATION.md](../../docs/security/MCP_TOOL_REGISTRATION_AUTHENTICATION.md) for complete security architecture.

### Prerequisites

```bash
# Install MCP package
pip install mcp httpx

# Ensure ADEPT services are running
make start
```

### Step 1: Start the MCP Server

```bash
# Run the weather server
python examples/mcp_tools/example_weather_mcp_server.py

# Output:
# ================================================================================
# Example Weather MCP Server
# ================================================================================
#
# Server Status: STARTING
# Protocol: MCP (Model Context Protocol)
# Transport: stdio
#
# Available Tools:
#   - get_weather(city, units='celsius')
#   - get_forecast(city, days=5)
#
# Server Status: READY (listening for MCP messages)
# ================================================================================
```

### Step 2: Register with ADEPT

**Option A: Via Python SDK** (Recommended)

```python
from agentic_framework_sdk import OpenAI

# Initialize SDK client
client = OpenAI(
    base_url="https://api.agentic.local",
    api_key="your_api_key"  # Or use JWT token
)

# Register the weather service
tool_config = {
    "name": "weather_service",
    "type": "mcp",
    "url": "stdio:python examples/mcp_tools/example_weather_mcp_server.py",
    "description": "Get weather data for any city",
    "acl_groups": ["notebook-users", "scientists"]
}

response = client.agentic.tools.register(tool_config)
print(f"Tool registered: {response}")

# List registered tools
tools = client.agentic.tools.list()
print(f"Available tools: {tools}")
```

**Option B: Via CLI** (Coming Soon)

```bash
# Future CLI command (SDK already supports, CLI wrapper pending)
agentic tools list  # Currently lists tools

# Tool registration CLI command to be added:
# agentic tools register \
#   --name weather_service \
#   --type mcp \
#   --url "stdio:python examples/mcp_tools/example_weather_mcp_server.py" \
#   --description "Get weather data for any city" \
#   --groups notebook-users,scientists
```

**Note**: The `agentic tools list` command already exists in the CLI (`src/agentic_framework_sdk/cli/main.py:1538`). Tool registration via CLI can be added using the existing SDK `client.agentic.tools.register()` method.

### Step 3: Register with ADEPT (API Method)

```bash
# Get service token or user JWT
export ADEPT_TOKEN=$(grep OPENWEBUI_SERVICE_API_KEY \
  deployment/local/docker-compose/.env-keycloak-credentials-dir/.env-keycloak-credentials \
  | cut -d'=' -f2)

# Register via REST API
curl -k -X POST https://api.agentic.local/admin/tools \
  -H "Authorization: Bearer $ADEPT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "weather_service",
    "type": "mcp",
    "url": "stdio:python examples/mcp_tools/example_weather_mcp_server.py",
    "description": "Get weather data for any city",
    "acl_groups": ["notebook-users", "scientists"]
  }'

# Verify registration
curl -k -X GET https://api.agentic.local/admin/tools \
  -H "Authorization: Bearer $ADEPT_TOKEN"
```

### Step 4: Use in Agent Workflows

Once registered, the weather tools are automatically available to agents:

```python
from openai import OpenAI

# Create OpenAI client pointing to ADEPT
client = OpenAI(
    base_url="https://api.agentic.local/v1",
    api_key=f"Bearer {token}"
)

# Agent will automatically discover and use weather tools
response = client.chat.completions.create(
    model="agentic-framework:scientific-agent-v1",
    messages=[
        {"role": "user", "content": "What's the weather in Paris and Tokyo?"}
    ]
)

# Agent response will include tool calls to get_weather:
# "The weather in Paris is 18°C and partly cloudy.
#  In Tokyo, it's 25°C and clear."
```

## Creating Your Own MCP Tool

### Template Structure

```python
#!/usr/bin/env python3
"""
My Custom MCP Tool Server
=========================

Description of what your tool does.
"""

from mcp import Mcpython3
from mcp.server.stdio import stdio_server

# Initialize MCP server
mcp = Mcpython3("my-tool-server", "1.0.0")


@mcp.tool()
async def my_custom_function(param1: str, param2: int = 10) -> dict:
    """
    Description of what this function does.

    Args:
        param1: Description of parameter 1
        param2: Description of parameter 2 (default: 10)

    Returns:
        Dictionary with results
    """
    # Your implementation here
    result = {"output": f"Processed {param1} with {param2}"}
    return result


async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await mcp.run(
            read_stream,
            write_stream,
            mcp.create_initialization_options()
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

### Best Practices

1. **Clear Documentation**: Write detailed docstrings for each tool
2. **Type Hints**: Use Python type hints for all parameters
3. **Error Handling**: Return structured error responses
4. **Validation**: Validate inputs before processing
5. **Logging**: Use structured logging for debugging
6. **Idempotency**: Make tools idempotent where possible
7. **Security**: Validate and sanitize all inputs

### Common Patterns

**Pattern 1: API Wrapper**
```python
@mcp.tool()
async def fetch_api_data(endpoint: str) -> dict:
    """Wrap external API calls."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"https://api.example.com/{endpoint}")
        return response.json()
```

**Pattern 2: Database Query**
```python
@mcp.tool()
async def query_database(sql: str) -> list:
    """Execute read-only database queries."""
    # Implement with proper SQL injection protection
    pass
```

**Pattern 3: File Processing**
```python
@mcp.tool()
async def process_file(file_path: str, operation: str) -> dict:
    """Process files with various operations."""
    # Implement with proper path validation
    pass
```

## Session Stability Across Forks (Session 57)

MCP tools automatically receive session context via closure binding at tool instantiation time. Fork resolution (internal to the orchestration layer) is transparent to tools:

- Tools receive `original_session_id` (stable, pre-fork) via `MCPToolWrapper.__init__`
- File paths use `mcp_session_id` (immutable across any number of forks)
- The LLM cannot override session context — it's injected by the framework

**What this means for custom tool authors**: Always use `mcp_session_id` from `user_context` for file storage, Redis keys, and resource scoping. Never derive session directories from `session_id` or `thread_id` — those may follow fork chains and change across context compactions.

```python
@mcp.tool()
async def my_tool(query: str, user_context: Dict) -> dict:
    # ✅ CORRECT: Use mcp_session_id (stable across forks)
    mcp_session_id = user_context.get("mcp_session_id")
    session_dir = f"/data/uploaded_files/{mcp_session_id}/"

    # ❌ INCORRECT: session_id may follow fork chain (volatile)
    # session_id = user_context.get("session_id")  # Don't use for file paths
```

For full architecture details, see [Session Lineage Isolation](../../docs/architecture/SESSION_LINEAGE_ISOLATION_ARCHITECTURE.md).

## Tool Discovery

ADEPT automatically discovers tools from registered MCP servers:

1. **Registration**: Tool server is registered via CLI or API
2. **Discovery**: ADEPT calls `tools/list` on the MCP server
3. **Schema Extraction**: Tool parameters and descriptions are extracted
4. **Authorization**: Tools are filtered by user's ACL groups
5. **Runtime**: Agent can call tools based on user permissions

## Debugging

### Test Tool Directly

```bash
# Test tool via MCP protocol
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | \
  python examples/mcp_tools/example_weather_mcp_server.py

# Expected: List of available tools with schemas
```

### Check Tool Registration

```bash
# View registered tools in Redis
docker exec -it redis redis-cli KEYS "tool_config:*"

# View specific tool config
docker exec -it redis redis-cli GET "tool_config:weather_service"
```

### Enable Debug Logging

```python
# In your MCP server
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Troubleshooting

### Tool Not Showing Up

**Symptoms**: Tool registered but agent doesn't use it

**Solutions**:
1. Check ACL groups match user's groups
2. Verify tool server is running
3. Check tool discovery logs:
   ```bash
   docker logs orchestration_service | grep -i "tool discovery"
   ```

### Permission Denied

**Symptoms**: Tool call fails with 403 Forbidden

**Solutions**:
1. Verify user's groups in JWT token
2. Update tool ACL groups:
   ```bash
   agentic tool update weather_service --add-groups scientists
   ```

### Tool Execution Errors

**Symptoms**: Tool returns error messages

**Solutions**:
1. Check tool server logs
2. Validate input parameters
3. Test tool directly (see Debugging section)

## Advanced Topics

### HTTP MCP Servers

While this example uses stdio transport, you can also create HTTP-based MCP servers:

```python
from mcp.server.fastapi import create_app

app = create_app()

@app.tool()
async def http_tool():
    """Tool served over HTTP."""
    pass

# Run with: uvicorn my_server:app --port 8090
```

Then register with HTTP URL:
```bash
agentic tool register \
  --name http_service \
  --type mcp \
  --url http://localhost:8090 \
  --description "HTTP-based MCP service"
```

### Tool Composition

Tools can call other tools for complex workflows:

```python
@mcp.tool()
async def weather_report(cities: list[str]) -> dict:
    """Generate comprehensive weather report for multiple cities."""
    reports = []
    for city in cities:
        weather = await get_weather(city)
        forecast = await get_forecast(city, days=3)
        reports.append({"city": city, "weather": weather, "forecast": forecast})
    return {"reports": reports}
```

### Stateful Tools

Use context managers for stateful operations:

```python
class DatabaseConnection:
    async def __aenter__(self):
        self.conn = await create_connection()
        return self

    async def __aexit__(self, *args):
        await self.conn.close()

@mcp.tool()
async def query_with_context(query: str) -> dict:
    """Execute query with managed connection."""
    async with DatabaseConnection() as db:
        result = await db.execute(query)
        return result
```

## Resources

- **MCP Documentation**: https://modelcontextprotocol.io
- **ADEPT Tool API**: `docs/api/TOOL_REGISTRATION.md`
- **Dynamic Tool Management**: CLAUDE.md (search for "Dynamic Tool Management")
- **ACL Documentation**: `docs/security/TOOL_ACL_ARCHITECTURE.md`

## Next Steps

1. **Customize Weather Tool**: Integrate real weather API (OpenWeatherMap, WeatherAPI)
2. **Create Domain Tool**: Build a tool specific to your use case
3. **Share Tools**: Package and share your tools with the community
4. **Contribute**: Submit useful tools as examples via pull request

---

**Date**: 2026-02-14
**Session**: 57 (Session Lineage Isolation update)
**Status**: ✅ Production Ready
