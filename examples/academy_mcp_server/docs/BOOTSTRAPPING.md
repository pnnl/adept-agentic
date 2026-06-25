# Academy MCP Server — Bootstrapping Guide

## Prerequisites

1. ADEPT core stack running (`make start` from project root)
2. `adept_application_network` Docker network exists
3. `agentic` CLI installed (`pip install -e src/` from project root)

## Quick Start

```bash
cd examples/academy_mcp_server

# Full lifecycle: build, start, register tools, verify
make setup

# Check health
curl http://localhost:9004/health
```

## Manual Steps

```bash
# 1. Build and start the 3-service stack (Redis + MCP + Nginx)
make build
make start

# 2. Wait for health
make wait-healthy

# 3. Register tools with ADEPT gateway
make register-tools

# 4. Verify tools in Redis
make verify-tools
```

## Podman Mode

```bash
ENGINE=podman make setup
```

## Tool Registration

Tools are auto-discovered from `tools/agent_lifecycle.py` via the Python
registration script (`scripts/register_academy_tools.py`). No hardcoded
schemas to maintain.

```bash
# Show discovered schemas
make show-schemas

# Register / deregister / verify
make register-tools
make deregister-tools
make verify-tools
```

## Teardown

```bash
make teardown   # Deregister tools + stop containers
```

## Configuration

Copy `.env.example` to `.env` to customise settings. Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `ACADEMY_PORT` | 9004 | MCP server port |
| `ACADEMY_REDIS_URL` | redis://academy_redis:6379/0 | Redis connection |
| `ACADEMY_LOG_LEVEL` | INFO | Log verbosity |
| `ENGINE` | docker | Container engine (docker/podman) |
| `ADMIN_USER` | admin | ADEPT admin for tool registration |
| `ADMIN_PASS` | admin | ADEPT admin password |

## Architecture

```
academy_redis (Redis 7)
  ↓ depends_on
academy_mcp_server (FastMCP + FastAPI on port 9004)
  ↓ depends_on
academy_nginx_proxy (Nginx reverse proxy, ports 9020/9021)
```

All three services join `adept_application_network` for orchestration
service discovery.
