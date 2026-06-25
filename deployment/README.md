# ADEPT Framework Deployment

This directory contains deployment automation and orchestration for the ADEPT Framework.

## Directory Structure

```
deployment/
├── local/                  # Local Docker-based deployment
│   ├── docker-compose/    # Docker Compose definitions
│   └── README.md          # Local deployment guide
│
├── ansible/               # Ansible automation
│   ├── roles/            # Reusable roles (cloud_auth, validation, aws_cdk_deploy)
│   └── scripts/          # Bootstrap and management scripts
│
└── cloud/                 # Cloud provider deployments
    └── aws/              # AWS CDK stacks and tooling
```

## Quick Start

### Local Development

```bash
# Start all services
make start

# Stop all services
make stop

# Full rebuild (no cache)
make rebuild
```

### Cloud Deployment (AWS)

See [devtools/skypilot/](../devtools/skypilot/) for the full cloud deployment toolkit (CDK + Ansible + SkyPilot).

## Docker Compose Files

All Docker Compose files are located in `local/docker-compose/`:

| File | Purpose |
|------|---------|
| `docker-compose.base.yaml` | Infrastructure services (Keycloak, PostgreSQL, Redis) |
| `docker-compose.core.yaml` | Application services (Gateway, Orchestration, MCP servers) |
| `docker-compose.multi-stack.yaml` | Multi-stack deployment configuration |
| `docker-compose.langfuse.yaml` | Observability (Langfuse + ClickHouse) |
| `docker-compose.dind.yaml` | Docker-in-Docker for sandbox execution |

## Network Architecture

ADEPT uses a three-tier network model:

| Network | Services | Purpose |
|---------|----------|---------|
| `adept_frontend_network` | nginx_proxy, OAuth2 proxy, UIs | User-facing (external access) |
| `adept_application_network` | agent_gateway, orchestration_service, Keycloak, MCP servers | Business logic (internal) |
| `adept_data_network` | PostgreSQL, Redis | Data persistence |

## Service Dependencies

### Startup Order

1. Base infrastructure (Keycloak, PostgreSQL, Redis)
2. Core application services (Gateway, Orchestration, Registry)
3. MCP tool servers (sandbox, general, HPC)
4. Frontend services (nginx, Streamlit, Management UI)

### Health Checks

```bash
# Check all services
make validate-service-health

# Comprehensive system validation
make validate
```

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and configure:

- `COMPOSE_PROJECT_NAME` -- Docker Compose project name
- LLM provider credentials (Azure, AWS Bedrock, etc.)
- Keycloak admin credentials

### Secrets Management

Secrets are managed via file-based retrieval (`SECRET_RETRIEVAL_METHOD=file`):
- `/run/secrets/` -- Runtime secret mounting (Kubernetes)
- `/app/credentials/` -- Credential directory (Docker Compose)
- `.env-keycloak-credentials-dir/` -- Generated Keycloak client secrets

## Troubleshooting

### Common Issues

1. **Port Conflicts**: Check `docker ps` for running containers
2. **Network Issues**: Ensure networks are created: `docker network ls`
3. **Volume Permissions**: Run `make init-shared-volume-permissions`
4. **Credential Drift**: Run `make fix-credentials && make sync-credentials`

### Logs

```bash
# View service logs
docker compose logs -f <service_name>

# Tail a specific service
docker logs orchestration_service --tail 50 --since 5m
```

## Related Documentation

- [Cloud Deployment Guide](../devtools/skypilot/ONBOARDING.md)
- [Swarm Multi-Stack Deployment](../docs/deployment/SWARM_MULTI_STACK_DEPLOYMENT_GUIDE.md)
- [K8s Onboarding](../docs/deployment/INFRASTRUCTURE_ENGINEER_K8S_ONBOARDING.md)
