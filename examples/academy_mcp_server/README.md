# Academy MCP Server

MCP server that exposes [Academy](https://github.com/agentos-project/academy) federated agent lifecycle operations as ADEPT-compatible tools. Follows the same integration pattern as the [OpenTrons MCP Server](../opentrons_mcp_server/).

## Overview

Academy is a federated agent middleware for distributed scientific workflows (Slurm, sensors, Globus). This server wraps Academy's Manager/Handle API into 4 MCP tools that ADEPT's ScientificWorkflowAgent can invoke via natural language.

## MCP Tools

| Tool | Description |
|------|-------------|
| `launch_academy_agent` | Launch an echo, counter, or compute agent |
| `invoke_agent_action` | Invoke an action on a running agent |
| `list_academy_agents` | List all agents in the current session |
| `shutdown_academy_agent` | Shut down a running agent |

## Agent Templates

| Agent | Actions | Purpose |
|-------|---------|---------|
| `EchoAgent` | `echo(message)`, `get_call_count()` | Integration testing |
| `CounterAgent` | `increment(value)`, `decrement(value)`, `get_count()`, `reset()` | Stateful demo |
| `ComputeAgent` | `factorial(n)`, `fibonacci(n)`, `is_prime(n)`, `get_computation_count()` | Scientific demo |

## Quick Start

```bash
# Prerequisites: ADEPT core stack running
make start  # from project root

# Setup (build, start, register tools)
cd examples/academy_mcp_server
make setup
```

## Usage

### Health Check

```bash
curl http://localhost:9004/health
```

### Verify Tools in Redis

```bash
docker exec redis redis-cli GET "external_tool:launch_academy_agent"
docker exec redis redis-cli GET "external_tool:invoke_agent_action"
docker exec redis redis-cli GET "external_tool:list_academy_agents"
docker exec redis redis-cli GET "external_tool:shutdown_academy_agent"
```

### Direct Tool Test (inside container)

```bash
docker exec academy_mcp_server /app/.venv/bin/python -c "
import asyncio
from academy_mcp_server.tools.agent_lifecycle import (
    launch_academy_agent, invoke_agent_action,
    list_academy_agents, shutdown_academy_agent
)

async def test():
    r = await launch_academy_agent('echo', {}, 'test-1')
    assert r['status'] == 'running', r
    aid = r['agent_id']

    r = await invoke_agent_action(aid, 'echo', {'message': 'hello'}, 30, 'test-1')
    assert r['result']['echo'] == 'hello', r

    r = await list_academy_agents('test-1')
    assert r['count'] == 1, r

    r = await shutdown_academy_agent(aid, True, 'test-1')
    assert r['status'] == 'shutdown', r
    print('All tests passed')

asyncio.run(test())
"
```

### Natural Language (via ADEPT)

Once tools are registered, use natural language with ADEPT:

> "Launch an echo agent and send it the message 'Hello Academy'"

> "Launch a compute agent, calculate factorial of 10, then shut it down"

> "Create a counter agent starting at 100, increment by 5 three times, then tell me the count"

## Makefile Targets

| Target | Description |
|--------|-------------|
| `make setup` | Full lifecycle: build, start, register, verify |
| `make rebuild` | Rebuild from scratch and re-register |
| `make teardown` | Stop and deregister |
| `make build` | Build Docker image |
| `make start` | Start container |
| `make stop` | Stop container |
| `make register-tools` | Register 4 tools via agentic CLI |
| `make deregister-tools` | Remove 4 tools from ADEPT |
| `make verify-tools` | Verify tools in Redis |
| `make health` | Check health endpoint |
| `make smoke-test` | E2E smoke test via Response API |
| `make test-infrastructure-health` | Redis isolation + tool visibility (dual-network) |
| `make logs` | Tail container logs |

## Architecture

```
┌──────────────────────────┐
│  ADEPT Orchestration     │
│  (ScientificWorkflowAgent)│
│                          │
│  Discovers tools via     │
│  Redis external_tool:*   │
└──────────┬───────────────┘
           │ MCP JSON-RPC
           ▼
┌──────────────────────────┐
│  Academy MCP Server      │
│  (FastAPI + FastMCP)     │
│  Port 9004               │
│                          │
│  4 @mcp.tool() endpoints │
└──────────┬───────────────┘
           │ Academy API
           ▼
┌──────────────────────────┐
│  AcademyManagerRegistry  │
│  (Session-scoped)        │
│                          │
│  Manager per session     │
│  LocalExchangeFactory    │
│  Handle per agent        │
└──────────────────────────┘
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_SERVER_PORT` | `9004` | Server port |
| `ADMIN_USER` | `admin` | ADEPT admin username |
| `ADMIN_PASS` | `admin` | ADEPT admin password |
| `KEYCLOAK_URL` | `http://localhost:8180` | Keycloak URL |
| `GATEWAY_URL` | `http://localhost:8083` | Agent Gateway URL |

## Phase 2 (Future)

- Redis exchange backend for distributed coordination
- Globus Auth integration
- HPC agent templates (Slurm, PBS)
- TTL-based session auto-cleanup
- Agent-to-ADEPT tool bridging
