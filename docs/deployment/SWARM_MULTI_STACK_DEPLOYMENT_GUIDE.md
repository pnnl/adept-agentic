# Docker Swarm Multi-Stack Deployment Guide

## Overview

Docker Swarm provides production-grade orchestration for deploying multiple isolated ADEPT stacks. This guide covers setting up and managing ADEPT stacks using Docker Swarm mode.

## Prerequisites

### 1. Initialize Docker Swarm

```bash
# Initialize Swarm (only needed once)
docker swarm init

# Verify Swarm is active
docker info | grep Swarm
# Should show: Swarm: active
```

Your Swarm cluster is now initialized with the current node as a manager at `10.16.17.5:2377`.

### 2. Install Dependencies

```bash
# Activate the virtual environment
source .venv/bin/activate

# Install required packages (if not already installed)
uv pip install python-on-whales jinja2 httpx pydantic
```

## Architecture

### Swarm Benefits for Multi-Stack ADEPT

1. **No Docker-in-Docker Issues**: Swarm services run natively on the host
2. **Service Discovery**: Built-in DNS for inter-service communication
3. **Load Balancing**: Automatic load distribution across replicas
4. **Rolling Updates**: Zero-downtime deployments with rollback capability
5. **Overlay Networks**: Secure, isolated networks spanning multiple nodes
6. **Secrets Management**: Secure handling of sensitive configuration

### Stack Components in Swarm

Each ADEPT stack deployed to Swarm includes:
- **Overlay Network**: Isolated network for the stack
- **Services**: Gateway, Orchestrator, MCP servers (each as a Swarm service)
- **Volumes**: Persistent storage for PostgreSQL, Redis, and uploaded files
- **Routing Mesh**: Ingress routing for external access

## Deployment Instructions

### Prerequisites

#### 1. Build ADEPT Images

Before deploying to Swarm, build all ADEPT images:

```bash
# Build all images (without starting containers)
make build

# Or build with no cache for a clean build
make build-no-cache
```

This creates the following images:
- `chapter-06-advanced-multi-agent-orchestration-nginx_proxy` - Nginx reverse proxy for external access
- `chapter-06-advanced-multi-agent-orchestration-agent_gateway` - Agent Gateway (Tier 1)
- `chapter-06-advanced-multi-agent-orchestration-orchestration_service` - Orchestration Service (Tier 2)
- `chapter-06-advanced-multi-agent-orchestration-mcp_server` - MCP Tool Server
- `chapter-06-advanced-multi-agent-orchestration-sandbox_mcp_server` - Sandbox execution server
- `chapter-06-advanced-multi-agent-orchestration-hpc_mcp_server` - HPC/Pipeline server
- `chapter-06-advanced-multi-agent-orchestration-gateway_registry` - Service registry

#### 2. Generate Swarm Templates

Generate the Jinja2 templates for Swarm deployment:

```bash
cd tests/multi-stack

# Generate Swarm templates (only needed once)
../../.venv/bin/python3.11 -c "
from swarm_stack_manager import SwarmStackManager
import asyncio
manager = SwarmStackManager()
asyncio.run(manager.create_swarm_templates())
"

# This creates:
# - swarm-templates/stack.yaml.j2 (Docker Stack template)
# - swarm-templates/deploy.sh.j2 (Deployment script template)
```

### Method 1: Using Python Swarm Manager

```bash
cd tests/multi-stack

# Deploy a single stack
../../.venv/bin/python3.11 swarm_stack_manager.py deploy stack_a

# Deploy multiple stacks
../../.venv/bin/python3.11 swarm_stack_manager.py deploy stack_a
../../.venv/bin/python3.11 swarm_stack_manager.py deploy stack_b
../../.venv/bin/python3.11 swarm_stack_manager.py deploy stack_c

# Check stack status
../../.venv/bin/python3.11 swarm_stack_manager.py status stack_a

# Scale a service (e.g., add more gateway replicas)
../../.venv/bin/python3.11 swarm_stack_manager.py scale stack_a gateway 3

# Remove a stack
../../.venv/bin/python3.11 swarm_stack_manager.py remove stack_a
```

### Method 2: Using Makefile Targets

```bash
# Deploy stack to Swarm
make multi-stack-swarm-deploy STACK=stack_a

# Remove stack from Swarm
make multi-stack-swarm-remove STACK=stack_a

# Deploy multiple stacks
make multi-stack-swarm-deploy STACK=stack_a
make multi-stack-swarm-deploy STACK=stack_b
```

### Method 3: Direct Docker Stack Commands

```bash
# First, generate the stack configuration
cd tests/multi-stack
.venv/bin/python3.11 -c "
from swarm_stack_manager import SwarmStackManager
manager = SwarmStackManager()
import asyncio
asyncio.run(manager.create_swarm_templates())
"

# Deploy using docker stack
docker stack deploy -c swarm-templates/stack_a.yaml stack_a

# List deployed stacks
docker stack ls

# View services in a stack
docker stack services stack_a

# Remove a stack
docker stack rm stack_a
```

## Stack Configuration

### Port Mappings

Each stack uses unique ports to avoid conflicts:

| Stack    | Nginx HTTP | Nginx HTTPS | Gateway | Orchestrator | MCP  | Sandbox | Registry |
|----------|------------|-------------|---------|--------------|------|---------|----------|
| stack_a  | 80         | 443         | 8083    | 8084        | 8080 | 8082    | 8086     |
| stack_b  | 8080       | 8443        | 8183    | 8184        | 8180 | 8182    | 8186     |
| stack_c  | 9080       | 9443        | 8283    | 8284        | 8280 | 8282    | 8286     |

**Note**: External clients should connect via the Nginx proxy ports for proper authentication and routing.

### Network Architecture

```
┌─────────────────────────────────────────┐
│         Docker Swarm Cluster            │
├─────────────────────────────────────────┤
│                                         │
│  ┌───────────────────────────────┐     │
│  │   Stack A Overlay Network     │     │
│  │  ┌─────────┐  ┌────────────┐ │     │
│  │  │ Gateway │──│Orchestrator│ │     │
│  │  └─────────┘  └────────────┘ │     │
│  │  ┌─────────┐  ┌────────────┐ │     │
│  │  │   MCP   │──│  Sandbox   │ │     │
│  │  └─────────┘  └────────────┘ │     │
│  └───────────────────────────────┘     │
│                                         │
│  ┌───────────────────────────────┐     │
│  │   Stack B Overlay Network     │     │
│  │  ┌─────────┐  ┌────────────┐ │     │
│  │  │ Gateway │──│Orchestrator│ │     │
│  │  └─────────┘  └────────────┘ │     │
│  │  ┌─────────┐  ┌────────────┐ │     │
│  │  │   MCP   │──│  Sandbox   │ │     │
│  │  └─────────┘  └────────────┘ │     │
│  └───────────────────────────────┘     │
│                                         │
│  ┌───────────────────────────────┐     │
│  │   Shared Services Network     │     │
│  │  ┌──────────┐  ┌───────────┐ │     │
│  │  │PostgreSQL│  │   Redis   │ │     │
│  │  └──────────┘  └───────────┘ │     │
│  │  ┌──────────┐  ┌───────────┐ │     │
│  │  │ Keycloak │  │ Registry  │ │     │
│  │  └──────────┘  └───────────┘ │     │
│  └───────────────────────────────┘     │
└─────────────────────────────────────────┘
```

## Monitoring and Management

### View Stack Status

```bash
# List all stacks
docker stack ls

# View services in a specific stack
docker stack services stack_a

# View tasks (containers) for a service
docker service ps stack_a_gateway

# View logs for a service
docker service logs stack_a_gateway -f

# Inspect a service
docker service inspect stack_a_gateway
```

### Scaling Services

```bash
# Scale gateway service to 3 replicas
docker service scale stack_a_gateway=3

# Scale orchestrator service
docker service scale stack_a_orchestrator=2

# View scaling status
docker service ps stack_a_gateway
```

### Rolling Updates

```bash
# Update service image
docker service update \
  --image adept-stack_a-gateway:v2 \
  stack_a_gateway

# Update with rollback on failure
docker service update \
  --update-failure-action rollback \
  --image adept-stack_a-gateway:v2 \
  stack_a_gateway

# Force update (recreate all tasks)
docker service update --force stack_a_gateway
```

## Quick Start Guide

### Complete Setup and Test

Follow these steps for a complete setup and test deployment:

```bash
# 1. Build all ADEPT images first (prerequisite)
make build

# 2. Initialize Docker Swarm (if not already done)
docker swarm init

# 3. Generate Swarm templates
cd tests/multi-stack
../../.venv/bin/python3.11 -c "
from swarm_stack_manager import SwarmStackManager
import asyncio
manager = SwarmStackManager()
asyncio.run(manager.create_swarm_templates())
"

# 4. Run the demo (deploys 2 stacks for 60 seconds)
../../.venv/bin/python3.11 swarm_stack_manager.py demo
```

## Quick Test Deployment

After building images with `make build`, test that Swarm deployment is working:

```bash
cd tests/multi-stack

# Run the demo (deploys 2 stacks for 60 seconds)
../../.venv/bin/python3.11 swarm_stack_manager.py demo

# Or deploy a test stack manually
../../.venv/bin/python3.11 swarm_stack_manager.py deploy test_stack

# Check if services are running
docker stack services test_stack

# View logs
docker service logs test_stack_gateway -f

# Remove test stack
../../.venv/bin/python3.11 swarm_stack_manager.py remove test_stack
```

### Verify Deployment

After deploying a stack, verify it's working:

```bash
# List all stacks
docker stack ls

# Check services in the stack
docker stack services stack_a

# Test gateway health endpoint
curl http://localhost:8083/health

# Test orchestrator health endpoint  
curl http://localhost:8084/health

# View service tasks (containers)
docker service ps stack_a_gateway

# Check service logs
docker service logs stack_a_gateway --tail 50
```

## Testing A2A Delegation in Swarm

### 1. Deploy Two Stacks

```bash
# Deploy stack_a and stack_b
make multi-stack-swarm-deploy STACK=stack_a
make multi-stack-swarm-deploy STACK=stack_b

# Wait for services to be ready
docker stack services stack_a
docker stack services stack_b
```

### 2. Register Cross-Stack Connection

```bash
# Register stack_b in stack_a's gateway registry
curl -X POST http://localhost:8086/v1/gateways \
  -H "Content-Type: application/json" \
  -d '{
    "alias": "stack_b",
    "url": "http://stack_b_gateway:8081",
    "capabilities": ["sandbox", "mcp-tools"]
  }'
```

### 3. Test Delegation

```bash
# Send delegation request from stack_a to stack_b
curl -X POST http://localhost:8083/v1/chat/completions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "agentic-framework:scientific-agent-v1",
    "messages": [{
      "role": "user",
      "content": "Delegate to stack_b: Generate a plot"
    }]
  }'
```

## Troubleshooting

### Common Issues

#### 1. Service Won't Start

```bash
# Check service status
docker service ps stack_a_gateway --no-trunc

# View service logs
docker service logs stack_a_gateway --tail 50

# Inspect service configuration
docker service inspect stack_a_gateway
```

#### 2. Network Connectivity Issues

```bash
# List networks
docker network ls

# Inspect overlay network
docker network inspect stack_a_default

# Test connectivity between services
docker run --rm --network stack_a_default alpine ping gateway
```

#### 3. Sandbox Privileged Mode

The sandbox service requires special handling in Swarm:

```yaml
# In stack configuration
sandbox:
  cap_add:
    - SYS_ADMIN
    - SYS_PTRACE
  security_opt:
    - apparmor:unconfined
    - seccomp:unconfined
```

Note: Full privileged mode is not supported in Swarm. Consider using:
- Kubernetes with SecurityContext
- Docker Compose for development
- Modified sandbox without nsjail for Swarm

#### 4. Volume Persistence

```bash
# List volumes
docker volume ls | grep stack_a

# Inspect volume
docker volume inspect stack_a_postgres_data

# Backup volume data
docker run --rm -v stack_a_postgres_data:/data \
  -v $(pwd):/backup alpine \
  tar czf /backup/postgres_backup.tar.gz /data
```

## Best Practices

1. **Use Constraints**: Place stateful services on specific nodes
   ```yaml
   deploy:
     placement:
       constraints:
         - node.role == manager
         - node.labels.type == storage
   ```

2. **Set Resource Limits**: Prevent resource exhaustion
   ```yaml
   deploy:
     resources:
       limits:
         memory: 2g
         cpus: '2.0'
       reservations:
         memory: 1g
         cpus: '1.0'
   ```

3. **Configure Health Checks**: Ensure service availability
   ```yaml
   healthcheck:
     test: ["CMD", "curl", "-f", "http://localhost:8081/health"]
     interval: 30s
     timeout: 10s
     retries: 3
     start_period: 40s
   ```

4. **Use Secrets**: Never hardcode sensitive data
   ```bash
   # Create secret
   echo "mypassword" | docker secret create db_password -
   
   # Use in service
   docker service create \
     --secret db_password \
     --env POSTGRES_PASSWORD_FILE=/run/secrets/db_password \
     postgres
   ```

5. **Monitor Services**: Use Docker's built-in metrics
   ```bash
   # Enable metrics
   docker service update \
     --endpoint-mode vip \
     --publish published=9090,target=9090 \
     prometheus
   ```

## Multi-Node Swarm Cluster

To scale beyond a single node:

### Add Worker Nodes

```bash
# On worker nodes, run:
docker swarm join --token \
  SWMTKN-1-5o3d5il5779w6b98tpdu1zymjgeoiedd63qvf08089vs4mm17r-5m180bd6cloo5485a2aha8fpk \
  10.16.17.5:2377
```

### Add Manager Nodes

```bash
# Get manager token
docker swarm join-token manager

# On new manager nodes, run the displayed command
```

### View Cluster Status

```bash
# List nodes
docker node ls

# Inspect node
docker node inspect <node-id>

# Update node labels
docker node update --label-add type=gpu <node-id>
```

## Cleanup

### Remove Individual Stacks

```bash
# Remove a specific stack
docker stack rm stack_a

# Wait for cleanup
docker stack ps stack_a  # Should show no tasks
```

### Remove All Stacks

```bash
# List and remove all stacks
for stack in $(docker stack ls --format "{{.Name}}"); do
  docker stack rm $stack
done

# Clean up volumes (CAUTION: data loss)
docker volume prune -f

# Leave Swarm mode
docker swarm leave --force
```

## Summary

Docker Swarm provides a robust, production-ready platform for deploying multiple ADEPT stacks with:
- **Automatic service discovery** between stack components
- **Built-in load balancing** for high availability
- **Rolling updates** with automatic rollback
- **Overlay networks** for secure isolation
- **No Docker-in-Docker issues** for test execution

For development and testing, the idempotent stack manager provides more control, while Swarm excels in production environments requiring scalability and resilience.