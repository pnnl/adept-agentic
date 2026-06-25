# Local Docker Deployment

This directory contains Docker-based local deployment configurations for the ADEPT Framework.

## Structure

```
local/
├── docker-compose/        # Docker Compose YAML files
│   ├── docker-compose.base.yaml         # Infrastructure services
│   ├── docker-compose.core.yaml         # Application services
│   ├── docker-compose.ragflow-backend.yaml  # RAGFlow backend
│   ├── docker-compose.ragflow-ui.yaml   # RAGFlow UI
│   └── docker-compose.multi-stack.yaml  # Multi-stack config
│
└── bootstrap/            # Bootstrap and initialization scripts
```

## Docker Compose Files

### docker-compose.base.yaml
Infrastructure services that all application services depend on:
- **Keycloak**: Identity and access management
- **PostgreSQL**: Primary database
- **Redis**: Caching and session management
- **NGINX**: Reverse proxy

### docker-compose.core.yaml
Core ADEPT application services:
- **Agent Gateway**: API gateway with authentication
- **Orchestration Service**: Core orchestration engine
- **Gateway Registry**: Service discovery
- **MCP Servers**: Tool execution servers
  - mcp_server: General scientific tools
  - hpc_mcp_server: HPC and pipeline tools
  - sandbox_mcp_server: Secure code execution
- **Streamlit App**: Web UI
- **Management UI**: Gateway management interface

### docker-compose.ragflow-backend.yaml
Dedicated RAGFlow backend services (isolated):
- **RAGFlow PostgreSQL**: Port 5433
- **RAGFlow Redis**: Port 6380
- **RAGFlow Elasticsearch**: Port 9201
- **RAGFlow MinIO**: Ports 9010/9011 (optional)

### docker-compose.ragflow-ui.yaml
RAGFlow UI service with Keycloak SSO integration:
- **RAGFlow UI**: Port 9382
- Connects to RAGFlow API on port 9380
- Uses external volumes from main stack

### docker-compose.multi-stack.yaml
Configuration for running multiple ADEPT stacks simultaneously for testing inter-gateway communication.

## Usage

### Basic Commands

```bash
# From project root
cd ../..

# Start all services
make start

# Stop all services
make stop

# Rebuild services
make rebuild
```

### RAGFlow Integration

```bash
# Start RAGFlow backend first
make start-ragflow-backend

# Then start main stack
make start

# Finally start RAGFlow UI
make start-ragflow-ui
```

### Direct Docker Compose Usage

```bash
# From this directory
cd docker-compose/

# Start base services
docker compose -f docker-compose.base.yaml up -d

# Start core services
docker compose -f docker-compose.base.yaml -f docker-compose.core.yaml up -d

# View logs
docker compose -f docker-compose.base.yaml -f docker-compose.core.yaml logs -f
```

## Networks

- **agentic_framework_network**: Main application network
- **adept_integration_network**: Isolated RAGFlow backend network

## Volumes

Shared volumes enable data persistence and sharing:
- **shared_uploads**: User uploaded files
- **ragflow_data**: RAGFlow application data
- **ragflow_sessions**: RAGFlow session state
- **keycloak_data**: Keycloak persistence
- **postgres_data**: PostgreSQL persistence

## Ports

| Service | Port | Description |
|---------|------|-------------|
| Keycloak | 8180 | Identity provider |
| Agent Gateway | 8081 | API gateway |
| Orchestration | 8084 | Orchestration service |
| Gateway Registry | 8086 | Service registry |
| Streamlit | 9091 | Web UI |
| NGINX | 80, 443 | Reverse proxy |
| RAGFlow API | 9380 | RAGFlow API |
| RAGFlow UI | 9382 | RAGFlow Web UI |
| RAGFlow PostgreSQL | 5433 | RAGFlow database |
| RAGFlow Redis | 6380 | RAGFlow cache |
| RAGFlow Elasticsearch | 9201 | RAGFlow search |

## Environment Configuration

Environment variables are loaded from:
- `.env` - Main configuration
- `.env-keycloak-credentials-dir/.env-keycloak-credentials` - Keycloak secrets

## Troubleshooting

### Check Service Status
```bash
docker ps
docker compose ps
```

### View Logs
```bash
# All services
docker compose logs -f

# Specific service
docker logs agent_gateway -f
```

### Network Issues
```bash
# List networks
docker network ls

# Inspect network
docker network inspect agentic_framework_network
```

### Volume Permissions
```bash
# Fix permissions
make init-shared-volume-permissions
```