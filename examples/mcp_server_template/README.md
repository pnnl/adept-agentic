# {{DISPLAY_NAME}}

A Model Context Protocol (MCP) server providing {{DESCRIPTION}} tools for the ADEPT agentic framework.

## Description

This MCP server exposes {{TOOL_COUNT}} tools for {{DOMAIN}} operations:

1. **{{NAME}}_example_tool** - Example tool demonstrating MCP integration pattern
2. **{{NAME}}_get_job_status** - Retrieve status of asynchronous processing jobs

The server follows ADEPT's 3-tier architecture:
- **Tier 1**: ADEPT Agent Gateway (JWT authentication, CORS, proxying)
- **Tier 2**: ADEPT Orchestration Service (workflow management, tool invocation)
- **Tier 3**: This MCP Server (stateless tool execution)

## Prerequisites

- Docker and docker-compose
- Python 3.11+ (for local development)
- Access to ADEPT Redis instance (for tool registration)
- (Optional) GPU with CUDA support for accelerated processing

## Quick Start

### 1. Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit configuration (optional, defaults work for local development)
vim .env
```

### 2. Start Services

```bash
# Build and start all services
docker compose up -d

# Check status
docker compose ps

# View logs
docker compose logs -f {{NAME}}_mcp_server
```

### 3. Verify Deployment

```bash
# Test MCP server health
curl http://localhost:{{MCP_PORT}}/health

# Expected response:
# {
#   "status": "healthy",
#   "mcp_tools": ["{{NAME}}_example_tool", "{{NAME}}_get_job_status"],
#   "version": "0.1.0"
# }
```

### 4. Register Tools with ADEPT

```bash
# Register tools in ADEPT Redis
python scripts/register_{{NAME}}_tools.py --register

# Verify registration
docker exec {{NAME}}_redis redis-cli KEYS "tool:{{NAME}}_*"

# Expected output:
# 1) "tool:{{NAME}}_example_tool"
# 2) "tool:{{NAME}}_get_job_status"
```

## Tool Descriptions

### {{NAME}}_example_tool

**Description**: Process input file with configurable model and batch size.

**Parameters**:
- `input_file` (string, required): Path to input file or file ID
- `model` (string, optional): Model name to use (default: "default")
- `batch_size` (integer, optional): Processing batch size (default: 16)

**Example Usage** (via ADEPT CLI):
```bash
afk chat "Use {{NAME}}_example_tool to process data.csv with batch_size=32"
```

**Example Usage** (direct MCP call):
```bash
curl -X POST http://localhost:{{MCP_PORT}}/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "{{NAME}}_example_tool",
      "arguments": {
        "input_file": "data.csv",
        "model": "custom_model",
        "batch_size": 32
      }
    }
  }'
```

---

### {{NAME}}_get_job_status

**Description**: Retrieve status and results of asynchronous processing jobs.

**Parameters**:
- `job_id` (string, required): Job identifier returned by example_tool

**Example Usage**:
```bash
afk chat "What is the status of job abc123?"
```

---

## Makefile Targets

| Target | Description |
|--------|-------------|
| `make build` | Build Docker images |
| `make up` | Start all services |
| `make down` | Stop all services |
| `make logs` | Follow all service logs |
| `make logs-mcp` | Follow MCP server logs only |
| `make restart` | Restart all services |
| `make rebuild` | Full rebuild (down + build + up) |
| `make test-unit` | Run Tier 1 unit tests (offline) |
| `make test-integration` | Run Tier 2 integration tests |
| `make test-registration` | Run Tier 3 registration tests |
| `make test-all` | Run all test tiers sequentially |
| `make test-clean` | Remove test artifacts and logs |
| `make register-tools` | Register tools with ADEPT Redis |
| `make delete-tools` | Delete tools from ADEPT Redis |
| `make shell-mcp` | Open bash shell in MCP server container |
| `make shell-redis` | Open redis-cli in Redis container |

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     ADEPT Tier 1 & 2                          │
│  ┌────────────────┐         ┌────────────────────────┐       │
│  │ Agent Gateway  │────────▶│ Orchestration Service  │       │
│  │  (Auth/CORS)   │         │  (Workflow Manager)    │       │
│  └────────────────┘         └───────────┬────────────┘       │
└──────────────────────────────────────────┼───────────────────┘
                                           │ MCP JSON-RPC
                                           ▼
┌──────────────────────────────────────────────────────────────┐
│              {{DISPLAY_NAME}} (Tier 3)                        │
│  ┌─────────────────────────────────────────────────────┐     │
│  │             Nginx Proxy (Port 80)                   │     │
│  │  ┌──────────────────────────────────────────────┐   │     │
│  │  │    FastMCP Server (Port {{MCP_PORT}})        │   │     │
│  │  │  ┌────────────────┐  ┌──────────────────┐   │   │     │
│  │  │  │ Example Tool   │  │ Get Job Status  │   │   │     │
│  │  │  └────────────────┘  └──────────────────┘   │   │     │
│  │  └──────────────────────────────────────────────┘   │     │
│  └─────────────────────────────────────────────────────┘     │
│                                                               │
│  ┌─────────────────┐         ┌──────────────────┐            │
│  │  Redis (6379)   │         │  Data Volumes    │            │
│  │  (Job State)    │         │  (Input/Output)  │            │
│  └─────────────────┘         └──────────────────┘            │
└──────────────────────────────────────────────────────────────┘
```

### Network Topology

- **{{NAME}}_network**: Internal container communication
- **Host Ports**:
  - `80` → nginx_proxy (HTTP)
  - `{{MCP_PORT}}` → MCP server (direct access, bypasses proxy)
  - `6379` → Redis (tool state)

### Data Flow

1. **Tool Invocation**: Orchestration Service → MCP JSON-RPC → FastMCP Server
2. **Job Creation**: Tool creates job, stores state in Redis
3. **Job Polling**: Client calls `get_job_status` to check progress
4. **Result Retrieval**: Tool returns result when job completes

## Testing

This project follows a 4-tier testing strategy. See [tests/TESTING.md](tests/TESTING.md) for detailed information.

**Quick Test Commands**:
```bash
# Tier 1: Unit tests (no Docker needed)
make test-unit

# Tier 2: Integration tests (requires running containers)
make test-integration

# Tier 3: Registration tests (requires Redis)
make test-registration

# All tests
make test-all
```

## Configuration

All configuration is managed via environment variables with the `{{NAME_UPPER}}_` prefix. See [.env.example](.env.example) for complete reference.

**Key Variables**:
- `{{NAME_UPPER}}_PORT`: MCP server listen port (default: {{MCP_PORT}})
- `{{NAME_UPPER}}_REDIS_URL`: Redis connection URL
- `{{NAME_UPPER}}_DEVICE`: Processing device (cpu/cuda)
- `{{NAME_UPPER}}_RESULTS_DIR`: Output directory for results

## Development

### Project Structure

```
{{NAME}}_mcp/
├── __init__.py           # Package version
├── app.py                # FastAPI/FastMCP application
├── server.py             # MCP instance and tool registration
├── config.py             # Pydantic settings
└── tools/                # Tool implementations
    ├── __init__.py
    ├── example_tool.py
    └── get_job_status.py

tests/                    # 4-tier test suite
├── conftest.py           # Shared fixtures
├── test_imports.py       # Tier 1: Import validation
├── test_config.py        # Tier 1: Configuration
├── test_schema_discovery.py  # Tier 1: Schema extraction
├── test_{{NAME}}_deployment.py  # Tier 2: Integration
└── test_tool_registration.py  # Tier 3: Registration

scripts/
└── register_{{NAME}}_tools.py  # Tool registration CLI

docker-compose.yaml       # Service definitions
Dockerfile                # MCP server image
.env.example              # Configuration template
Makefile                  # Development shortcuts
```

### Adding New Tools

1. Create tool file in `{{NAME}}_mcp/tools/my_new_tool.py`
2. Define Pydantic input model with Field annotations
3. Decorate function with `@mcp.tool()`
4. Import tool in `{{NAME}}_mcp/server.py`
5. Update `TOOL_COUNT` in tests
6. Register with `make register-tools`

**Example**:
```python
# {{NAME}}_mcp/tools/my_new_tool.py
from pydantic import BaseModel, Field
from ..server import mcp

class MyNewToolInput(BaseModel):
    param1: str = Field(..., description="Required parameter")
    param2: int = Field(default=10, description="Optional parameter")
    mcp_session_id: str = Field(default="", exclude=True)

@mcp.tool()
async def my_new_tool(param1: str, param2: int = 10, **kwargs) -> dict:
    """Brief description of what this tool does."""
    session_id = kwargs.get("mcp_session_id", "unknown")
    # Implementation here
    return {"success": True, "result": "..."}
```

### Running Tests Locally

```bash
# Install dev dependencies
pip install -r requirements.txt
pip install pytest pytest-asyncio

# Run unit tests
export PYTHONPATH="${PWD}:${PYTHONPATH}"
pytest tests/test_imports.py tests/test_config.py -v

# Run with coverage
pytest tests/ --cov={{NAME}}_mcp --cov-report=html
open htmlcov/index.html
```

## Deployment

### Docker Compose (Local/Development)

See [Quick Start](#quick-start) section above.

### Kubernetes (Production)

```bash
# Build and push image
docker build -t your-registry.io/{{NAME}}-mcp:v0.1.0 .
docker push your-registry.io/{{NAME}}-mcp:v0.1.0

# Deploy to cluster
kubectl apply -f k8s/

# Check status
kubectl get pods -l app={{NAME}}-mcp-server
kubectl logs -l app={{NAME}}-mcp-server -f
```

## Troubleshooting

### MCP Server Won't Start

```bash
# Check logs
docker compose logs {{NAME}}_mcp_server

# Common issues:
# 1. Port conflict - change {{NAME_UPPER}}_PORT in .env
# 2. Missing data directories - create data/{input,output,results,models}
# 3. Redis unreachable - check {{NAME_UPPER}}_REDIS_URL
```

### Tools Not Appearing in ADEPT

```bash
# Verify MCP server health
curl http://localhost:{{MCP_PORT}}/health

# Check tools/list endpoint
curl -X POST http://localhost:{{MCP_PORT}}/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'

# Re-register tools
python scripts/register_{{NAME}}_tools.py --delete
python scripts/register_{{NAME}}_tools.py --register
```

### Tests Fail with "Connection Refused"

```bash
# Ensure containers are running
docker compose ps

# Check network connectivity
docker exec {{NAME}}-mcp-test-runner curl http://{{NAME}}_mcp_server:{{MCP_PORT}}/health
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-new-tool`)
3. Add tests for your changes
4. Ensure all tests pass (`make test-all`)
5. Commit your changes (`git commit -am 'Add my new tool'`)
6. Push to the branch (`git push origin feature/my-new-tool`)
7. Create a Pull Request

## License

[Add your license here]

## Links

- **ADEPT Framework**: [../../README.md](../../README.md)
- **Stack Parity Analysis**: [../docs/MCP_SERVER_STACK_PARITY_ANALYSIS.md](../docs/MCP_SERVER_STACK_PARITY_ANALYSIS.md) — Cross-stack comparison of all MCP server deployments (shared plumbing vs domain-specific deltas)
- **Testing Guide**: [tests/TESTING.md](tests/TESTING.md)
- **Quickstart Guide**: [QUICKSTART.md](QUICKSTART.md)
- **MCP Protocol**: https://modelcontextprotocol.io/docs
- **FastMCP**: https://github.com/jlowin/fastmcp
