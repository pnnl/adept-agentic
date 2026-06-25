# Getting Started: System Administrators

This guide covers production administration of ADEPT: identity management, credential lifecycle, network architecture, security hardening, monitoring, and backup procedures.

---

## Authentication Management

ADEPT uses Keycloak as its central identity provider. All services authenticate via JWT tokens with RBAC enforced through group membership.

### Key Concepts

| Concept | Description |
|---------|-------------|
| Realm | Logical tenant boundary (default: `agentic-framework`) |
| Clients | OAuth2 applications (Agent Gateway, OpenWebUI, Management UI) |
| Groups | RBAC roles: `admin`, `gateway-service`, `notebook-users` |
| Flows | ROPC for end-users, Client Credentials for service-to-service |

### User Management

Users are created during bootstrap with group-based access:

- **admin**: Full platform access, Management UI, tool administration
- **notebook-users**: JupyterLab access, file uploads, agent interactions
- **gateway-service**: Service accounts for inter-tier communication

---

## Credential Lifecycle

ADEPT manages credentials through a three-phase lifecycle:

```bash
# Phase 1: Generate credentials (during bootstrap or regeneration)
make fix-credentials

# Phase 2: Sync credentials for test/validation containers
make sync-credentials

# Phase 3: Validate credential health
make validate-credentials
```

!!! warning "Critical Dependency"
    The `KC_ADMIN_CLI_SECRET` must match the value in Keycloak's database. If Keycloak is rebuilt, this secret changes and must be updated in `.env` before any credential operations succeed.

### Discovery and Recovery

```bash
# Discover current KC_ADMIN_CLI_SECRET from database
./scripts/deps/discover_admin_cli_secret.sh

# Validate all service credentials authenticate successfully
make validate-credentials

# Comprehensive health check with recommendations
python scripts/deps/service_health_manager.py --health-check
```

---

## Network Architecture

ADEPT uses a three-tier network topology for defense in depth:

| Network | Services | Purpose |
|---------|----------|---------|
| Frontend | NGINX proxy, OAuth2 proxy, UIs | External access |
| Application | Agent Gateway, Orchestration, Keycloak, MCP servers | Business logic |
| Data | PostgreSQL, Redis | Persistence (no external access) |

!!! info "Network Isolation"
    The data tier is never exposed externally. All database access flows through the application tier.

### Access Patterns

| Client Type | Entry Point | Authentication |
|-------------|-------------|----------------|
| External (browser, SDK) | NGINX proxy (443) | OAuth2 / JWT Bearer |
| Service-to-service | Application network (internal DNS) | Client Credentials |
| Administrative | Direct container exec | Keycloak admin token |

---

## Security Model

### Authentication Flow

1. User authenticates via Keycloak (OIDC/OAuth2)
2. JWT issued with group claims for RBAC
3. Agent Gateway (Tier 1) validates JWT on every request
4. User context forwarded to Tier 2 via secure headers; Tier 3 receives session context for isolation

### Sandbox Isolation

Code execution runs in nsjail-isolated containers with filesystem isolation, network restrictions, resource limits, and no persistent state between executions.

### OAuth2 Redirect URI Management

Manage external access URIs with zero downtime (no service restart required):

```bash
# Add, list, or remove redirect URIs
docker exec orchestration_service python3 \
  /app/scripts/nginx_proxy/manage_redirect_uris.py add <ip-or-domain>
docker exec orchestration_service python3 \
  /app/scripts/nginx_proxy/manage_redirect_uris.py list
```

---

## Monitoring

| Component | Purpose |
|-----------|---------|
| Langfuse | LLM trace collection, token usage, cost tracking |
| Service health manager | Credential drift detection, auto-recovery |
| Structured logging | JSON logs with session correlation IDs |

```bash
make validate-comprehensive-health   # Full system validation
make validate-mcp-tools-discovery    # MCP tool discovery check
```

---

## Backup and Recovery

| Component | Backup Command | Restore Command |
|-----------|---------------|-----------------|
| PostgreSQL | `docker exec postgres pg_dump -U admin -d agentic_framework > backup.sql` | `docker exec -i postgres psql -U admin -d agentic_framework < backup.sql` |
| Redis | `docker exec redis redis-cli BGSAVE` | Restart with existing `/data/dump.rdb` |
| Keycloak | `kc.sh export --dir /tmp/export --realm agentic-framework` | `kc.sh import --dir /tmp/export` |

!!! tip "Backup Schedule"
    For production deployments, schedule PostgreSQL backups daily, Redis snapshots hourly, and Keycloak exports after identity configuration changes.

---

## Common Operations

| Task | Command |
|------|---------|
| Restart single service | `make rebuild-gateway` |
| Regenerate all secrets | `make fix-credentials && make sync-credentials` |
| Add external access URI | `manage_redirect_uris.py add <address>` |
| Check service logs | `docker logs <service> --tail 50 --since 5m` |
| Validate full system | `make validate` |
| Bootstrap from scratch | `make teardown && make start` |
