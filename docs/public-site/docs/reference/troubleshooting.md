# Troubleshooting

This guide covers common issues encountered when developing with or operating an ADEPT stack, along with diagnostic commands and resolutions.

## Quick Diagnostics

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
make validate-credentials
make validate-service-health
docker logs orchestration_service --tail 50 --since 5m
```

## Authentication Issues

### KC_ADMIN_CLI_SECRET Mismatch (401 Errors)

**Symptom**: `401 unauthorized_client: Invalid client or Invalid client credentials`

**Resolution**:

```bash
# Discover the correct secret, update .env, then rebuild
docker exec postgres psql -U admin -d keycloak -c \
  "SELECT secret FROM client WHERE client_id = 'admin-cli';" -t -A
make rebuild-orchestrator
```

### Credential Drift

**Symptom**: Services return 401/403 after a Keycloak restart or extended uptime.

**Resolution**:

```bash
make fix-credentials      # Regenerate all service client secrets
make sync-credentials     # Sync to test credential location
make validate-credentials # Verify everything authenticates
```

!!! warning "Restart vs Rebuild"
    A Docker `restart` does NOT reload `.env` values. Use `make rebuild-<service>` or `docker compose up -d <service>` to pick up credential changes.

## Network Issues

### Three-Tier Network Architecture

ADEPT uses three Docker networks. Services must be on the correct network to communicate:

| Network | Purpose | Services |
|---------|---------|----------|
| `adept_frontend_network` | User-facing | nginx_proxy, OAuth2 proxy, UIs |
| `adept_application_network` | Business logic | agent_gateway, orchestration_service, Keycloak, MCP servers |
| `adept_data_network` | Data persistence | PostgreSQL, Redis |

!!! note "Legacy Network"
    The `agentic_framework_network` is deprecated and empty. If you see references to it in old scripts, update them to use the three-tier networks.

### Test Container Connectivity

Test containers must attach to **both** `adept_application_network` and `adept_frontend_network`:

```bash
docker run --rm \
  --network=adept_application_network \
  --network=adept_frontend_network \
  agentic-framework-deps-base \
  /app/.venv/bin/pytest tests/e2e/test_example.py -v
```

## Service Issues

### Port Mapping Confusion

The Agent Gateway container listens on port 8081 but is mapped to **host port 8083**:

| Service | Container Port | Host Port |
|---------|---------------|-----------|
| Agent Gateway | 8081 | **8083** |
| HPC MCP Server | 8081 | 8081 |

```bash
# Verify port mappings
docker ps --format "{{.Names}}\t{{.Ports}}" | grep -E "agent_gateway|hpc_mcp"
```

Use `make rebuild-gateway`, `make rebuild-orchestrator`, `make rebuild-registry`, or `make rebuild` (full, no cache) to rebuild services.

## Common Makefile Targets

| Target | Purpose |
|--------|---------|
| `make validate` | Run all E2E validation tests |
| `make validate-credentials` | Check service authentication |
| `make fix-credentials` | Regenerate all service client secrets |
| `make sync-credentials` | Sync credentials to test location |
| `make validate-service-health` | Full system health check |
| `make start` / `make stop` | Start or stop all services |
| `make rebuild` / `make teardown` | Full rebuild or complete teardown |
