# Testing Strategy for {{DISPLAY_NAME}} MCP Server

## 4-Tier Test Architecture

This project follows a systematic 4-tier testing approach to ensure reliability at every level of the stack.

### Tier 1: Offline/Unit Tests (No Containers Required)

**Purpose**: Validate imports, configuration, schema extraction, and basic logic without Docker.

**Files**:
- `test_imports.py` - Module import validation
- `test_config.py` - Pydantic settings and env var binding
- `test_schema_discovery.py` - Tool schema extraction from Field annotations

**Run Commands**:
```bash
# Run all Tier 1 tests
make test-unit

# Or directly with pytest (no Docker needed)
pytest tests/test_imports.py tests/test_config.py tests/test_schema_discovery.py -v

# Run with coverage
pytest tests/ -v --cov={{NAME}}_mcp --cov-report=term-missing
```

**Expected Results**:
- All imports succeed
- Settings load with correct defaults
- Tool schemas contain expected parameters (input_file, model, batch_size)
- Framework fields (mcp_session_id, session_id, user_context) stripped from schemas
- {{TOOL_COUNT}} tools discovered

---

### Tier 2: Integration Tests (Requires Running Containers)

**Purpose**: Validate that the MCP server and nginx proxy are deployed, healthy, and responding correctly.

**Files**:
- `test_{{NAME}}_deployment.py` - Container health and endpoint validation

**Prerequisites**:
```bash
# Start the stack
docker compose up -d

# Verify containers are running
docker ps | grep {{NAME}}
```

**Run Commands**:
```bash
# Run all Tier 2 tests
make test-integration

# Or with nohup for background execution
nohup make test-integration > logs/test_integration_$(date +%Y%m%d_%H%M%S).log 2>&1 &

# Monitor progress
tail -f logs/test_integration_*.log
```

**Expected Results**:
- MCP server `/` endpoint returns `{"status": "running"}`
- MCP server `/health` endpoint returns `{"status": "healthy", "mcp_tools": [...]}`
- Nginx proxy `/health` endpoint returns `{"status": "ok"}`
- Nginx proxy forwards `/mcp` requests to MCP server
- At least 1 tool with "example" in name present in health response

---

### Tier 3: Tool Registration Tests (Requires Redis)

**Purpose**: Validate end-to-end tool registration flow: MCP discovery → Redis storage → CLI lifecycle.

**Files**:
- `test_tool_registration.py` - Three-phase validation

**Phases**:
1. **3A: MCP Tool Discovery** - Validate `tools/list` JSON-RPC endpoint
2. **3B: ADEPT Redis Registration** - Validate tools stored in Redis with correct schema
3. **3C: CLI Lifecycle** - Validate register/verify/delete operations

**Prerequisites**:
```bash
# Ensure Redis is accessible
docker exec {{NAME}}_redis redis-cli PING
# Expected: PONG

# Register tools
python scripts/register_{{NAME}}_tools.py --register
```

**Run Commands**:
```bash
# Run all Tier 3 tests
make test-registration

# Or with nohup
nohup make test-registration > logs/test_registration_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

**Expected Results**:
- MCP `tools/list` returns {{TOOL_COUNT}} tools
- All tool names prefixed with `{{NAME}}_`
- Tools registered in Redis with protocol=mcp
- Tool URLs contain `/mcp` path
- Framework fields NOT present in schemas
- CLI register/delete commands succeed

---

### Tier 4: CLI End-to-End Tests (Full Stack)

**Purpose**: Validate complete workflows from CLI tool invocation through to results.

**Files**: (To be added as domain logic is implemented)
- `test_cli_e2e_example_tool.py` - Example tool invocation with file upload
- `test_cli_e2e_job_status.py` - Job status polling workflow

**Run Commands**:
```bash
# Run all CLI E2E tests (when implemented)
make test-cli-e2e

# Or with nohup
nohup make test-cli-e2e > logs/test_cli_e2e_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

---

## Critical Testing Principles

### 1. Docker Restart Does NOT Pick Up Source Changes

**IMPORTANT**: `docker compose restart` only restarts containers — it does NOT rebuild images with updated source code.

**Correct Workflow After Code Changes**:
```bash
# 1. Stop containers
docker compose down

# 2. Rebuild MCP server image
docker compose build {{NAME}}_mcp_server

# 3. Start with new image
docker compose up -d

# 4. Verify new code is loaded
docker exec {{NAME}}_mcp_server cat /app/{{NAME}}_mcp/__version__.py
```

**Makefile Shortcuts**:
```bash
# Full rebuild workflow
make rebuild

# Quick restart (no rebuild - only use if config/env changed)
make restart
```

---

### 2. Test Image Naming Conventions

The project uses **two Docker image tags** for different purposes:

| Tag | Purpose | Built By | Used By |
|-----|---------|----------|---------|
| `{{NAME}}-mcp:latest` | Standalone test execution | `docker build -f tests/Dockerfile.test` | Makefile test targets |
| `{{NAME}}_mcp_server:dev` | Deployed service | `docker compose build {{NAME}}_mcp_server` | docker-compose.yaml |

**Why Two Tags?**
- Test image includes pytest, requests, redis-py dependencies
- Service image is production-lean (no test dependencies)
- Test image mounts source code read-only (no persistence)
- Service image copies source code into container (persistent)

**Rebuild Commands**:
```bash
# Rebuild test image
docker build -t {{NAME}}-mcp:latest -f tests/Dockerfile.test .

# Rebuild service image
docker compose build {{NAME}}_mcp_server
```

---

### 3. Nohup Test Execution Pattern

For long-running tests or CI/CD integration, use nohup with timestamped logs:

```bash
# Create logs directory
mkdir -p logs

# Run tests in background with timestamped log
nohup make test-all > logs/test_all_$(date +%Y%m%d_%H%M%S).log 2>&1 &

# Monitor progress (Ctrl+C to stop tailing, background job continues)
tail -f logs/test_all_*.log

# Check status
jobs
ps aux | grep pytest

# View results after completion
cat logs/test_all_*.log | grep -E "(PASSED|FAILED|ERROR)"
```

---

## Makefile Test Targets Summary

| Target | Tier | Description |
|--------|------|-------------|
| `make test-unit` | 1 | Offline unit tests (imports, config, schema) |
| `make test-integration` | 2 | Container health and deployment validation |
| `make test-registration` | 3 | MCP discovery + Redis + CLI lifecycle |
| `make test-cli-e2e` | 4 | Full end-to-end CLI workflows |
| `make test-all` | All | Run all test tiers sequentially |
| `make test-clean` | - | Remove test artifacts, logs, cache |

---

## Troubleshooting

### Tests Fail with "Connection Refused"
```bash
# Check if containers are running
docker ps | grep {{NAME}}

# Check MCP server logs
docker logs {{NAME}}_mcp_server

# Verify network connectivity
docker exec {{NAME}}-mcp-test-runner curl http://{{NAME}}_mcp_server:{{MCP_PORT}}/health
```

### Tests Fail with "Module Not Found"
```bash
# Ensure test image is built
docker build -t {{NAME}}-mcp:latest -f tests/Dockerfile.test .

# Verify PYTHONPATH in test container
docker run --rm {{NAME}}-mcp:latest env | grep PYTHONPATH
```

### Redis Tests Fail
```bash
# Check Redis connectivity
docker exec {{NAME}}_redis redis-cli PING

# Check if tools are registered
docker exec {{NAME}}_redis redis-cli KEYS "tool:{{NAME}}_*"

# Re-register tools
python scripts/register_{{NAME}}_tools.py --register
```

### Schema Tests Fail with "Framework Fields in Schema"
This indicates the registration script is not properly stripping framework-injected fields. Check:
1. `scripts/register_{{NAME}}_tools.py` - Ensure `_strip_framework_fields()` is called
2. Tool definitions - Framework fields should have `exclude=True` in Field annotations
3. Pydantic schema extraction - Verify `model_json_schema(mode="serialization")` is used

---

## Coverage Goals

- **Tier 1**: 100% (all imports, config, schema extraction)
- **Tier 2**: 100% (all health/deployment endpoints)
- **Tier 3**: 100% (full registration lifecycle)
- **Tier 4**: 80% (critical workflows covered)

Run coverage reports with:
```bash
pytest tests/ --cov={{NAME}}_mcp --cov-report=html
open htmlcov/index.html
```
