# Getting Started: Platform Engineers

This guide covers setting up an ADEPT development environment, understanding the service architecture, and common operational tasks for platform and DevOps engineers.

---

## Quick Start

```bash
# Clone the repository
git clone https://github.com/pnnl/adept-agentic.git
cd adept-agentic

# Configure environment
cp .env.example .env
# Edit .env with your LLM provider keys and configuration

# Start all services
make start

# Validate system health
make validate
```

!!! note "First Start"
    The initial `make start` pulls container images and bootstraps Keycloak with default credentials. This may take several minutes on first run.

---

## Architecture Overview

ADEPT implements a three-tier secure architecture:

```
Tier 1: Agent Gateway         — Pure authentication proxy (Keycloak JWT)
Tier 2: Orchestration Service — Core brain (LangGraph, PostgreSQL state)
Tier 3: MCP Tool Servers      — Stateless scientific executors
```

Supporting services: Keycloak (identity), PostgreSQL (state), Redis (cache), ChromaDB (vectors), Gateway Registry (A2A discovery).

[:octicons-arrow-right-24: Full Architecture Documentation](../architecture/overview.md)

---

## Docker Compose Structure

| File | Purpose |
|------|---------|
| `docker-compose.base.yaml` | Infrastructure: Keycloak, PostgreSQL, Redis, ChromaDB |
| `docker-compose.core.yaml` | Application: Gateway, Orchestration, MCP servers, Registry |
| `docker-compose.multi-stack.yaml` | Scaling: Multiple gateway instances for federation |

---

## Port Mappings

| Service | Container Port | Host Port | URL |
|---------|---------------|-----------|-----|
| Agent Gateway | 8081 | 8083 | `http://localhost:8083` |
| Orchestration Service | 8084 | 8084 | `http://localhost:8084` |
| Gateway Registry | 8086 | 8086 | `http://localhost:8086` |
| HPC MCP Server | 8081 | 8081 | `http://localhost:8081` |

!!! warning "Common Pitfall"
    The Agent Gateway is on host port **8083**, not 8081. Generated URLs using `localhost:8081` route to the HPC MCP Server instead.

---

## Configuration

Copy `.env.example` and configure the following sections:

| Category | Key Variables |
|----------|--------------|
| LLM Provider | `DEFAULT_LLM_MODEL`, `AZURE_API_*`, `AWS_*` |
| Authentication | `KEYCLOAK_*`, `KC_ADMIN_CLI_SECRET` |
| Database | `POSTGRES_*` |
| Service Mesh | `GATEWAY_*`, `REGISTRY_*` |

---

## Service Management

### Lifecycle Targets

```bash
make start              # Start all services
make stop               # Stop services
make restart            # Restart services
make rebuild            # Full rebuild (no cache)
make teardown           # Remove containers, networks, volumes
```

### Service-Specific Rebuilds

```bash
make rebuild-gateway          # Agent Gateway (Tier 1)
make rebuild-orchestrator     # Orchestration Service (Tier 2)
make rebuild-registry         # Gateway Registry
make rebuild-gateway-mgmt-ui  # Management UI
```

### Validation

```bash
make validate                     # All E2E tests
make validate-response-api-tool-calls  # Response API streaming
make validate-service-health      # Comprehensive health check
make validate-credentials         # Service authentication
```

---

## Multi-Cloud Deployment

ADEPT supports deployment across major cloud providers:

| Provider | IaC Tool | Orchestrator | Directory |
|----------|----------|--------------|-----------|
| AWS | CDK | EKS | `infra/aws/` |
| Azure | Pulumi | AKS | `infra/azure/` |
| GCP | Terraform | GKE | `infra/gcp/` |

Helm charts are available in `infra/helm/` for Kubernetes deployments.

[:octicons-arrow-right-24: Deployment Guide](../deployment/docker-compose.md)

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| 401 on API calls | Stale credentials | `make fix-credentials && make sync-credentials` |
| Services not starting | Missing .env | `cp .env.example .env` and configure |
| Port conflicts | Other services on 8083/8084 | Check `docker ps` and stop conflicting containers |
| Keycloak bootstrap fails | Wrong KC_ADMIN_CLI_SECRET | Run discovery script, update .env, rebuild |

!!! tip "Logs"
    Use `docker logs <service_name> --tail 50 --since 5m` to inspect recent service logs for debugging.
