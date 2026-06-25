# Running Tests

## Overview

All ADEPT tests are invoked through Makefile targets. This ensures consistent execution environments, proper network configuration, and reproducible results across development machines and CI.

## Prerequisites

Before running tests, ensure:

1. **Services are running** -- execute `make start` to bring up the full stack.
2. **Credentials are synced** -- run `make sync-credentials` to copy service secrets to the test credential directory.
3. **Docker is available** -- all tests execute inside containers.

```bash
# Verify prerequisites
make start
make sync-credentials
docker ps --format "table {{.Names}}\t{{.Status}}" | head -10
```

## Quick Reference

| Target | Scope | Duration |
|--------|-------|----------|
| `make validate` | Full E2E suite | 5-15 min |
| `make validate-unit-all` | All unit tests with coverage | 1-3 min |
| `make validate-unit-pkg` | Platform package unit tests | 30-60s |
| `make validate-unit-sdk` | SDK unit tests | 15-30s |
| `make validate-response-api-tool-calls` | Response API streaming | 30-60s |
| `make validate-service-health` | Service credentials and discovery | 15-30s |
| `make validate-registry` | Gateway registry CRUD | 10-20s |
| `make validate-multi-agent` | Multi-agent orchestration | 60-120s |
| `make validate-cli-all` | All CLI validation tests | 30-60s |
| `make validate-unit-contract-tests` | Contract test suite | 10-20s |
| `make validate-credentials` | Service credential validation | 5-10s |

## Running Specific Tests

To run a single test file directly:

```bash
docker run --rm \
  --network=adept_application_network \
  --network=adept_frontend_network \
  -v "$(pwd)/src":/app/src:ro \
  -v "$(pwd)/tests":/app/tests:ro \
  -e AGENT_GATEWAY_URL=http://agent_gateway:8081/v1 \
  -e KEYCLOAK_URL=http://keycloak:8180 \
  agentic-framework-deps-base \
  /app/.venv/bin/pytest tests/e2e/test_example.py -v -s
```

!!! tip "Dual-network requirement"
    Test containers must connect to both `adept_application_network` (internal services) and `adept_frontend_network` (reverse proxy). The Makefile handles this automatically.

## Test Output

All test invocations should be wrapped with `nohup` and directed to timestamped log files:

```bash
mkdir -p logs
nohup make validate-unit-all > logs/unit_tests_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

This pattern ensures:

- Long-running tests do not block your terminal.
- Output is preserved for later analysis.
- Timestamps enable correlation with service logs.

To check results:

```bash
# View the most recent log
ls -t logs/ | head -1 | xargs -I{} tail -30 logs/{}

# Search for failures
grep -l "FAILED" logs/*.log
```

## Filtering Noisy Output

Some targets produce verbose pip installation messages. Filter them for cleaner output:

```bash
make validate-response-api-tool-calls 2>&1 | grep -v "Requirement already satisfied" | tail -40
```

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `401 Unauthorized` in tests | Stale credentials | `make sync-credentials` |
| `Connection refused` | Services not running | `make start` |
| `Network not found` | Stack never started | `make start` (creates networks) |
| `Permission denied` on source mount | UID mismatch | Ensure `:ro` on volume mounts |
| Tests hang indefinitely | Missing `-s` flag for interactive tests | Add `-s` to pytest args |

!!! warning "Never run tests on the host"
    Always use Docker containers for test execution. Host-based `pytest` invocations may use incorrect Python versions, missing dependencies, or wrong network paths.
