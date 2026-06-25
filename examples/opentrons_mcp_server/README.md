# Opentrons MCP Server

MCP server providing Opentrons liquid handling protocol execution for the ADEPT framework.

## Overview

This MCP server enables AI agents to execute liquid handling protocols on Opentrons robots through natural language interfaces. It supports both simulation mode (for testing) and real hardware mode (for production lab automation).

## Features

- **Protocol Validation**: JSON Schema-based validation with safety rules
- **Simulation Mode**: Test protocols without hardware
- **Real Hardware Support**: Execute on Opentrons OT-2 robots (requires opentrons Python API)
- **Session Isolation**: Multi-tier session ID support
- **Safety Controls**: Volume limits, well coordinate validation, tip type matching
- **MCP Protocol**: FastMCP integration with ADEPT framework

## Installation

### Docker (Recommended)

```bash
docker build -t opentrons-mcp-server .
docker run -p 9003:9003 -e OPENTRONS_HARDWARE_MODE=simulation opentrons-mcp-server
```

### Makefile (Recommended for ADEPT Integration)

```bash
# From this directory — full lifecycle (build + start + register with ADEPT + verify)
make setup

# Rebuild after code changes
make rebuild

# Stop and deregister
make teardown

# Individual targets
make build            # Build Docker image
make start            # Start container
make register-tool    # Register MCP tool with ADEPT via agentic CLI
make deregister-tool  # Remove tool from ADEPT
make verify-tool      # Verify tool in Redis and Gateway API
make health           # Check /health endpoint
make smoke-test       # E2E test via Response API
make logs             # Tail container logs
make help             # Show all available targets
```

**From project root**:
```bash
make opentrons-setup        # Delegates to this Makefile
make opentrons-rebuild
make opentrons-teardown
make opentrons-health
make opentrons-smoke-test
```

**Prerequisites**: ADEPT core stack running (`make start` from project root) and `agentic` CLI installed (`pip install -e src/`).

### Local Development

```bash
pip install -r requirements.txt
export OPENTRONS_HARDWARE_MODE=simulation
export MCP_SERVER_PORT=9003
python -m examples.opentrons_mcp_server.main
```

## Configuration

Environment variables:

- `OPENTRONS_HARDWARE_MODE`: `simulation` (default) or `real`
- `MCP_SERVER_PORT`: Server port (default: 9003)

## Protocol Format

```json
{
  "protocol_name": "Sample Transfer",
  "protocol_version": "1.0",
  "plate_type": "96-well",
  "transfers": [
    {
      "source_well": "A1",
      "dest_well": "B1",
      "volume_ul": 50.0,
      "tip_type": "p300_single"
    }
  ]
}
```

### Valid Well Coordinates

- **96-well plate**: A1-H12 (8 rows × 12 columns)
- **384-well plate**: A1-P24 (16 rows × 24 columns)

### Valid Tip Types

- `p10_single`: 0.5-10 μL
- `p20_single`: 1-20 μL
- `p300_single`: 20-300 μL
- `p1000_single`: 100-1000 μL

### Safety Limits

- Maximum volume per well: 300 μL (96-well), 100 μL (384-well)
- Maximum volume per transfer: 1000 μL
- Tip type must match transfer volume

## API Endpoints

### Health Check
```
GET /health
```

Returns server status and hardware mode.

### MCP Tools

#### execute_opentrons_protocol

Execute a liquid handling protocol.

**Parameters**:
- `protocol_json` (dict): Protocol specification
- `dry_run` (bool): If True, validates only (default: True)
- `mcp_session_id` (str): Session ID for isolation

**Returns**:
```json
{
  "status": "success",
  "protocol_name": "Sample Transfer",
  "transfer_count": 3,
  "execution_log": [...],
  "dry_run": false,
  "session_id": "session-123",
  "hardware_mode": "simulation"
}
```

## Usage with ADEPT

### Tool Registration

The tool must be registered with ADEPT's dynamic tool management before agents can invoke it:

```bash
# Automated (recommended)
make register-tool    # From this directory
make opentrons-register  # From project root

# Manual
agentic tools register execute_opentrons_protocol \
  -d "Execute an OpenTrons OT-2 liquid handling protocol" \
  -p mcp -u http://opentrons_mcp_server:9003/mcp \
  --tool-name execute_opentrons_protocol_tool \
  --args-schema '{"protocol_json":{"type":"object","description":"Protocol spec"},"dry_run":{"type":"boolean","description":"Validate without executing","default":true}}' \
  --username admin --password admin
```

The tool uses **MCP protocol** (not HTTP) — the FastMCP Client handles the JSON-RPC handshake (initialize → tools/call → result). The URL must include the `/mcp` path.

### Natural Language Interface

```
User: "Execute an Opentrons protocol to transfer 50μL from A1 to B1"
Agent: [calls execute_opentrons_protocol tool]
Agent: "Protocol validated successfully. 1 transfer scheduled. Use dry_run=False to execute."
```

### Multi-Agent Delegation (A2A)

Gateway B delegates Opentrons protocol execution to Gateway C:

```python
# Gateway B agent
delegate_task_to_gateway(
    task="Execute Opentrons transfer protocol",
    target_gateway="gateway-c",
    protocol_json={...}
)
```

## Security

- **ACL Groups**: Only users in `lab-users` or `scientists` groups can execute protocols
- **Dry-run Default**: Hardware execution requires explicit `dry_run=False`
- **Schema Validation**: All protocols validated against JSON Schema
- **Safety Rules**: Volume limits and well coordinate validation
- **Session Isolation**: Each protocol execution isolated by session ID

## Testing

```bash
# Unit tests
pytest tests/unit/opentrons_mcp_server/

# Integration tests
pytest tests/e2e/test_a2a_opentrons_scenario.py

# Makefile targets
make health           # Server health check
make smoke-test       # E2E via Response API (requires ADEPT stack)
make verify-tool      # Verify registration in Redis + Gateway API
```

## Roadmap

- [ ] Real Opentrons OT-2 hardware integration
- [x] 384-well plate support
- [ ] Multi-channel pipette support
- [ ] Protocol library with common workflows
- [ ] Real-time progress streaming
- [ ] Error recovery and retry logic
- [x] Audit logging for protocol execution (structured [TOOL_CALL]/[TOOL_RESULT]/[TOOL_ERROR] logging)

## License

MIT License - See LICENSE file for details
