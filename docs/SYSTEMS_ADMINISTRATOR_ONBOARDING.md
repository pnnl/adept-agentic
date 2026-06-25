# ADEPT Framework - Systems Administrator Onboarding

**Purpose**: Complete guide for systems administrators managing the ADEPT framework infrastructure
**Audience**: Systems administrators, DevOps engineers, platform operators
**Prerequisites**: Docker, PostgreSQL, Keycloak knowledge; Linux command-line proficiency
**Related**: [Platform AI Engineer Onboarding](PLATFORM_AI_ENGINEER_ONBOARDING.md), [ASOPB & Release Developer Tutorial](tutorials/DEVELOPER_ONBOARDING_ASOPB_AND_RELEASE.md), [Client-Side Certificate Trust](guides/CLIENT_CERTIFICATE_TRUST.md), [Ansible Deployment](../deployment/ansible/README.md), [Domain SME Guide](DOMAIN_SME_VIBE_CODING_GUIDE.md)

---

## Table of Contents

1. [Overview](#overview)
2. [Administrator Access & Authentication](#administrator-access--authentication)
3. [User Management](#user-management)
4. [A2A Gateway Mesh Management](#a2a-gateway-mesh-management)
5. [External Tool Management](#external-tool-management)
6. [Service API Token Management](#service-api-token-management)
7. [Keycloak Administration](#keycloak-administration)
8. [OAuth2 Configuration](#oauth2-configuration)
9. [Credential Management](#credential-management)
10. [Session Lineage Isolation (Context Auto-Compaction)](#session-lineage-isolation-context-auto-compaction)
11. [Service Health Monitoring](#service-health-monitoring)
12. [Ansible Stack Lifecycle Management](#ansible-stack-lifecycle-management)
13. [Troubleshooting](#troubleshooting)
14. [Security Best Practices](#security-best-practices)
15. [Backup & Recovery](#backup--recovery)

---

## Overview

### What is ADEPT?

ADEPT (Agentic Discovery & Exploration Platform for Tools) is a production-ready, three-tier distributed system providing OpenAI-compatible API endpoints with:
- **Tier 1**: Agent Gateway (authentication, RBAC, proxying)
- **Tier 2**: Orchestration Service (core "brain", OpenAI API, agent logic)
- **Tier 3**: MCP Tool Servers (stateless executors for scientific tools)

### Systems Administrator Responsibilities

As a systems administrator, you are responsible for:
- **User Lifecycle Management**: Creating, updating, and deactivating user accounts
- **Service Token Management**: Generating bearer tokens for non-interactive access
- **Credential Rotation**: Rotating secrets and API keys before expiration
- **Access Control**: Managing Keycloak groups and RBAC permissions
- **Service Health**: Monitoring service health and fixing credential drift
- **Security Compliance**: Enforcing password policies and token expiration
- **Backup & Recovery**: Ensuring data persistence and disaster recovery

### Infrastructure Architecture

#### Docker Network Segmentation

The platform implements a four-tier network architecture for security isolation:

| Network | Services | Security Level |
|---------|----------|----------------|
| `adept_frontend_network` | nginx_proxy, OAuth2 proxy, UIs | LOW (public-facing) |
| `adept_application_network` | agent_gateway, orchestration_service, Keycloak, MCP servers | MODERATE (internal services) |
| `adept_data_network` | PostgreSQL, Redis | HIGH (data persistence) |
| `adept_integration_network` | Langfuse, RAGFlow, 3rd-party services | MODERATE (3rd-party integrations) |

**Network Creation**: Automated by `scripts/init-shared-network.sh` during stack startup (Phase 2)

**Service Placement Principles**:
- User-facing services -> `adept_frontend_network`
- Business logic services -> `adept_application_network` + additional networks as needed
- Data services -> `adept_data_network` only (strict isolation)
- 3rd-party integrations -> `adept_integration_network`

**Security Benefits**:
- Database isolation (PostgreSQL only on `adept_data_network`)
- Service segmentation (MCP servers cannot access frontend)
- 3rd-party isolation (Langfuse/RAGFlow separated from core services)
- Kubernetes-ready architecture (maps to NetworkPolicies)

**Troubleshooting Network Issues**:
```bash
# List all networks
docker network ls | grep adept

# Inspect network membership
docker network inspect adept_application_network

# Verify service can reach another service
docker exec agent_gateway ping orchestration_service
```

**References**:
- Network Segmentation: `docs/security/NETWORK_SEGMENTATION_ARCHITECTURE.md`

### Docker Group Membership

**Requirement**: All users who manage ADEPT containers must be in the `docker` group so they can run Docker commands without `sudo`.

**Why This Matters**:
- Makefile targets, validation scripts, and `init-data` helpers all invoke `docker` directly
- Without group membership, every Docker command requires `sudo`, which breaks automated workflows
- Container UID/GID 1200:1200 (`appuser:appgroup`) is pinned in `infra/dockerfiles/Dockerfile.os-base` -- data directory ownership must match

**Adding a single user** (requires sudo):
```bash
# 1. Add user to the docker group
sudo usermod -aG docker $(whoami)

# 2. Activate the new group in the current shell (avoids full logout)
newgrp docker

# 3. Verify
id | grep docker
# Expected: groups=...,971(docker),...

docker ps --format '{{.Names}}' | head -3
# Expected: container names (no "permission denied")
```

**Adding multiple developers** (batch utility):
```bash
# Add multiple users at once
sudo bash deployment/ansible/scripts/manage-docker-users.sh add user1 user2

# List all docker group members
bash deployment/ansible/scripts/manage-docker-users.sh list

# Verify specific users
bash deployment/ansible/scripts/manage-docker-users.sh verify user1 user2
```

Each added user must then activate the group in their own shell (`newgrp docker` or re-login). See `deployment/ansible/README.md` -> [Post-Install: User Management](../deployment/ansible/README.md#post-install-user-management) for the full workflow and ordering.

**Important Notes**:
- `newgrp docker` starts a new shell with docker as the active group -- environment variables from the parent shell are preserved but shell functions may not be
- For SSH sessions, a full logout/login is the most reliable way to pick up the new group
- On Rocky Linux / RHEL 9, the docker group is created automatically by the `docker-ce` package
- **Ansible automation**: `deployment/ansible/playbooks/prepare-rocky-vm.yml` Phase 3 adds the provisioning user (`{{ adept_user }}`) to the docker group. Additional developers must be added separately using the utility script above.

**Data Directory Ownership**:
All data directories that containers write to must be owned by `appuser:appgroup` (UID/GID 1200:1200). Use a lightweight Alpine container to chown without sudo:
```bash
docker run --rm -v "$(pwd)/data":/data alpine \
  chown -R 1200:1200 /data/biofoundation /data/uploaded_files \
  /data/persistent_chroma_db /data/rag_indexes /data/sql_databases \
  /data/vector_db_persistence /data/sandbox_workspace /data/hpc_workspace
```

**References**:
- UID/GID pinning: `infra/dockerfiles/Dockerfile.os-base` (ARG APP_UID=1200, APP_GID=1200)

---

## Administrator Access & Authentication

### How Administrators Authenticate

**Critical Understanding**: System administrators authenticate through **direct container access** to the credentials directory, NOT through the UI.

#### Authentication Flow Diagram

```
System Administrator (Host Machine)
         |
make add-user USERNAME=alice PASSWORD=pass GROUPS=notebook-users
         |
docker exec orchestration_service bash -c "python /app/scripts/deps/add_keycloak_user.py ..."
         |
orchestration_service container
   - Has volume mount: ./.env-keycloak-credentials-dir:/app/credentials
   - Script reads: get_secret("KC_ADMIN_CLI_SECRET")
   - Fallback chain: /run/secrets -> /app/credentials -> environment
         |
Script finds: /app/credentials/KC_ADMIN_CLI_SECRET
         |
Authenticates with Keycloak Admin API using admin-cli confidential client
         |
Performs administrative operation (create user, generate token, etc.)
```

**Key Point**: No manual credential entry required - credentials are bootstrap-generated and persisted in the mounted directory.

#### Credential Directory Structure

```
deployment/local/docker-compose/.env-keycloak-credentials-dir/
├── KC_ADMIN_CLI_SECRET                    # Admin-CLI confidential client secret
├── AGENT_GATEWAY_CLIENT_SECRET            # Agent gateway service account
├── GATEWAY_CLIENT_SECRET                  # Gateway service secret
├── N8N_CLIENT_SECRET                      # n8n service account
├── OPENWEBUI_CLIENT_SECRET                # OpenWebUI service account
├── REGISTRY_CLIENT_SECRET                 # Gateway registry secret
├── SERVICE_API_KEYS_CONFIG                # Service API tokens (JSON)
├── service_api_tokens_metadata.json       # Token metadata (TTL, expiration)
└── .env-keycloak-credentials              # Consolidated credentials file
```

#### Verifying Administrator Access

```bash
# 1. Verify orchestration_service container is running
docker ps | grep orchestration_service

# 2. Verify credentials directory is mounted
docker exec orchestration_service ls -la /app/credentials/

# 3. Verify KC_ADMIN_CLI_SECRET is accessible
docker exec orchestration_service cat /app/credentials/KC_ADMIN_CLI_SECRET | wc -c
# Expected output: 32 (or similar, depending on secret length)

# 4. Test Keycloak connection
make list-keycloak-groups
# Expected output: List of 5 groups (admin, gateway-agents, etc.)
```

---

## User Management

### Creating New Users

**Use Case**: Onboard new scientists, engineers, or administrators with notebook-user-like permissions.

#### Quick Reference

```bash
# Create user with notebook-users group
make add-user USERNAME=alice PASSWORD=alice-password GROUPS=notebook-users

# Create user with multiple groups
make add-user USERNAME=bob PASSWORD=bob-pass GROUPS=notebook-users,streamlit-users

# Create admin user
make add-user USERNAME=admin-alice PASSWORD=secure-pass GROUPS=admin

# Update existing user (add to admin group)
make add-user USERNAME=alice GROUPS=notebook-users,admin UPDATE=true
```

#### User Management Script

**Script**: `scripts/deps/add_keycloak_user.py`

**Features**:
- User creation with username, password, email, and group assignment
- User updates (modify groups, reset passwords)
- Group validation (ensure groups exist before user creation)
- Email verification (automatically verify user emails)
- Dry-run mode (preview changes without applying)

**CLI Usage**:
```bash
# Create user
python scripts/deps/add_keycloak_user.py \
    --username alice \
    --password alice-password \
    --groups notebook-users \
    --email alice@example.com

# Update existing user
python scripts/deps/add_keycloak_user.py \
    --username alice \
    --groups notebook-users,admin \
    --update

# List available groups
python scripts/deps/add_keycloak_user.py --list-groups

# Dry-run mode (preview changes)
python scripts/deps/add_keycloak_user.py \
    --username test-user \
    --password test-pass \
    --groups notebook-users \
    --dry-run
```

#### Available Groups

| Group | Purpose | Permissions |
|-------|---------|-------------|
| **notebook-users** | End-user data scientists | Access to Agent Gateway API, Jupyter notebooks |
| **streamlit-users** | Streamlit v2 application users | Access to Streamlit chat interface |
| **admin** | System administrators | Full administrative access |
| **gateway-service** | Service accounts for gateways | Inter-gateway communication |
| **gateway-agents** | External services (n8n, OpenWebUI) | Agent Gateway API access |

#### User Validation

After creating a user, verify authentication:

```bash
# 1. Set environment variables
export KEYCLOAK_USERNAME=alice
export KEYCLOAK_PASSWORD=alice-password

# 2. Test authentication with LangGraph examples
python examples/scripts/validate-langgraph-examples.py

# 3. Or test manually with curl
curl -X POST "http://keycloak:8180/realms/agentic-framework/protocol/openid-connect/token" \
  -d "grant_type=password" \
  -d "client_id=notebook-user-client" \
  -d "username=alice" \
  -d "password=alice-password"
# Expected: JSON with access_token and refresh_token
```

#### User Lifecycle Management

**Deactivating Users**:
```bash
# Option 1: Remove from all groups (effectively disables access)
make add-user USERNAME=alice GROUPS="" UPDATE=true

# Option 2: Direct Keycloak admin (requires Keycloak UI or API)
docker exec keycloak /opt/keycloak/bin/kcadm.sh \
    config credentials --server http://localhost:8180 --realm master --user admin --password admin
docker exec keycloak /opt/keycloak/bin/kcadm.sh \
    update users/<user-id> -r master -s enabled=false
```

**Password Reset**:
```bash
# Reset password for existing user
make add-user USERNAME=alice PASSWORD=new-password UPDATE=true
```

**Audit User Activity**:
```bash
# View user sessions in database
docker exec postgres psql -U admin -d postgres -c \
    "SELECT session_id, user_id, username, session_type, status, created_at, last_active_at
     FROM user_sessions
     WHERE username='alice'
     ORDER BY created_at DESC
     LIMIT 10;"
```

---

## A2A Gateway Mesh Management

### Overview

The ADEPT framework supports distributed gateway mesh topology with Agent-to-Agent (A2A) communication. System administrators can manage gateway peers using CLI commands to enable federation across multiple ADEPT deployments.

### A2A CLI Commands

**Prerequisites**:
```bash
export GATEWAY_REGISTRY_URL=http://localhost:8086
```

#### List Registered Peers

```bash
# Table format (default)
agentic a2a list-peers

# JSON format
agentic a2a list-peers --format json

# Simple format (alias: URL)
agentic a2a list-peers --format simple
```

#### Register New Peer Gateway

```bash
# Register peer
agentic a2a register-peer lab-west https://lab-west.example.com/v1

# With description and tags
agentic a2a register-peer lab-west https://lab-west.example.com/v1 \
  --description "West Coast Lab" \
  --tags "production,us-west-2"
```

#### Update Peer Capabilities

```bash
# Add tags (merge, not replace)
agentic a2a update-peer lab-west --add-tags "Opentrons,lab-automation"

# Remove tags
agentic a2a update-peer lab-west --remove-tags "deprecated-tag"

# Update description only (tags preserved)
agentic a2a update-peer lab-west --description "Updated Lab West"
```

#### Test Peer Connectivity

```bash
# Test connection
agentic a2a test-connection lab-west

# Verbose mode
agentic a2a test-connection lab-west --verbose
```

#### Remove Peer

```bash
# Remove peer (with confirmation)
agentic a2a remove-peer lab-west

# Remove peer (skip confirmation)
agentic a2a remove-peer lab-west --yes
```

### Complete Workflow Example

```bash
# 1. List existing peers
agentic a2a list-peers

# 2. Register new peer gateway
agentic a2a register-peer test-peer https://test.example.com/v1 \
  --description "Test Gateway" \
  --tags "staging,test"

# 2.5. Update peer capabilities (add Opentrons tag)
agentic a2a update-peer test-peer --add-tags "Opentrons"

# 3. Generate A2A token for peer
agentic a2a generate-token --groups gateway-service

# 4. Test connectivity
agentic a2a test-connection test-peer

# 5. Remove peer when no longer needed
agentic a2a remove-peer test-peer --yes
```

### Validation

```bash
# Unit tests
pytest tests/unit/agentic_framework_sdk/cli/test_a2a_commands.py -v
# Expected: 22/22 tests passing

# E2E tests (requires running Gateway Registry)
pytest tests/e2e/test_a2a_cli_commands.py -v --mark e2e
# Expected: 20/20 tests passing
```

**References**:
- Implementation: `src/agentic_framework_sdk/cli/a2a_commands.py`
- Unit Tests: `tests/unit/agentic_framework_sdk/cli/test_a2a_commands.py`
- E2E Tests: `tests/e2e/test_a2a_cli_commands.py`

### Learning Resources

**[A2A Gateway Mesh Workshop](../examples/a2a-workshop/README.md)** - 2-hour hands-on workshop for system administrators:

**Workshop Contents**:
- Federation protocol concepts and architecture diagrams
- Gateway mesh communication patterns
- Security testing with JWT tokens and service accounts
- Credential management with CLI tools
- Practical exercises with validation scripts
- Real-world federation scenarios (multi-organization, multi-region, hybrid cloud)

**What You'll Learn**:
- How to establish trust between independent ADEPT deployments
- Secure token generation and validation
- Peer gateway registration and health monitoring
- Troubleshooting federation issues

**IP-Based VM Federation Setup**:

For system administrators deploying ADEPT across Azure/AWS VMs using only IP addresses:

**[Quick-Start Checklist](guides/A2A_IP_BASED_VM_FEDERATION_QUICKSTART.md)** (15-20 minutes)
- **Self-signed certificates**: OpenSSL commands with Subject Alternative Name for IP addresses
- **Why self-signed?**: Let's Encrypt doesn't support IP-only certificates
- **Credential setup**: Auto-discovery from ADEPT installation (no manual configuration)
- **Mutual registration**: Bidirectional peer registration workflow
- **Troubleshooting**: Quick fixes for SSL, DNS, and firewall issues

**[Complete Federation Guide](guides/A2A_IP_BASED_VM_FEDERATION_GUIDE.md)** (45-60 minutes)
- **Architecture overview**: Three-tier network topology
- **Certificate generation**: Detailed OpenSSL configuration with IP in SAN
- **nginx configuration**: SSL/TLS setup for IP-based certificates
- **Token/secret exchange**: Clarifies NO credential exchange needed between VMs!
- **Comprehensive troubleshooting**: SSL errors, DNS resolution, Keycloak authentication, firewall rules
- **Security considerations**: Production vs development deployment patterns

**Credential Management**:

Modern CLI credential management for multi-environment deployments:

```bash
# Setup credentials with auto-discovery from ADEPT installation
agentic auth cred-setup --auto-discover --profile default --force

# Verify credentials work
agentic auth cred-test --profile default

# Use profile in A2A commands
agentic a2a list-peers --profile production
agentic a2a register-peer aws-gateway https://54.210.89.123/v1 --profile production
agentic a2a test-connection aws-gateway --profile production --verbose
```

**Credential Features**:
- **Three-tier discovery**: Profile -> ADEPT installation -> environment variables
- **Secure storage**: `~/.adept-agentic/credentials` with chmod 600 permissions
- **Multi-profile support**: Separate profiles for dev, staging, production
- **Backward compatible**: Existing environment variable workflows still work
- **Auto-discovery**: Automatically finds credentials from ADEPT deployment

**Management Commands**:
```bash
agentic auth cred-setup    # Setup new profile
agentic auth cred-list     # List all profiles
agentic auth cred-test     # Test authentication
agentic auth cred-show     # Show credentials (redacted)
agentic auth cred-remove   # Delete profile
agentic auth cred-export   # Export as env or JSON
```

**Documentation**:
- Implementation Plan: `docs/implementation-plans/CLI_CREDENTIAL_MANAGEMENT_IMPLEMENTATION_PLAN.md`
- Federation Guide: `docs/guides/A2A_IP_BASED_VM_FEDERATION_GUIDE.md` (833 lines)
- Quick-Start: `docs/guides/A2A_IP_BASED_VM_FEDERATION_QUICKSTART.md` (386 lines)

**Key Insight**: When federating two VMs, each VM uses its own credentials to authenticate to its own Keycloak instance. No credential exchange or token sharing is needed between VMs - only IP addresses and gateway URLs are shared!

#### Cross-VM JWKS Federation

**When needed**: When A2A delegation crosses VMs with independent Keycloak instances that use the same internal hostname (`http://keycloak:8180`).

**Problem**: The forwarded user token's signing key (kid) exists only in the originating VM's Keycloak. The receiving VM's `validate_jwt_multi_stack()` fetches JWKS from its **local** Keycloak (because the issuer URL matches), which doesn't have the peer's keys.

**Configuration**: Add `A2A_TRUSTED_PEER_JWKS_URLS` to `.env` on **both VMs**, pointing to the peer's JWKS endpoint via nginx_proxy:

```bash
# On VM-A (.env)
A2A_TRUSTED_PEER_JWKS_URLS=https://<peer-b-ip>/realms/master/protocol/openid-connect/certs

# On VM-B (.env)
A2A_TRUSTED_PEER_JWKS_URLS=https://<peer-a-ip>/realms/master/protocol/openid-connect/certs

# Multiple peers (comma-separated)
A2A_TRUSTED_PEER_JWKS_URLS=https://peer1/realms/master/protocol/openid-connect/certs,https://peer2/realms/master/protocol/openid-connect/certs
```

After updating `.env`, rebuild the affected services:
```bash
make rebuild-gateway
make rebuild-orchestrator
```

**Verification**:
```bash
# Check orchestration_service logs for peer JWKS activity
docker logs orchestration_service 2>&1 | grep "A2A_USER_TOKEN\|peer JWKS"

# Expected on successful cross-VM delegation:
# Found kid <kid> in peer JWKS: https://<peer_ip>/realms/master/protocol/openid-connect/certs
```

**Troubleshooting**:

| Symptom | Cause | Fix |
|---------|-------|-----|
| "Unable to find a matching key" on user token | Missing `A2A_TRUSTED_PEER_JWKS_URLS` | Add peer JWKS URL to `.env` |
| "Failed to fetch peer JWKS" | Network/firewall issue | Verify HTTPS connectivity to peer nginx_proxy |
| Service token works but user token fails | Peer JWKS only in `keycloak_context_builder`, not `core/auth.py` | Upgrade to latest code |

---

### Client-Side Certificate Trust for External Tools

ADEPT uses a self-signed TLS certificate on its nginx proxy. Developer workstations connecting to the ADEPT host must trust this certificate in the OS trust store **and** in application-specific trust stores (Node.js, Python, browsers each use different CA bundles). Simply trusting the cert at the OS level is not sufficient for all tools.

For the complete step-by-step guide covering macOS, Linux, and Windows for all client types (Node.js/VS Code, Python, curl, browsers), see **[Client-Side Certificate Trust Guide](guides/CLIENT_CERTIFICATE_TRUST.md)**.

**Quick reference**: The certificate is at `data/nginx_certs/api.agentic.local.crt` on the ADEPT host. Copy it to your workstation, add it to the OS trust store, then configure `NODE_EXTRA_CA_CERTS` (for Node.js/VS Code) and `REQUESTS_CA_BUNDLE` or `SSL_CERT_FILE` (for Python).

---

## External Tool Management

### Overview

System administrators can register, list, and delete external tools that extend the agent's capabilities beyond the 18 built-in MCP tools. External tools are persisted in Redis and provisioned to agents based on ACL group membership.

### Supported Protocols

| Protocol | Transport | Use Case | Example |
|----------|-----------|----------|---------|
| `http` | Raw HTTP POST | REST APIs, webhooks | `http://my-service:8080/api` |
| `mcp` | MCP JSON-RPC via FastMCP Client | FastMCP/MCP servers | `http://opentrons_mcp_server:9003` |
| `stdio` | Subprocess stdin/stdout | Local CLI tools | `python3,-m,my_tool` |

### CLI Commands

```bash
# List all registered tools (built-in + external)
agentic tools list

# Register an MCP tool (e.g., OpenTrons liquid handling server)
agentic tools register execute_opentrons_protocol \
  -d "Execute an OpenTrons liquid handling protocol" \
  -p mcp \
  -u http://opentrons_mcp_server:9003 \
  --tool-name execute_opentrons_protocol_tool \
  --args-schema '{"protocol_json":{"type":"object","description":"Protocol spec"},"dry_run":{"type":"boolean","description":"Validate without executing","default":true}}' \
  --acl-global \
  --username admin --password admin

# Register an HTTP tool
agentic tools register my_rest_tool \
  -d "Call a REST API" \
  -p http \
  -u http://my-service:8080/api/endpoint \
  --username admin --password admin

# Delete a tool
agentic tools delete execute_opentrons_protocol -y \
  --username admin --password admin
```

### Key Concepts

- **`--tool-name`** (MCP only): Maps to the `@mcp.tool()` function name on the remote server. May differ from the registered tool name.
- **`--url`** (MCP): The base URL of the MCP server. The FastMCP Client appends `/mcp` internally.
- **`--args-schema`**: JSON string defining tool parameters with types, descriptions, and defaults.
- **`--acl-global`**: Makes the tool available to all authenticated users. Use `--acl-groups` for group-based access.
- Authentication requires `admin` role via `--username/--password` or `ADMIN_USERNAME`/`ADMIN_PASSWORD` env vars.

### Validation

```bash
# Unit tests (53 tests including MCP protocol)
make validate-unit-external-tool-manager

# Verify Redis persistence
docker exec redis redis-cli KEYS "external_tool:*"
```

### References

- Implementation: `src/agentic_framework_pkg/orchestration_service/external_tool_manager.py`
- CLI: `src/agentic_framework_sdk/cli/main.py` (tools_register command)
- Tests: `tests/unit/agentic_framework_pkg/orchestration_service/test_external_tool_manager.py`

### OpenTrons MCP Server Lifecycle

The OpenTrons MCP server has a dedicated Makefile (`examples/opentrons_mcp_server/Makefile`) for automated build, registration, and teardown. Delegating targets are also available from the project root Makefile.

**From project root**:
```bash
make opentrons-setup          # Full lifecycle: build + start + register + verify
make opentrons-rebuild        # Rebuild from scratch + re-register tool
make opentrons-teardown       # Stop container + deregister tool
make opentrons-register       # Register MCP tool via agentic CLI
make opentrons-deregister     # Deregister tool from ADEPT
make opentrons-health         # Check server health endpoint
make opentrons-smoke-test     # E2E test via Response API
make opentrons-logs           # Tail container logs
```

**From `examples/opentrons_mcp_server/`**:
```bash
make setup            # Full lifecycle
make rebuild          # Rebuild + re-register
make teardown         # Stop + deregister
make register-tool    # Register only
make deregister-tool  # Deregister only
make verify-tool      # Verify in Redis + Gateway API
make health           # Health check
make smoke-test       # E2E smoke test
make help             # Show all targets
```

**Configuration overrides** (environment variables):
```bash
ADMIN_USER=admin        # Admin username (default: admin)
ADMIN_PASS=admin        # Admin password (default: admin)
KEYCLOAK_URL=http://localhost:8180  # Keycloak URL
GATEWAY_URL=http://localhost:8083   # Agent Gateway host port
```

The Makefile auto-detects the `agentic` CLI from `.venv311/`, `.venv/`, or PATH. Prerequisites: ADEPT core stack running and `agentic` CLI installed (`pip install -e src/` from project root).

### Federated MCP Server Stacks

ADEPT supports federated MCP server stacks deployed across multiple hosts and facilities. Each stack registers its tools with the ADEPT core tool registry. For the holistic integration roadmap (Globus IdP, SPIFFE/SPIRE, token exchange, 28 Globus tools), see:

- **Federated Platform Integration Tracker**: `docs/implementation-plans/FEDERATED_PLATFORM_INTEGRATION_TRACKER.md`
- **Cross-Stack Parity Analysis**: `examples/docs/MCP_SERVER_STACK_PARITY_ANALYSIS.md`
- **Globus IdP Integration Plan**: `docs/implementation-plans/GLOBUS_IDP_INTEGRATION_PLAN.md`

**Registered stacks** (as of 2026-03-30): EMSL Sandbox (6 tools), Slurm HPC (6 tools), Biofoundation (5 tools), VFM (4 tools), Academy (4 tools) -- 29 total external tools via `make list-registered-tools`.

### EMSL Hybrid Cloud Sandbox

The EMSL sandbox is a **remote MCP server** deployed on an internal Rocky 9
VM (`<your-hostname>`), connected to the AWS EC2 ADEPT gateway
over HTTPS. It is the first hybrid cloud integration in ADEPT -- an on-premises
lab instrument server accessible from the cloud.

**Infrastructure differences from standard ADEPT deployment:**

| Component | AWS/Azure ADEPT | EMSL Rocky 9 |
|-----------|----------------|--------------|
| Container runtime | Docker CE (root daemon) | Rootless Podman 5.6.0 |
| Storage driver | overlay2 (`/var/lib/docker/`) | VFS (`/data/podman-storage-*/`, local XFS) |
| Home directory | Local EBS/disk | NFS-mounted |
| Compose | `docker compose` (native) | `podman compose` -> Docker Compose plugin |
| Build | `docker compose build` | `podman build` directly (compose can't resolve local images) |
| TLS | Not required (internal) | Local CA cert (HTTPS :443, TLS 1.3) |
| Execution method | subprocess or DinD | subprocess only (rootless, no privileged DinD) |

**Operational reference**: `examples/emsl_sandbox/docs/EMSL_DEPLOYMENT_OPERATIONS_GUIDE.md`

#### Podman Storage Configuration

Podman storage is configured in `~/.config/containers/storage.conf` on the EMSL host:

```toml
[storage]
driver = "vfs"
graphroot = "/data/podman-storage-<username>"
runroot = "/data/podman-run-<username>"
```

**Critical constraints:**
- **VFS driver required** -- the home directory is NFS-mounted, and overlay/fuse-overlayfs
  is incompatible with NFS (no xattr, hardlink, or d_type support)
- **Storage on `/data/`** (local XFS) -- persistent across reboots. Originally on `/tmp/`
  which caused container filesystem corruption via `systemd-tmpfiles` cleanup
- **Do NOT move storage to `/home/`** -- NFS performance and compatibility issues

#### TLS Certificate Management

The EMSL sandbox uses a local CA for HTTPS. Certificates are generated on the
EMSL VM and the CA cert is distributed to EC2 for trust store injection.

```bash
# Generate certs (EMSL VM)
cd examples/emsl_sandbox
SANDBOX_HOST_IP=<your-server-ip> make generate-certs

# Install CA on EC2 (automatic via docker-compose entrypoint)
# See: scripts/install-emsl-ca-cert.sh
```

Full TLS documentation: Section 1.6 of the EMSL operations guide.

#### Common Administrative Tasks

```bash
# Full rebuild after storage reset (EMSL VM)
cd examples/emsl_sandbox
make build-base-images    # Rebuild os-base + deps-base (if wiped)
make build                # Build sandbox image
make start                # Start all 3 services

# Health check
make health               # Check redis + MCP server + nginx (HTTP + HTTPS)

# Register tools on EC2 gateway
make register-tools       # Registers 6 EMSL sandbox tools

# Verify Python runtime (after rebuild)
podman exec sandbox_mcp_server /app/.venv/bin/python -c "print('hello')"
```

#### Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `init_fs_encoding` Python crash | Container filesystem corrupted (VFS on `/tmp/`) | Migrate storage to `/data/`, rebuild container |
| `make start` -> `connection refused` | Podman API socket not running | `make start` auto-starts it via `ensure-podman-socket` |
| `make build` -> `requested access denied` | Docker Compose can't resolve podman local images | Already fixed -- Makefile uses `podman build` directly |
| TLS `WRONG_VERSION_NUMBER` | SSH tunnel forwarding to HTTP port instead of HTTPS | Check tunnel target: should be `localhost:443` |
| TLS `CERTIFICATE_VERIFY_FAILED` | CA cert not installed on EC2 | Mount `ca.crt` and run `install-emsl-ca-cert.sh` |

### EMSL Sandbox Kubernetes Deployment

The EMSL sandbox is now available as a **standalone Helm chart** for deployment to on-prem Kubernetes clusters. This is a stop-gap before the full ADEPT stack migration.

**Chart**: `infra/helm/emsl-sandbox/` -- deploys Redis, sandbox_mcp_server, and nginx into the `class` namespace.

#### Prerequisites

```bash
# 1. Image pull secret for container registry
kubectl create secret docker-registry my-registry-secret \
  --docker-server=<your-registry> \
  --docker-username=<user> --docker-password=<pass> -n class

# 2. Gurobi license (optional)
kubectl create secret generic emsl-sandbox-gurobi \
  --from-file=gurobi.lic=/path/to/gurobi.lic -n class
```

#### Installation

```bash
cd infra/helm/emsl-sandbox/

# Build and push images
make build-images && make push-images

# Install
helm install emsl-sandbox . --namespace class \
  --set secrets.sandboxFilesToken="$(openssl rand -hex 32)" \
  --set sandbox.gurobi.licenseSecretName=emsl-sandbox-gurobi
```

#### Verification

```bash
# Check pods
kubectl get pods -n class -l app.kubernetes.io/instance=emsl-sandbox

# Health checks
kubectl port-forward -n class svc/emsl-sandbox-sandbox 8082:8082
curl http://localhost:8082/health   # {"status": "ok"}

kubectl port-forward -n class svc/emsl-sandbox-nginx 8080:80
curl http://localhost:8080/health   # sandbox-proxy healthy

kubectl exec -n class deploy/emsl-sandbox-redis -- redis-cli ping  # PONG
```

#### Key Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `secrets.sandboxFilesToken` | Token for /files/ endpoint | Auto-generated |
| `sandbox.backend` | Execution method | `subprocess` |
| `sandbox.runUser` | OS user for subprocess | `<your-user>` |
| `sandbox.gurobi.enabled` | Enable Gurobi solver | `true` |
| `nginx.allowedIPs` | IPs for /mcp access | `[<your-server-ip>]` |
| `persistence.sharedUploads.storageClassName` | NFS storage class | `<your-storage-class>` |
| `ingress.host` | Ingress hostname | `<your-hostname>` |

#### Upgrade and Rollback

```bash
# Upgrade
helm upgrade emsl-sandbox . -n class --set sandbox.image.tag=v2.0.0

# Rollback
helm history emsl-sandbox -n class
helm rollback emsl-sandbox <revision> -n class

# Uninstall
helm uninstall emsl-sandbox -n class
kubectl delete pvc -n class -l app.kubernetes.io/instance=emsl-sandbox
```

**Chart README**: `infra/helm/emsl-sandbox/README.md`

---

## Service API Token Management

### Overview: Service Tokens vs User JWT Tokens

**Service API tokens** provide an alternative authentication method for non-interactive access, ideal for automation, CI/CD, and external service integration.

**Architecture**:
- **Redis Database 1**: Primary storage for external service tokens
- **Dual-Mode Validation**: Redis first, file fallback (Phase 1)
- **TokenCache**: 1-hour in-memory cache (99% hit rate)
- **Atomic Operations**: Lua scripts prevent race conditions
- **Zero-Downtime**: Instant token creation/revocation (no service restart)

#### Comparison Matrix

| Feature | Service API Token | User JWT Token |
|---------|-------------------|----------------|
| **Authentication** | Bearer sk-service-* | Keycloak OAuth2 flow |
| **Lifespan** | 90 days (default) | 8 hours (access token) |
| **Refresh Required** | No | Yes (refresh_token) |
| **Use Case** | Services, automation | End-user interactive |
| **Identity** | Service username | Actual user (sub) |
| **Complexity** | Low (just API key) | High (OIDC flow) |
| **Storage** | Redis DB 1 + file (Phase 1) | Keycloak database |
| **Performance** | 0.01ms (cached), 0.15ms (uncached) | OIDC flow overhead |

#### When to Use Service Tokens

**Use Service Tokens When**:
- Non-interactive automation (CI/CD pipelines, cron jobs)
- Long-running background processes
- External service integration (n8n, OpenWebUI, custom services)
- Testing and validation scripts
- No user login UI required

**Use User JWT When**:
- Interactive web applications (Streamlit, JupyterLab)
- User-initiated actions requiring attribution
- Need actual user identity for authorization
- Session management tied to user login/logout

### Redis-Based Token Management

**Key Enhancement**: Service API tokens are now stored in **Redis Database 1** for instant synchronization across services, replacing the unstable file-based SIGHUP hot-reload system (20% failure rate).

#### Architecture Overview

**Token Types**:
1. **Bootstrap Tokens** (Hardcoded in auth.py):
   - `sk-service-openwebui-STABLE-PERSISTENT-v1-...`
   - `sk-service-n8n-STABLE-PERSISTENT-v1-...`
   - Never stored in Redis (eliminates circular dependency)
   - Used for initial service startup

2. **External Tokens** (Redis Database 1):
   - Generated via CLI or Management UI
   - Format: `sk-service-{service_name}-{32-char-random}`
   - TTL: 1-365 days (default 90)
   - Dynamic creation/revocation without service restart

**Token Validation Flow** (Dual-Mode - Phase 1):
```
HTTP Request -> Authorization: Bearer sk-service-...
  |
1. Check BOOTSTRAP_TOKENS (hardcoded, 0.01ms)
  | (if not bootstrap)
2. Check TokenCache (1-hour in-memory cache, 0.01ms, 99% hit rate)
  | (if cache miss)
3. Check Redis Database 1 (0.15ms, atomic, always up-to-date)
  | (if not found in Redis - Phase 1 fallback only)
4. Check FILE (SERVICE_API_KEYS_CONFIG, 0.01ms, backward compatibility)
  |
5. Return 200 OK or 401 Unauthorized
```

**Performance Benefits**:
- Token operations: **210x faster** (0.5ms vs 105ms with SIGHUP)
- Token validation: ~0.01ms average (negligible impact)
- Cache hit rate: 99% (1-hour TTL)
- Memory overhead: +51 KB per service

**Security Enhancements**:
- Input validation: service_name alphanumeric check prevents SQL injection
- Atomic Lua scripts: Prevent race conditions across 4 uvicorn workers
- Cache consistency: Revocation clears cache automatically
- Token hashing: SHA-256 first 16 chars in Redis keys (prevents exposure)

**Documentation**:
- **Quick Start Guide**: `docs/guides/SERVICE_TOKEN_MANAGEMENT_QUICK_START.md`

### Creating Service API Tokens

**Script**: `scripts/deps/create_service_api_token.py`

**Quick Reference**:
```bash
# Create service token (90-day default)
make create-service-token NAME=my-automation GROUPS=notebook-users TTL_DAYS=90

# Create token with custom TTL (30 days)
make create-service-token NAME=short-lived GROUPS=gateway-agents TTL_DAYS=30

# Create token with description
make create-service-token NAME=ci-pipeline GROUPS=notebook-users DESCRIPTION="CI/CD automation"

# List all tokens
make list-service-tokens

# Revoke token
make revoke-service-token TOKEN=sk-service-my-automation-abc123
```

**CLI Usage**:
```bash
# Create service token
python scripts/deps/create_service_api_token.py \
    --name my-automation-service \
    --groups notebook-users \
    --description "CI/CD pipeline automation" \
    --ttl-days 90

# List all tokens (with status: active, expired, revoked)
python scripts/deps/create_service_api_token.py --list

# Revoke token
python scripts/deps/create_service_api_token.py --revoke sk-service-my-automation-abc123
```

### Token Lifecycle Management

#### Token Creation Best Practices

1. **Use Descriptive Names**: Clearly identify the service (e.g., `ci-pipeline`, `n8n-automation`, `monitoring-service`)
2. **Set Appropriate TTL**: Balance security and operational overhead
   - Short-lived (7-30 days): High-security environments
   - Medium (90 days default): Standard operations
   - Long-lived (1 year): Stable, low-risk integrations
3. **Document Purpose**: Always include description for audit trail
4. **Assign Minimal Groups**: Only grant necessary permissions

#### Token Rotation Workflow

```bash
# 1. List tokens to find expiring ones
make list-service-tokens
# Output shows days_remaining for each active token

# 2. Create replacement token (before expiration)
make create-service-token NAME=ci-pipeline-v2 GROUPS=notebook-users TTL_DAYS=90

# 3. Update service configuration with new token
# (Service-specific - update environment variables, secret managers, etc.)

# 4. Verify new token works
export ADEPT_SERVICE_API_TOKEN="sk-service-ci-pipeline-v2-..."
python examples/openai_client_service_token_example.py

# 5. Revoke old token
make revoke-service-token TOKEN=sk-service-ci-pipeline-v1-...

# 6. Audit: Verify old token no longer works
curl -H "Authorization: Bearer sk-service-ci-pipeline-v1-..." \
     https://api.agentic.local/v1/models
# Expected: 401 Unauthorized
```

#### Token Audit and Monitoring

```bash
# View all tokens with status
make list-service-tokens

# Check token metadata
docker exec orchestration_service cat /app/credentials/service_api_tokens_metadata.json | jq .

# Verify SERVICE_API_KEYS_CONFIG
docker exec orchestration_service bash -c "
    python3 -c \"
from agentic_framework_pkg.core.secrets_manager import get_secret
import json
config = json.loads(get_secret('SERVICE_API_KEYS_CONFIG'))
print(json.dumps(config, indent=2))
    \"
"
```

### Token Activation

Tokens created via `make create-service-token` are stored in **Redis Database 1** and are available instantly across all services -- no restart or reload is required.

```bash
# 1. Create token
make create-service-token NAME=my-new-service GROUPS=notebook-users

# 2. Use immediately (no reload step needed)
curl -H "Authorization: Bearer sk-service-my-new-service-..." \
     https://api.agentic.local/v1/models
# Expected: 200 OK with model list
```

**When rebuild IS required** (not token-related changes):
- Code changes in auth.py
- Environment variable changes (SECRET_RETRIEVAL_METHOD, etc.)
- Docker image or dependency updates

### Using Service Tokens

#### Example 1: OpenAI-Compatible Client

```python
import openai
import os

# Load service token from environment
service_token = os.getenv("ADEPT_SERVICE_API_TOKEN")

# Create OpenAI client
client = openai.OpenAI(
    base_url="https://api.agentic.local/v1",
    api_key=service_token
)

# Make chat completion call
response = client.chat.completions.create(
    model="agentic-framework:scientific-agent-v1",
    messages=[
        {"role": "user", "content": "What is the capital of France?"}
    ]
)

print(response.choices[0].message.content)
```

**Complete Example**: `examples/openai_client_service_token_example.py`

#### Example 2: External Service Integration (n8n, OpenWebUI)

```bash
# 1. Create token for external service
make create-service-token NAME=n8n-integration GROUPS=gateway-agents TTL_DAYS=365

# 2. Configure external service
# n8n: Add as HTTP Request authentication header
# OpenWebUI: Configure in OpenAI API settings
# Custom service: Store in secret manager

# 3. Test integration
curl -H "Authorization: Bearer sk-service-n8n-integration-..." \
     https://api.agentic.local/v1/chat/completions \
     -d '{"model": "agentic-framework:scientific-agent-v1", "messages": [{"role": "user", "content": "Hello"}]}'
```

### JupyterLab oauth2_proxy Configuration

**Issue**: Users created via Management UI don't have verified emails, causing 500 Internal Server Error when accessing JupyterLab.

**Solution**: Configure oauth2_proxy to allow unverified emails in development environments.

#### Email Verification Architecture

**Two-Layer Solution**:
1. **oauth2_proxy Flag**: `OAUTH2_PROXY_INSECURE_OIDC_ALLOW_UNVERIFIED_EMAIL=true`
   - Applies to all users (system-wide configuration)
   - Development-only (not for production)
   - Location: `docker-compose.core.yaml` lines 625-674

2. **Bootstrap Script**: Sets `emailVerified: True` during user creation
   - Location: `scripts/deps/bootstrap_keycloak.py` lines 392, 406, 416
   - Belt-and-suspenders approach
   - Works for users created via Makefile targets

#### Configuration

**docker-compose.core.yaml** (oauth2_proxy service):
```yaml
oauth2_proxy:
  environment:
    - OAUTH2_PROXY_INSECURE_OIDC_ALLOW_UNVERIFIED_EMAIL=true  # Allow unverified emails (dev only)
```

**Verification**:
```bash
# 1. Verify environment variable is set
docker inspect oauth2_proxy | grep UNVERIFIED_EMAIL

# 2. Test JupyterLab access
curl -I https://api.agentic.local/jupyter/
# Expected: 302 redirect to Keycloak login (not 500 error)

# 3. Check user email verification status
docker exec postgres psql -U admin -d keycloak -c \
    "SELECT username, email, email_verified FROM user_entity WHERE username='paul';"
```

#### Production Considerations

**For Production Deployments**:
1. Remove `OAUTH2_PROXY_INSECURE_OIDC_ALLOW_UNVERIFIED_EMAIL=true` flag
2. Implement email verification UI in Management UI
3. Require users to verify emails before JupyterLab access
4. Set up SMTP for verification emails

**Development vs Production**:
| Environment | Email Verification | Rationale |
|-------------|-------------------|-----------|
| **Development** | Disabled (oauth2_proxy flag) | UX priority, no real emails |
| **Staging** | Enabled (no flag) | Test production flow |
| **Production** | Enabled (enforce) | Security requirement |

---

## Keycloak Administration

### Keycloak Admin CLI

**Accessing Keycloak Admin CLI**:
```bash
# 1. Configure admin credentials
docker exec keycloak /opt/keycloak/bin/kcadm.sh config credentials \
    --server http://localhost:8180 \
    --realm master \
    --user admin \
    --password admin

# 2. Get list of users
docker exec keycloak /opt/keycloak/bin/kcadm.sh get users -r master

# 3. Get list of groups
docker exec keycloak /opt/keycloak/bin/kcadm.sh get groups -r master

# 4. Get list of clients
docker exec keycloak /opt/keycloak/bin/kcadm.sh get clients -r master --fields clientId,enabled
```

### Keycloak Web UI

**Access URL**: `https://api.agentic.local/admin/master/console/`

**Login**:
- Username: `admin`
- Password: (from `KC_BOOTSTRAP_ADMIN_PASSWORD` environment variable)

**Common Tasks**:
1. **View Users**: Realm Settings -> Users
2. **Manage Groups**: Realm Settings -> Groups
3. **Client Configuration**: Clients -> Select client -> Settings
4. **Session Management**: Sessions -> View active sessions
5. **Event Logs**: Realm Settings -> Events -> View login/logout events

### Managing OAuth2 Clients

**List OAuth2 Clients**:
```bash
# List all clients with redirect URIs
docker exec keycloak /opt/keycloak/bin/kcadm.sh get clients -r master \
    --fields clientId,redirectUris | jq .
```

**Update Client Redirect URIs** (e.g., for SSH port forwarding):
```bash
# Update JupyterLab client redirect URIs
docker exec keycloak /opt/keycloak/bin/kcadm.sh update clients/<client-internal-id> -r master \
    -s 'redirectUris=["https://localhost:8443/oauth2/callback","https://localhost:8080/oauth2/callback"]'
```

### Configuring NGINX for Public FQDN Access

**Use Case**: When the ADEPT stack is accessible via a public FQDN (e.g., `your-adept-host.example.com`)
or external IP, nginx must be configured to accept requests with that hostname.

**Symptom without this configuration**: `ERR_INVALID_RESPONSE` in browser, or `application/octet-stream`
content-type on 404 responses.

**Step 1: Set the NGINX_PUBLIC_FQDN environment variable**

```bash
# Add to .env (skip if local-only / api.agentic.local deployment)
echo 'NGINX_PUBLIC_FQDN=your-adept-host.example.com' >> .env
```

When `NGINX_PUBLIC_FQDN` is empty (default), nginx only responds to `api.agentic.local`
and `localhost`. This is safe for local-only deployments with no DNS entry.

**Step 2: Rebuild nginx_proxy**

```bash
sudo make rebuild-nginx-proxy
```

**Step 3: Verify**

```bash
# Root should return JSON API index
curl -ks https://your-adept-host.example.com/ | python3 -m json.tool
# {"name": "ADEPT Agentic Framework", "version": "v1", "endpoints": {...}}

# 404s should return application/json (not octet-stream)
curl -kI https://your-adept-host.example.com/nonexistent | grep content-type
# content-type: application/json

# Confirm server_name includes public FQDN
sudo docker exec nginx_proxy grep server_name /etc/nginx/conf.d/api.local.conf
# server_name api.agentic.local localhost your-adept-host.example.com;
```

**Step 4: Register OAuth2 redirect URIs** (required for JupyterLab, OpenWebUI)

After configuring the FQDN in nginx, you must also register the OAuth2 callback URL
in Keycloak. See the next section.

**Validation**:
```bash
sudo make validate-nginx-public-fqdn       # Both unit + E2E
sudo make validate-nginx-public-fqdn-unit   # Unit only (no stack required)
sudo make validate-nginx-public-fqdn-e2e    # E2E only (nginx_proxy must be running)
```

**Ansible Automation**: If using Ansible, run `post-bootstrap.yml` after the stack is healthy
to automate OAuth2 redirect URI registration and external access verification:
```bash
cd deployment/ansible
ansible-playbook playbooks/post-bootstrap.yml -i inventory/your-site.ini
```

For OAuth2 redirect URI registration, persistence, and troubleshooting when accessing ADEPT via IP addresses, public FQDNs, or custom hostnames, see [OAuth2 Configuration](#oauth2-configuration).

---

## OAuth2 Configuration

This section consolidates all OAuth2 redirect URI management: registration, persistence across rebuilds, PUBLIC_BASE_URL configuration, and troubleshooting.

### Quick Setup -- Registering OAuth2 Redirect URIs

**Use Case**: When deploying ADEPT on cloud VMs (AWS EC2, Azure VM, on-premises servers) or accessing via custom hostnames, you need to register OAuth2 redirect URIs in Keycloak to enable authentication.

**Common Scenarios**:
- Public FQDN: `https://your-adept-host.example.com/jupyter`
- EC2 public IP: `https://<your-server-ip>/jupyter`
- Azure VM: `https://192.168.1.100/jupyter`
- Custom domain: `https://lab-gateway.university.edu/jupyter`

**Symptom if redirect URI is missing**: Keycloak shows `"Invalid parameter: redirect_uri"` error when accessing JupyterLab or any OAuth2-protected service via the public hostname.

**CRITICAL**: Before registering redirect URIs, ensure `PUBLIC_BASE_URL` in `.env` is set to the **FQDN users type in their browser** -- not an internal IP. This single variable controls the OIDC issuer URL, redirect URI auto-registration, and CORS origins.

```bash
# Step 0: Verify PUBLIC_BASE_URL (most common source of OAuth2 failures)
grep "^PUBLIC_BASE_URL" .env
# MUST match the hostname users access (e.g., https://your-adept-host.example.com)

# Step 1: Bootstrap credentials (creates secrets + registers PUBLIC_BASE_URL redirect URI)
make fix-credentials

# Step 2: Register redirect URIs for ALL access hostnames/IPs
make register-oauth-redirect HOST=your-adept-host.example.com   # FQDN
make register-oauth-redirect HOST=<your-server-ip>              # Private IP (if used)

# Step 3: Verify
make list-oauth-redirects

# Step 4: Test (clear browser cookies or use incognito)
# Browse to https://your-adept-host.example.com/jupyter/
```

**Makefile targets**:

| Target | Usage | Purpose |
|--------|-------|---------|
| `make register-oauth-redirect HOST=<host>` | Add | Register a redirect URI for hostname/IP |
| `make list-oauth-redirects` | Read | List all registered redirect URIs |
| `make remove-oauth-redirect HOST=<host>` | Delete | Remove a stale redirect URI |

These are idempotent, zero-downtime, and use the Keycloak Admin API (no restarts needed).

### PUBLIC_BASE_URL and Multi-Host Access

**`PUBLIC_BASE_URL` is the single most important deployment variable for OAuth2.**

It controls:

| Derived Configuration | Impact |
|----------------------|--------|
| `OAUTH2_PROXY_OIDC_ISSUER_URL=${PUBLIC_BASE_URL}/realms/master` | Where oauth2_proxy exchanges auth codes -- **must match the hostname users see in their browser** |
| Redirect URI auto-registration | `bootstrap_keycloak.py` registers `${PUBLIC_BASE_URL}/oauth2/callback` |
| CORS origins | Controls allowed cross-origin request origins |
| External URLs in API responses | Presigned URLs, file download links |

**Rule**: Set `PUBLIC_BASE_URL` to the **FQDN users type in their browser**. If users access via `https://your-adept-host.example.com`, set it to `https://your-adept-host.example.com` -- NOT an internal IP.

**Why an IP causes failures**: When `PUBLIC_BASE_URL=https://<your-server-ip>` but users access via FQDN, the OIDC issuer context mismatches. The auth code is issued for `https://your-adept-host.example.com/realms/master` but oauth2_proxy tries to exchange it at `https://<your-server-ip>/realms/master`. Keycloak rejects this with `unauthorized_client` -- even though the client secret is correct.

**Setup**:
```bash
# 1. Set PUBLIC_BASE_URL to the primary access FQDN
grep "^PUBLIC_BASE_URL" .env
# Must show: PUBLIC_BASE_URL=https://your-adept-host.example.com

# 2. Bootstrap (auto-registers FQDN redirect URI + sets OIDC issuer)
make fix-credentials

# 3. Register additional access paths (IPs, alternate hostnames)
make register-oauth-redirect HOST=<your-server-ip>

# 4. Verify
make list-oauth-redirects
```

### Persistence Across Rebuilds

OAuth redirect URIs are stored in Keycloak's PostgreSQL database, which uses a **persistent volume** at `./data/postgres_data/` on the host filesystem. They persist across most operations and are only lost when volumes are deleted.

**Persistence Matrix**:

| Operation | Redirect URIs | Re-register Needed? |
|-----------|---------------|---------------------|
| `make rebuild` | Persists | No |
| `make restart` | Persists | No |
| `make stop` + `make start` | Persists | No |
| `docker-compose down` + `up` | Persists | No |
| `make rebuild-orchestrator` | Persists | No |
| **`make teardown`** | **DELETED** | **Yes** |
| **`make erase`** | **DELETED** | **Yes** |

**Credential Drift vs Redirect URI Persistence**: Redirect URIs and client secrets are both stored in Keycloak's PostgreSQL, but they behave differently. After `make rebuild-orchestrator`, redirect URIs are fine but client secrets are regenerated (causing credential drift). Fix with `make fix-credentials`. See [Troubleshooting Issue 3](#issue-3-credential-drift-after-service-restart).

### When You DO Need to Re-Register

1. **First time setup** or **after `make teardown`/`make erase`**:
   ```bash
   make start
   make register-oauth-redirect HOST=your-adept-host.example.com
   make register-oauth-redirect HOST=<your-server-ip>
   ```

2. **Adding a NEW external access point**:
   ```bash
   make register-oauth-redirect HOST=new-hostname.example.com
   ```

### What Gets Registered Automatically

The bootstrap script (`scripts/deps/bootstrap_keycloak.py`) auto-registers these URIs during initial setup:
- `https://api.agentic.local/oauth2/callback` (production FQDN)
- `https://api.agentic.local/jupyter/oauth_callback` (JupyterLab specific)
- `http://localhost:4180/oauth2/callback` (oauth2-proxy standalone)
- `https://localhost:8443/oauth2/callback` (SSH tunnel)
- Various localhost port variants and custom ports from `CUSTOM_OAUTH_PORTS`

### Optional: Add webOrigin for JavaScript Integration

webOrigin is only required if your web applications make **client-side JavaScript calls to Keycloak** (JavaScript token refresh, Keycloak JS adapter, SPAs).

**Symptom if webOrigin is missing**: Browser console shows CORS errors when making direct calls to Keycloak endpoints.

**Add webOrigin manually** (only if you see CORS errors):

```bash
CLIENT_UUID=$(docker exec postgres psql -U admin -d keycloak -t -A -c \
  "SELECT id FROM client WHERE client_id = 'jupyterlab-client';")

docker exec postgres psql -U admin -d keycloak -c \
  "INSERT INTO web_origins (client_id, value)
   VALUES ('$CLIENT_UUID', 'https://<your-server-ip>')
   ON CONFLICT DO NOTHING;"

docker restart keycloak && sleep 15
```

**Note**: Basic OAuth2 redirect flows (server-side) only need `redirect_uri`. webOrigin is only needed for client-side JavaScript calls to Keycloak.

### Checking Current Registered URIs

```bash
# Recommended: Python management script
docker exec orchestration_service python3 /app/scripts/nginx_proxy/manage_redirect_uris.py list

# Alternative: SQL query
docker exec postgres psql -U admin -d keycloak -c \
  "SELECT c.client_id, r.value
   FROM client c
   JOIN redirect_uris r ON c.id = r.client_id
   WHERE c.client_id = 'jupyterlab-client'
   ORDER BY r.value;"
```

### Troubleshooting OAuth2 Issues

**Common failure sequence** (three errors that often occur in order):

| Error | Symptom | Root Cause | Fix |
|-------|---------|------------|-----|
| `unauthorized_client` (secrets mismatch) | 500 on `/oauth2/callback` | Bootstrap regenerated secrets but oauth2_proxy has old one | `make fix-credentials` |
| `Invalid parameter: redirect_uri` | Keycloak error page | FQDN not in Keycloak's redirect URI allow-list | `make register-oauth-redirect HOST=<fqdn>` |
| `unauthorized_client` (issuer mismatch) | 500 despite matching secrets | `PUBLIC_BASE_URL` uses IP but users access via FQDN | Fix `PUBLIC_BASE_URL` in `.env`, recreate oauth2_proxy |

**After `make teardown` + `make start`**: JupyterLab shows "invalid_redirect_uri" because all URIs were deleted with the volume. Re-register with `make register-oauth-redirect HOST=<your_host>`.

**After `register_jupyterlab_oauth_redirect_uri.sh`**: 500 error with "invalid_client_credentials" means credential drift. Fix with `docker restart oauth2_proxy` or `make fix-credentials`.

**Secret verification**:
```bash
DB_SECRET=$(docker exec postgres psql -U admin -d keycloak -t -A -c \
  "SELECT secret FROM client WHERE client_id = 'jupyterlab-client';")
FILE_SECRET=$(cat deployment/local/docker-compose/.env-keycloak-credentials-dir/JUPYTERLAB_CLIENT_SECRET)
[ "$DB_SECRET" = "$FILE_SECRET" ] && echo "Secrets match" || echo "Secret mismatch - run make fix-credentials"
```

### Volume Persistence Architecture

**Persistent Volumes** (survive rebuilds):
```
./data/
├── postgres_data/         # Keycloak database (OAuth config)
├── redis_data/            # Session state, file metadata
├── uploaded_files/        # User uploaded files
├── rag_indexes/           # Vector indexes
└── jupyter_data/          # JupyterLab notebooks
```

### Related Documentation

- **OAuth2 Redirect URI Management Guide**: `docs/guides/OAUTH2_REDIRECT_URI_MANAGEMENT.md`
- **OAuth Architecture**: `docs/implementation-reports/JUPYTERLAB_AUTHENTICATION_FLOW_WITH_PORT_FORWARDING.md`

---

## Credential Management

### CLI Bootstrap (Host Machine)

To configure the `agentic` CLI on the host machine (outside Docker):

```bash
# Auto-detect environment, discover services, authenticate, save config
agentic config bootstrap

# Verify
agentic config doctor
```

This resolves the common `[Errno -3] Temporary failure in name resolution` error caused by the config pointing to Docker-internal DNS. See **[CLI Bootstrap Guide](guides/CLI_BOOTSTRAP_GUIDE.md)** for non-interactive mode, environment variables, and troubleshooting.

### Bootstrap Credentials

**Initial Bootstrap**:
```bash
# 1. Run bootstrap script (generates all credentials)
make fix-credentials

# 2. Sync credentials for validation tests
make sync-credentials

# 3. Verify credentials exist
make validate-credentials-exist
```

### Credential Rotation

**Rotating All Service Credentials**:
```bash
# 1. Backup existing credentials
cp -r deployment/local/docker-compose/.env-keycloak-credentials-dir \
     deployment/local/docker-compose/.env-keycloak-credentials-dir.backup

# 2. Regenerate credentials
make fix-credentials

# 3. Restart services to pick up new credentials
make restart

# 4. Validate services are healthy
make validate-comprehensive-health
```

### KC_ADMIN_CLI_SECRET Management

**Critical**: The `KC_ADMIN_CLI_SECRET` is the master credential for all Keycloak admin operations.

**Discovery** (if lost):
```bash
# Method 1: Discovery script
./scripts/deps/discover_admin_cli_secret.sh

# Method 2: Direct PostgreSQL query
docker exec postgres psql -U admin -d keycloak -c \
    "SELECT secret FROM client WHERE client_id = 'admin-cli';" -t -A

# Method 3: From credentials directory
cat deployment/local/docker-compose/.env-keycloak-credentials-dir/KC_ADMIN_CLI_SECRET
```

**Update .env File**:
```bash
# Edit .env with discovered secret
vim .env
# Set: KC_ADMIN_CLI_SECRET=<secret-from-above>

# Rebuild orchestration service to pick up new value
make rebuild-orchestrator
```

### SECRET_RETRIEVAL_METHOD Configuration

**Default**: `file`

**Environment Variables**:
```bash
SECRET_RETRIEVAL_METHOD=file  # Default, recommended for Docker/K8s
SECRET_FILE_PATH=/run/secrets  # Default primary directory
```

**Fallback Chain** (when `SECRET_RETRIEVAL_METHOD=file`):
1. `/run/secrets/{SECRET_NAME}` (uppercase) - Docker/K8s secrets standard
2. `/run/secrets/{secret_name}` (lowercase) - Docker secrets compatibility
3. `/app/credentials/{SECRET_NAME}` (uppercase) - Credentials directory fallback
4. `os.getenv("{SECRET_NAME}")` - Environment variable final fallback

---

## Session Lineage Isolation (Context Auto-Compaction)

When conversations exceed the LLM's context window, the system automatically forks to a sub-session (context compaction). Understanding the isolation model is important for debugging file access issues and session-related support tickets.

### Key Concepts for Administrators

- **Fork chains are stored in Redis** as `fork:{parent_session_id} -> child_session_id` keys. They are automatically followed when a user continues a conversation.
- **Forks are unbounded** -- users can continue conversations indefinitely across any number of context compactions. There is no artificial cap on chain length.
- **File isolation is fork-agnostic** -- file directories use the original (pre-fork) session ID. Context compaction forks do not create new file directories or break file access.
- **MCP tools receive the stable parent session ID**, not the forked sub-session ID. This prevents file metadata from fragmenting across sub-sessions.
- **Cycle detection** (not hop counting) protects against corrupt fork chains. Circular references are logged as `[FORK_RESOLUTION] Cycle detected` errors.

### Troubleshooting

```bash
# Check fork chain for a session
docker exec redis redis-cli KEYS "fork:streamlit_*"

# Follow a chain manually
docker exec redis redis-cli GET "fork:streamlit_5f58d06c59f34e78"

# Verify file directory uses parent session
ls -la data/uploaded_files/sessions/streamlit_5f58d06c59f34e78/
```

**Architecture Reference**: `docs/architecture/SESSION_LINEAGE_ISOLATION_ARCHITECTURE.md`

---

## Service Health Monitoring

### Service Health Manager

**Script**: `scripts/deps/service_health_manager.py`

**Purpose**: Proactive monitoring and auto-recovery for:
- Credential drift (OpenWebUI, n8n, registry service clients)
- Token expiration
- MCP tool discovery issues
- Service connectivity

**Usage**:
```bash
# Validate all service credentials
python scripts/deps/service_health_manager.py --validate-credentials

# Fix credential drift automatically
python scripts/deps/service_health_manager.py --fix-credentials

# Discover and validate MCP tools
python scripts/deps/service_health_manager.py --discover-tools

# Comprehensive health check
python scripts/deps/service_health_manager.py --health-check

# Get results in JSON format
python scripts/deps/service_health_manager.py --health-check --json
```

**Integration**:
```bash
# Makefile targets
make validate-credentials           # Check service client auth
make fix-credentials               # Auto-fix credential drift
make validate-mcp-tools-discovery  # Validate MCP tool availability
make validate-comprehensive-health # Full system health check
```

### Monitoring Dashboard

**Service Status**:
```bash
# Check all containers
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# Check service logs
docker logs orchestration_service --tail 100
docker logs agent_gateway --tail 100
docker logs keycloak --tail 100
```

**Database Health**:
```bash
# Check PostgreSQL connection
docker exec postgres psql -U admin -d postgres -c "SELECT version();"

# Check active sessions
docker exec postgres psql -U admin -d postgres -c \
    "SELECT COUNT(*), status FROM user_sessions GROUP BY status;"

# Check database size
docker exec postgres psql -U admin -d postgres -c \
    "SELECT pg_size_pretty(pg_database_size('postgres'));"
```

---

## Ansible Stack Lifecycle Management

ADEPT provides Ansible playbooks for automated stack lifecycle management, supporting both local and remote execution. For full details, see [`deployment/ansible/README.md`](../deployment/ansible/README.md).

### Prerequisites: Ansible Galaxy Collections

Before running any playbook, install required collections:

```bash
ansible-galaxy collection install -r deployment/ansible/requirements.yml
```

### Playbooks

| Playbook | Purpose |
|----------|---------|
| `deployment/ansible/playbooks/prepare-rocky-vm.yml` | OS-level setup: Docker, users, workspace dirs, symlinks, permissions |
| `deployment/ansible/playbooks/rebuild-stack.yml` | Full ADEPT + MCP server lifecycle: build -> start -> register -> verify |

### rebuild-stack.yml -- 8-Phase Lifecycle

| Phase | Tag | Description |
|-------|-----|-------------|
| 0 | `always` | Pre-flight: workspace, .env, Docker checks |
| 0b | `always` | Best-effort `chmod -R a+rwX data/` (sudo-docker migration) |
| 1 | `adept` | Rebuild ADEPT core stack (`make rebuild`, 10-20 min) |
| 2 | `adept` | Sync credentials + fix credential drift |
| 3 | `adept` | Wait for orchestration_service, agent_gateway, keycloak healthy |
| 4 | `mcp`, `biofoundation` | Rebuild Bio-Foundation MCP server + health check |
| 5 | `mcp`, `vfm` | Rebuild VFM MCP server + health check |
| 6 | `mcp`, `tests` | Run offline test suites for both MCP servers |
| 7 | `oauth2` | Register OAuth2 redirect URIs (FQDN + api.agentic.local) |
| 8 | `verify` | Final container count and status report |

### Common Invocations

```bash
cd <workspace>

# Full rebuild (all phases)
ansible-playbook deployment/ansible/playbooks/rebuild-stack.yml \
  -i deployment/ansible/inventory/your-site.ini

# ADEPT core only (skip MCP servers)
ansible-playbook deployment/ansible/playbooks/rebuild-stack.yml \
  -i deployment/ansible/inventory/your-site.ini --tags adept

# MCP servers only (ADEPT already running)
ansible-playbook deployment/ansible/playbooks/rebuild-stack.yml \
  -i deployment/ansible/inventory/your-site.ini --tags mcp

# Single MCP server
ansible-playbook deployment/ansible/playbooks/rebuild-stack.yml \
  -i deployment/ansible/inventory/your-site.ini --tags biofoundation

# Verify stack health (all containers, no rebuild)
ansible-playbook deployment/ansible/playbooks/rebuild-stack.yml \
  -i deployment/ansible/inventory/your-site.ini --tags verify \
  --limit <your-hostname>

# Target a specific host (required when inventory has multiple hosts)
ansible-playbook deployment/ansible/playbooks/rebuild-stack.yml \
  -i deployment/ansible/inventory/your-site.ini --tags mcp \
  --limit <your-hostname>

# Background execution with timestamped log
nohup ansible-playbook deployment/ansible/playbooks/rebuild-stack.yml \
  -i deployment/ansible/inventory/your-site.ini --tags mcp \
  > logs/rebuild_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

### Inventory Configuration

```ini
# deployment/ansible/inventory/your-site.ini -- local execution (on the target host itself)
[adept_vms]
<your-hostname> ansible_user=<your-user> ansible_python_interpreter=/usr/bin/python3 ansible_connection=local

[adept_vms:vars]
data_volume=/data
adept_workspace=<workspace>
site_name=<your-site>
```

#### Host Parameters

| Parameter | Local | Remote | Description |
|-----------|-------|--------|-------------|
| `ansible_connection` | `local` | (omit or `ssh`) | Connection type; `local` skips SSH |
| `ansible_user` | current user | SSH username | Must have `docker` group membership |
| `ansible_python_interpreter` | `/usr/bin/python3` | `/usr/bin/python3` | Python path on target |
| `ansible_ssh_private_key_file` | N/A | `~/.ssh/id_rsa` | SSH key for remote authentication |
| `ansible_become` | N/A | `true` (if needed) | Sudo escalation for permissions |
| `adept_workspace` | workspace path | workspace path on target | Must contain Makefile and .env |

#### Remote Execution Prerequisites

When deploying to a remote host (remove `ansible_connection=local`):

1. **SSH access**: The control machine must have SSH key access to the target
   ```bash
   ssh-copy-id your-user@your-host.example.com
   ```
2. **Docker group**: The `ansible_user` on the target must be in the `docker` group (or set `sudo_docker=true`)
3. **Workspace exists**: `adept_workspace` must already contain a cloned repo with `.env` configured
4. **Data files**: Model checkpoints and reference data must be in `data/` on the target
5. **Credentials**: `.env-keycloak-credentials-dir/` must exist (created by first `make rebuild`)

```ini
# deployment/ansible/inventory/remote.ini -- remote execution example
[adept_vms]
your-host.example.com ansible_user=<your-user> ansible_python_interpreter=/usr/bin/python3 ansible_ssh_private_key_file=~/.ssh/id_rsa

[adept_vms:vars]
data_volume=/data
adept_workspace=<workspace>
site_name=<your-site>
```

### Data Directory Permissions (sudo-docker Migration)

When transitioning from `sudo docker` to non-sudo docker, files created by containers retain their original UID ownership (postgres=999, n8n=1000, appuser=1200) with restrictive permissions. The playbook handles this automatically:

1. **Phase 0b** runs `chmod -R a+rwX data/` (best-effort, ignores failures on locked files)
2. **quick-start script** escalates to `sudo chmod` when non-sudo fails
3. **prepare-rocky-vm.yml** includes a recursive permissions task in phase8

If containers still fail after ansible rebuild:
```bash
# Manual fix (requires sudo for container-owned files)
sudo chmod -R a+rwX data/
docker restart n8n openwebui  # Restart affected services
```

### Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `sudo_docker` | `false` | Prefix docker commands with sudo |
| `gpu_mode` | `cpu` | Device mode for MCP servers |
| `skip_mcp_tests` | `false` | Skip Phase 6 offline tests |
| `full_rebuild` | `true` | Use `--no-cache` for builds |

### References

- Playbook: `deployment/ansible/playbooks/rebuild-stack.yml`
- VM prep: `deployment/ansible/playbooks/prepare-rocky-vm.yml`
- Quick-start: `scripts/quick-start-adept-and-subsystems.sh`

### Deploying to a Remote Host

This walkthrough deploys ADEPT from a prepared control host to a fresh remote target. Both hosts share an IDP, so SSH uses password authentication -- no key exchange required.

**Prerequisites on the control host:**
- Ansible installed (in the `adept-session` conda env)
- ADEPT repository cloned with playbooks and inventory
- Network connectivity to the target host

**Prerequisites on the target host:**
- Rocky Linux 9 (or Ubuntu 22/24)
- `/data` volume mounted with at least 50 GB free
- `ansible_user` has sudo privileges

#### Step 1: Prepare the Remote VM

Runs all 10 phases of `prepare-rocky-vm.yml`: validates the data volume, installs system packages + conda, installs Docker CE, moves the Docker data root to `/data`, configures firewall and sysctl, cleans stale Podman storage (Rocky only), starts Docker with a smoke test, transfers the source code and creates workspace dirs/symlinks/TLS cert, and copies `.env.example` with host-specific values (KEYCLOAK_URL, NGINX_PUBLIC_FQDN, PUBLIC_BASE_URL).

**Workspace naming convention**: `adept-agentic-{deploy_context}` (e.g., `/data/workspace/adept-agentic-my-deployment`). The playbook builds this from `deploy_context` (inventory variable, defaults to `site_name` if not set). One VM = one deployment = one context. Redeployments overwrite the workspace in place (idempotent).

**Important**: The default `git_repo` variable points to the GitHub org, which may enforce SAML SSO. HTTPS username/password auth will fail with a 403. Use one of these alternatives:

| Scenario | Extra flags |
|----------|-------------|
| Personal fork (no SSO) | `-e "git_repo=https://github.com/<user>/adept-agentic-framework-extended.git"` |
| Tarball transfer (no GitHub auth needed) | `-e source_tarball=true` |
| Workspace already exists | `-e git_clone=false` |

**Option A -- Git clone from personal fork (no SAML SSO required):**

```bash
cd <your-adept-clone>

ansible-playbook deployment/ansible/playbooks/prepare-rocky-vm.yml \
  -i deployment/ansible/inventory/remote.ini \
  --ask-pass --ask-become-pass \
  -e "git_repo=https://github.com/<your-user>/adept-agentic-framework-extended.git"
```

**Option B -- Tarball transfer (target cannot reach GitHub, or repo requires SAML SSO):**

```bash
cd <your-adept-clone>

ansible-playbook deployment/ansible/playbooks/prepare-rocky-vm.yml \
  -i deployment/ansible/inventory/remote.ini \
  --ask-pass --ask-become-pass \
  -e source_tarball=true
```

This creates a `git archive` tarball of tracked files from your local clone and transfers it to the target via SSH. The tarball includes only committed files on HEAD (excludes `.git/`, untracked, and gitignored files). A `git init` is run on the target to make the workspace idempotent and enable future `git pull` once GitHub access is available.

**Target workspace folder naming**: The playbook creates the workspace on the target host using the convention `adept-agentic-{deploy_context}`, e.g., `/data/workspace/adept-agentic-my-deployment`. This is independent of your local clone's folder name -- the tarball is repacked with the correct prefix for the target. The components are:
- `adept-agentic` -- repo identifier (matches the public GitHub repo name)
- `{deploy_context}` -- from the inventory or Makefile `DEPLOY_CONTEXT` variable (defaults to `site_name`)

**Flags:**
- `--ask-pass`: prompts for SSH password (shared IDP)
- `--ask-become-pass`: prompts for sudo password (required for Docker install, sysctl, firewall)
- `-e deploy_context=<context>`: set workspace context (defaults to site_name)
- `-e adept_workspace=/custom/path`: override workspace path entirely (optional)

#### Step 2: Configure LLM Credentials on the Target

The playbook copies `.env.example` and sets host-specific variables, but LLM API keys must be filled in manually (they contain secrets that cannot be committed to the repo).

```bash
ssh <your-host>
cd /path/to/your/adept-workspace  # adjust to match your deployment

# Activate docker group membership (added by Step 1)
newgrp docker

# Edit .env -- minimum viable LLM configuration:
#   DEFAULT_LLM_MODEL=bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0
#   LANGCHAIN_LLM_MODEL=bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0
#   RAG_DEFAULT_MODEL=bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0
#   AWS_ACCESS_KEY_ID=AKIA...
#   AWS_SECRET_ACCESS_KEY=...
#   AWS_REGION_NAME=us-west-2
#   CODING_AGENT_DEFAULT_MODEL=bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0
#   CODING_AGENT_AWS_REGION_NAME=us-west-2
#   CODING_AGENT_AWS_ACCESS_KEY_ID=AKIA...
#   CODING_AGENT_AWS_SECRET_ACCESS_KEY=...
vi .env

# Optional: configure Claude Code credentials for developers on this host
cp devtools/aws-cdk/setup-claude-bedrock.sh.template setup-claude-bedrock.sh
vi setup-claude-bedrock.sh
source setup-claude-bedrock.sh

exit  # back to control host
```

> **Tip**: You can `scp` the `.env` from the control host and edit only the host-specific values. The playbook already sets NGINX_PUBLIC_FQDN, PUBLIC_BASE_URL, and AGENT_GATEWAY_ALLOWED_HOSTS to the target's FQDN.

#### Step 3: Build and Start the ADEPT Stack

Runs `rebuild-stack.yml` remotely: builds all containers (10-20 min), syncs and fixes credentials, waits for core services to be healthy, rebuilds MCP servers (if present), and registers OAuth2 redirect URIs.

```bash
# From control host -- use nohup because the rebuild is long-running
nohup ansible-playbook deployment/ansible/playbooks/rebuild-stack.yml \
  -i deployment/ansible/inventory/remote.ini --ask-pass \
  > logs/remote_rebuild_$(date +%Y%m%d_%H%M%S).log 2>&1 &

# Monitor progress
tail -f logs/remote_rebuild_*.log
```

To rebuild only the ADEPT core stack (skip MCP servers):
```bash
ansible-playbook deployment/ansible/playbooks/rebuild-stack.yml \
  -i deployment/ansible/inventory/remote.ini --ask-pass --tags adept
```

#### Step 4: Post-Bootstrap (OAuth2 Redirect URIs)

Registers OAuth2 redirect URIs for the target's FQDN and IP so external browsers can authenticate via JupyterLab and OpenWebUI.

```bash
ansible-playbook deployment/ansible/playbooks/post-bootstrap.yml \
  -i deployment/ansible/inventory/remote.ini --ask-pass
```

#### Verification

After Step 4 completes, verify from the control host:
```bash
# Stack health (no rebuild, just check)
ansible-playbook deployment/ansible/playbooks/rebuild-stack.yml \
  -i deployment/ansible/inventory/remote.ini --ask-pass --tags verify

# Or test directly
curl -sk https://your-adept-host.example.com/ | python3 -m json.tool  # API index
curl -sk -o /dev/null -w '%{http_code}' https://your-adept-host.example.com/jupyter/  # 302 -> OAuth2
```

#### Inventory Reference

```ini
# deployment/ansible/inventory/remote.ini
[adept_vms]
your-host.example.com ansible_user=<your-user> ansible_python_interpreter=/usr/bin/python3

[adept_vms:vars]
data_volume=/data
adept_workspace=/path/to/your/adept-workspace
site_name=<your-site>
```

Note: No `ansible_connection=local` (uses SSH) and no `ansible_ssh_private_key_file` (shared IDP, password authentication via `--ask-pass`).

### AWS EC2 Developer VM Provisioning (CDK + Ansible)

For provisioning **fresh EC2 developer VMs** in AWS, use the CDK + Ansible two-step workflow in `devtools/skypilot/`. This is separate from the Ansible-only lifecycle above because it handles:

- **CDK**: Infrastructure provisioning (EC2, IAM, security groups, CloudWatch alarms) in SCP-restricted VPCs
- **Compliance**: Two-step process -- CDK creates bare EC2, then Ansible configures after security hooks complete
- **Multi-context state**: Per-account/provider isolation in `devtools/skypilot/contexts/<DEPLOY_CONTEXT>/`

**Quick reference (all commands from project root)**:

```bash
# Deploy EC2 instance (background)
make cdk-deploy-bg

# Retrieve SSH key
make cdk-retrieve-key

# Test connectivity (host-local SSH, no container)
make ec2-ping EC2_HOST=<private-ip>

# Sync codebase to EC2 (incremental rsync)
make ec2-sync EC2_HOST=<private-ip>

# Run Ansible OS preparation (Docker, Python, workspace)
make ansible-prepare-vm-bg \
  ANSIBLE_TARGET_HOST=<private-ip> \
  ANSIBLE_SSH_KEY=ADE-dev-<user>-<account>-key.pem

# Tear down
make cdk-destroy
```

**How it works**: The EC2 management targets (`cdk-*`, `ec2-*`, `ansible-*`) live in `devtools/Makefile.internal`, which is conditionally included into the root Makefile via `-include` (silently skipped when absent, e.g., in public releases). Run `make help-internal` to list all available internal targets. Always invoke them from the **project root**, not from `devtools/skypilot/`.

**Full guide**: [`devtools/skypilot/ONBOARDING.md`](../devtools/skypilot/ONBOARDING.md)
**GitHub Issue**: [#34](https://github.com/pnnl/adept-agentic-framework-extended/issues/34)

---

## Troubleshooting

### Common Issues

#### Issue 1: User Creation Fails with "401 Unauthorized"

**Symptom**:
```
401 unauthorized_client: Invalid client or Invalid client credentials
```

**Root Cause**: `KC_ADMIN_CLI_SECRET` is missing or incorrect. See [KC_ADMIN_CLI_SECRET Management](#kc_admin_cli_secret-management) for full discovery methods.

**Quick Fix**:
```bash
./scripts/deps/discover_admin_cli_secret.sh  # Find the correct secret
vim .env                                      # Set KC_ADMIN_CLI_SECRET=<secret>
make rebuild-orchestrator                     # Pick up new value
make list-keycloak-groups                     # Verify connection
```

#### Issue 2: Service Token Not Working

**Symptom**:
```
curl -H "Authorization: Bearer sk-service-..." https://api.agentic.local/v1/models
# Returns: 401 Unauthorized
```

**Root Cause**: Token not in `SERVICE_API_KEYS_CONFIG` or revoked.

**Solution**:
```bash
# 1. List all tokens
make list-service-tokens

# 2. Check if token is active (not expired or revoked)
# If expired/revoked, create new token

# 3. Verify SERVICE_API_KEYS_CONFIG contains token
docker exec orchestration_service bash -c "
    python3 -c \"
from agentic_framework_pkg.core.secrets_manager import get_secret
import json
config = json.loads(get_secret('SERVICE_API_KEYS_CONFIG'))
print('sk-service-...' in config)
    \"
"

# 4. If token missing, recreate and update SERVICE_API_KEYS_CONFIG
make fix-credentials  # Regenerates all credentials including SERVICE_API_KEYS_CONFIG
```

#### Issue 3: Credential Drift After Service Restart

**What is credential drift?** When Keycloak client secrets are regenerated (via `make fix-credentials`, `make rebuild`, or bootstrap), services that cache the old secret become unable to authenticate. This is the #1 cause of "Internal Server Error" on OAuth2 login flows.

**Affected services and symptoms**:

| Service | Symptom | Root Cause |
|---------|---------|------------|
| oauth2_proxy (JupyterLab) | `500 Internal Server Error` on `/oauth2/callback` | `jupyterlab-client` secret mismatch |
| OpenWebUI | Login fails with 401 | `openwebui-client` secret mismatch |
| n8n | Webhook auth fails | `n8n-client` secret mismatch |
| agent_gateway | JWT validation fails | `AGENT_GATEWAY_CLIENT_SECRET` stale |

**How to identify**: Check oauth2_proxy logs for the telltale error:
```bash
docker logs oauth2_proxy --tail 10
# Look for: "unauthorized_client" "Invalid client or Invalid client credentials"
```

**When drift happens**:
- After `make rebuild-orchestrator` (bootstrap regenerates secrets)
- After `make fix-credentials` if oauth2_proxy/jupyterlab are NOT recreated
- After `make restart` if Keycloak DB was wiped
- After any operation that runs `bootstrap_keycloak.py`

**Single-command fix** (regenerates secrets AND recreates affected services):
```bash
make fix-credentials
```

This command:
1. Runs `bootstrap_keycloak.py` inside orchestration_service (regenerates all client secrets in Keycloak)
2. Writes new secrets to `deployment/local/docker-compose/.env-keycloak-credentials-dir/`
3. Stops and removes oauth2_proxy + jupyterlab containers
4. Recreates orchestration_service, agent_gateway, gateway_registry, oauth2_proxy, jupyterlab with fresh secrets

**Verify the fix**:
```bash
# 1. Check oauth2_proxy started without errors
docker logs oauth2_proxy --tail 5
# Should show: "OAuthProxy configured for Keycloak OIDC Client ID: jupyterlab-client"
# Should NOT show: "unauthorized_client"

# 2. Test JupyterLab login
# Browse to https://<hostname>/jupyter/ -- should redirect to Keycloak login

# 3. Full health check
make validate-comprehensive-health
```

**Why this keeps happening**: The bootstrap script regenerates ALL client secrets every time it runs (by design -- it ensures Keycloak and the credentials directory are always in sync). But any service that loaded the OLD secret from its environment will fail until it's recreated with the new secret. The `make fix-credentials` target handles this by explicitly recreating the affected containers.

**Prevention**: Always use `make fix-credentials` instead of manually running `bootstrap_keycloak.py`. The Makefile target handles the full lifecycle (regenerate + recreate). If you only need to restart services without regenerating secrets, use `make restart` instead.

#### Issue 4: JupyterLab "Invalid parameter: redirect_uri"

**Symptom**: After logging into Keycloak, the browser shows:
```
Keycloak - We are sorry...
Invalid parameter: redirect_uri
```

**Root Cause**: The hostname you are accessing the stack from (e.g., `your-adept-host.example.com`) is not registered as a valid OAuth2 redirect URI in Keycloak. The bootstrap script only auto-registers the host from `PUBLIC_BASE_URL` in `.env`.

**How to identify**:
```bash
# Check what PUBLIC_BASE_URL is set to
grep PUBLIC_BASE_URL .env

# List registered redirect URIs
make list-oauth-redirects

# If your hostname/FQDN is NOT in the list, that's the problem
```

**Fix**:
```bash
# Register the missing hostname
make register-oauth-redirect HOST=your-adept-host.example.com

# Verify it was added
make list-oauth-redirects
```

**Prevention**: If you always access the stack via FQDN, set `PUBLIC_BASE_URL` in `.env` to the FQDN:
```bash
# .env
PUBLIC_BASE_URL=https://your-adept-host.example.com
```

Then `make fix-credentials` will auto-register the FQDN during bootstrap. You can still register additional hostnames/IPs with `make register-oauth-redirect HOST=<ip>`.

**Note**: This is often hit in sequence with Issue 3 (credential drift). After `make fix-credentials` fixes the 500 error, the next error is "Invalid parameter: redirect_uri" because the FQDN was never registered. The full recovery sequence is:
```bash
make fix-credentials                                              # Fix client secret drift
make register-oauth-redirect HOST=your-adept-host.example.com    # Register FQDN
make register-oauth-redirect HOST=<your-server-ip>               # Register IP (if needed)
```

#### Issue 5: Port Conflicts

**Symptom**: Services fail to start due to port already in use.

**Solution**:
```bash
# Check which service is using the port
sudo lsof -i :8083  # Agent Gateway
sudo lsof -i :8084  # Orchestration Service
sudo lsof -i :8180  # Keycloak

# Stop conflicting service or use different port
# Update docker-compose.core.yaml with new port mapping
```

---

## CI/CD: GitHub Actions Workflows

### Overview

The repository includes GitHub Actions workflows for automated scanning and deployment:

| Workflow | File | Purpose | Trigger |
|----------|------|---------|---------|
| ASOPB Pre-Release Scan | `asopb-pre-release-scan.yml` | Two-phase security scan (regex blocking + ML graceful) | PR to main, push to feature branches, manual dispatch |
| Publish Public Release | `publish-public-release.yml` | Push to public repo `pnnl/adept-agentic` | Manual dispatch only |
| Deploy Documentation | `deploy-docs.yml` | Build MkDocs site and deploy to GitHub Pages | Push to main (paths: `docs/public-site/**`) |
| Build and Push | `build-and-push.yml` | Docker image builds for ACR/ECR | Called by deploy workflows |
| Lint and Test | `lint-and-test.yml` | Code quality and unit tests | PR events |

### GitHub Pages Documentation Site

The public documentation site runs on `pnnl/adept-agentic` (the public repo), not the internal repo. Content flows through the release pipeline:

1. Pages are authored in `docs/public-site/docs/` (internal repo, MkDocs Material format)
2. `make stage` includes `docs/public-site/` in the staged release tree (via `.publish-exclude` allowlist)
3. After publishing to the public repo, `deploy-docs.yml` triggers and builds the site
4. GitHub Pages serves the built site from the `gh-pages` branch

**Content safety**: Four layers prevent internal content from reaching the public site:
- `.publish-exclude` controls what reaches the public repo
- `make -C docs/public-site validate` scans for prohibited patterns pre-commit
- `/sync-docs` skill checks parity during development
- `deploy-docs.yml` runs a content safety grep before building

**Enabling Pages on a new deployment**: Settings > Pages > Source: Deploy from a branch (`gh-pages`, root).

**Local preview**: `make -C docs/public-site serve` starts a local MkDocs dev server on port 8000.

### ASOPB Pre-Release Scan (Two-Phase Parallel Pipeline)

> **Full configuration reference**: [`docs/ci/ASOPB_CI_CONFIGURATION.md`](../ci/ASOPB_CI_CONFIGURATION.md)
> covers branch triggers, conditional jobs, GHCR auth, troubleshooting, and local equivalents.

Automated security scanning triggered on pushes to `main` and `feature-platform-optimizations-*` branches, PRs to main, and manual dispatch.

**Phase 1 (blocking)**: Pure Python regex scan. Stages the release tree using
`make stage` (same as local scanning). Fails the PR check if ASPI score < 90
(S4 Hardened threshold). Posts ASPI summary as a PR comment.

**Phase 2 (graceful, parallel)**: Full ML pipeline via the `adept-release-scanner`
Docker image from GHCR. Parallelized across runners using GHA matrix strategy:

| Tier | Jobs | Timeout | Condition |
|------|------|---------|-----------|
| Fast | 1 | 15 min | Always (regex + secrets + trufflehog) |
| Trivy CVE | 1 | 15 min | Always (advisory, non-blocking) |
| Toxicity | 4 (chunked) | 60 min | Conditional: `full-ml-scan` label or `run_ml_chunks=true` |
| NER | 4 (chunked) | 60 min | Conditional: `full-ml-scan` label or `run_ml_chunks=true` |
| PII | 4 (chunked) | 60 min | Conditional: `full-ml-scan` label or `run_ml_chunks=true` |
| Aggregate | 1 | 10 min | Always (merges whatever results are available) |

Routine CI: ~5 min (fast + trivy only). Full ML: ~60 min. Falls back gracefully
if the image is unavailable. Uses `continue-on-error: true` on scan jobs so ML
failures never block a PR merge. Partial results are preserved as artifacts even
if individual chunks timeout.

**Enabling full ML scan**: Either add the `full-ml-scan` label to the PR, or
dispatch manually with `run_ml_chunks=true`.

**Manual dispatch**: Navigate to Actions > ASOPB Pre-Release Scan > Run workflow.
Configurable inputs: `aspi_threshold` (default 90), `skip_ml_scan` (default false),
`run_ml_chunks` (default false).

### GHCR Scanner Image Lifecycle

The ML scan (Phase 2) requires the `adept-release-scanner` Docker image on GHCR.

**Image location**: `ghcr.io/pnnl/adept-release-scanner:latest` (~6.38GB)

**Image definition**: `scripts/release/Dockerfile` (Python 3.11, CPU-only PyTorch,
3 HuggingFace models, TruffleHog v3.94.3, Node.js 20 + Promptfoo)

**Rebuild and push** (when Dockerfile or ML dependencies change):

```bash
cd scripts/release
make docker-build
docker tag adept-release-scanner:latest ghcr.io/pnnl/adept-release-scanner:latest
gh auth token | docker login ghcr.io -u $(gh api user --jq .login) --password-stdin
docker push ghcr.io/pnnl/adept-release-scanner:latest
```

Push requires a GitHub PAT with `write:packages` scope, or an authenticated `gh` CLI
session with the same scope.

**First-time setup -- package-repository linking** (one-time, required for CI):

After the initial push, the GHCR package must be linked to the repository so CI
runners' `GITHUB_TOKEN` has pull access:

1. Go to https://github.com/orgs/pnnl/packages/container/package/adept-release-scanner
2. Click **Package settings** (right sidebar)
3. Under **Manage Actions access**, click **Add Repository**
4. Select `adept-agentic-framework-extended`
5. Set role to **Read**

Without this linking, Phase 2 silently skips with a "Scanner image not available"
warning. The linking persists across image updates -- subsequent `docker push`
commands do not reset it. This step cannot be done via the GitHub REST API for
org-scoped packages; it must be done via the UI.

**CI authentication**: The workflow uses `docker/login-action@v4` with `GITHUB_TOKEN`
(automatic, `packages:read` permission). No manual secrets configuration needed.

### SCANNER_MOUNTS (Code Parity)

The Docker image provides ML models and runtime dependencies only. The 7 Python
scanning scripts are bind-mounted from the repository checkout at runtime:

```
scripts/release/scan_pipeline.py         -> /app/scan_pipeline.py
scripts/release/scan_sensitive_content.py -> /app/scan_sensitive_content.py
scripts/release/scan_secrets.py          -> /app/scan_secrets.py
scripts/release/scan_ner_pii.py          -> /app/scan_ner_pii.py
scripts/release/scan_toxicity.py         -> /app/scan_toxicity.py
scripts/release/scan_trufflehog.py       -> /app/scan_trufflehog.py
scripts/release/scan_promptfoo.py        -> /app/scan_promptfoo.py
```

This means scanning logic always matches the checked-out commit. The image only
needs rebuilding when runtime dependencies change (new ML models, TruffleHog
version upgrade, etc.), not when scan logic changes.

### GitHub Actions Version Policy

All actions must use Node.js 24-compatible versions. Node.js 20 actions are
deprecated (forced Node 24 default: June 2, 2026; Node 20 removed: September 16, 2026).

Current versions in `asopb-pre-release-scan.yml`:
- `actions/checkout@v6`
- `actions/setup-python@v6`
- `actions/upload-artifact@v7`
- `docker/login-action@v4`
- `actions/github-script@v9`

Other workflows (`build-and-push.yml`, `deploy-*.yml`) still use older action
versions (v2/v3) and need upgrading before the June 2026 deadline.

### Related Documentation

- **GitHub Actions DevOps Guide**: `docs/guides/GITHUB_ACTIONS_DEVOPS.md` (concurrency control, GHCR operations, debugging, version policy)
- **ASPI Scoring Reference**: `docs/security/ASPI_SCORING_REFERENCE.md` (scan types, gate thresholds, domain weights)
- **CVE Triage Guide**: `docs/guides/CVE_TRIAGE_GUIDE.md` (investigate, classify, remediate CVE findings)
- **Compensating Controls Guide**: `docs/guides/COMPENSATING_CONTROLS_GUIDE.md` (suppress false positives with integrity checks)
- **Pre-Release Review Guide**: `scripts/release/PRE_RELEASE_REVIEW_GUIDE.md` (full 5-phase release verification workflow)
- Release pipeline overview: `scripts/release/README.md`
- **Developer Tutorial**: `docs/tutorials/DEVELOPER_ONBOARDING_ASOPB_AND_RELEASE.md` (hands-on walkthrough of scanner internals, image freshness, ML pass troubleshooting)

---

## Security Best Practices

### Password Policies

**Enforce Strong Passwords**:
- Minimum 8 characters
- Mix of uppercase, lowercase, numbers, symbols
- No common words or patterns
- Unique per user (no password reuse)

**Password Validation** (built into `add_keycloak_user.py`):
```python
# Validation checks:
# - Length >= 8 characters
# - Complexity score (warns if < 2 character types)
```

### Token Security

**Service API Token Best Practices**:
1. **Treat tokens like passwords** - Never commit to version control
2. **Use secret managers** - Store in AWS Secrets Manager, HashiCorp Vault, etc.
3. **Rotate before expiration** - Check `make list-service-tokens` regularly
4. **Revoke if compromised** - `make revoke-service-token TOKEN=...`
5. **Minimal permissions** - Only assign necessary groups
6. **Audit usage** - Monitor token access in logs

### Keycloak Security

**Admin Account Security**:
```bash
# Change admin password immediately after installation
docker exec keycloak /opt/keycloak/bin/kcadm.sh set-password \
    --username admin \
    --new-password <strong-password>
```

**Token Lifespan Configuration**:
```bash
# Realm Settings -> Tokens
# Access Token Lifespan: 8 hours (default)
# SSO Session Idle Timeout: 8 hours
# SSO Session Max Lifespan: 8 hours
```

### Sandbox Code Execution Security

**Configuration**: `deployment/local/docker-compose/docker-compose.core.yaml` (sandbox_mcp_server service)

**Execution Method** (`EXECUTION_METHOD` env var):

| Setting | Docker Socket | Privileged | Use Case |
|---------|--------------|------------|----------|
| `subprocess` (default) | NOT needed | NOT needed | Standard scientific computing |
| `docker-in-docker` | Required (via proxy) | Required | Per-execution container isolation |

**Security Level** (`security_level` in code_execution_tool.py):

| Level | Import Handling | Network Access | Use Case |
|-------|----------------|---------------|----------|
| `strict` | Whitelist only (numpy, pandas, scipy, etc.) | BLOCKED | Air-gapped/classified deployments |
| `medium` (default) | Blacklist (blocks subprocess, docker, paramiko) | ALLOWED (for license servers) | Standard deployment |
| `permissive` | Same as medium | ALLOWED | Backward compatibility |

**Critical Security Requirements**:

1. **NEVER mount raw Docker socket** (`/var/run/docker.sock`) into sandbox_mcp_server. This enables full privilege escalation -- any code that reaches the socket can read ALL secrets from ALL containers via `docker inspect`.
2. **If DinD is needed**, use a Docker socket proxy (e.g., `tecnativa/docker-socket-proxy`) that blocks `inspect`, `exec`, and network operations.
3. **privileged mode**: Only enable (`SANDBOX_PRIVILEGED=true`) if DinD is required. Subprocess execution does NOT need it.
4. **nsjail** (optional, deployment-specific): Kernel-level syscall filtering via seccomp BPF.
   Disabled by default for exploratory workloads. Enable with `SANDBOX_USE_NSJAIL=true` for
   sensitive deployments (digital twins, lab automation, classified environments).
   See [nsjail Configuration](#nsjail-kernel-level-syscall-filtering) below.

**Verification**:
```bash
# Verify Docker socket is NOT mounted
docker inspect sandbox_mcp_server --format '{{json .Mounts}}' | python3 -m json.tool | grep docker.sock
# Expected: no output

# Verify not privileged
docker inspect sandbox_mcp_server --format '{{.HostConfig.Privileged}}'
# Expected: false

# Verify security validator is active (check logs after code execution)
docker logs sandbox_mcp_server --tail 10 | grep "security validation"
```

**Network Isolation**:
- sandbox_mcp_server is on `application_net` + `adept_integration_network`
- NOT on `data_net` -- Redis and PostgreSQL are unreachable from sandbox code
- External egress is DENIED by default (nftables DROP policy, fail-closed)
- Operators can allowlist specific external hosts via `config/sandbox_egress_allowlist.yaml`

**Environment Variable Isolation**:
- sandbox_mcp_server does NOT use `env_file:` -- only explicitly listed vars enter the container
- Critical secrets (KEYCLOAK_ADMIN_PASSWORD, AWS_SECRET_ACCESS_KEY, KC_ADMIN_CLI_SECRET, etc.) are never injected
- Only LANGFUSE_SECRET_KEY (observability) enters the container beyond operational vars
- `/proc/1/environ` contains no infrastructure secrets
- Subprocess-spawned code additionally restricted to 5 vars via `_create_restricted_env()`

**Docker Capabilities (Principle of Least Privilege)**:
- `cap_drop: ALL` -- removes all capabilities from the container
- Selective `cap_add`: NET_ADMIN (nftables), CHOWN/DAC_OVERRIDE/FOWNER (entrypoint), SETUID/SETGID (gosu)
- After gosu privilege drop, appuser has CapEff=0 (zero effective capabilities)

**Sandbox Egress Allowlist Configuration** (opt-in, per-site):

By default, the sandbox container blocks all outbound connections to external hosts.
To allow access to license servers, HPC login nodes, or package registries:

```bash
# 1. Copy the example config
cp config/sandbox_egress_allowlist.yaml.example config/sandbox_egress_allowlist.yaml

# 2. Edit to add your site-specific hosts
#    Each rule requires: host, port, protocol (tcp/udp), and a comment explaining why
vim config/sandbox_egress_allowlist.yaml

# 3. Restart the sandbox service to apply (no rebuild needed)
docker compose -f docker-compose.base.yaml -f docker-compose.core.yaml --profile apps restart sandbox_mcp_server
```

Example `config/sandbox_egress_allowlist.yaml`:
```yaml
version: 1
rules:
  - host: hpc-login.example.com
    port: 22
    protocol: tcp
    comment: "HPC login node for job submission"
  - host: license-server.example.com
    port: 27000
    protocol: tcp
    comment: "License server for optimization solvers"
  - host: pypi.org
    port: 443
    protocol: tcp
    comment: "Python package index for pip installs"
```

**Fail-closed behavior**: If the config file has invalid syntax, unknown fields, or
fails Pydantic validation, ALL external egress is blocked (deny-all). This prevents
misconfiguration from accidentally opening network access.

**Internal services** (orchestration, MCP servers on `application_net`) remain reachable
regardless of egress configuration -- the allowlist only controls external-facing traffic.

**Validation**:
```bash
make validate-sandbox-egress-allowlist  # 24 E2E tests (runs on host via conda)
```

**Implementation details**: `docs/implementation-plans/SANDBOX_EGRESS_ALLOWLIST_PLAN.md`
**Security assessment**: `docs/security/SANDBOX_EGRESS_ALLOWLIST_SECURITY_ASSESSMENT.md`

**Compensating Controls** (accepted risks with documented justification):
- **CC-SANDBOX-01**: RESOLVED -- nftables egress allowlist enforced (deny-by-default). Only operator-specified hosts reachable.
- **CC-SANDBOX-02**: RESOLVED -- nsjail kernel-level isolation implemented and validated. Disabled by default for exploratory workloads; enabled per-deployment via `SANDBOX_USE_NSJAIL=true`.

### Gurobi Optimization Support (Opt-In)

**Status**: Opt-in capability. Requires: license file, network access to token server, authorized OS username.

The sandbox supports Gurobi optimization workloads (LP, MILP, QP) when deployed on a network with access to a Gurobi token server.

**Configuration** (`.env`):

```bash
# 1. Subprocess identity -- must match an authorized username in the license file
SANDBOX_EXEC_USER=<your_authorized_username>
SANDBOX_EXEC_UID=1500
SANDBOX_EXEC_GID=1200

# 2. License file path inside container (entrypoint validation only)
GRB_LICENSE_FILE=/app/data/gurobi.lic

# 3. Token server DNS (injected into container /etc/hosts)
GRB_TOKEN_SERVER_HOST=<token-server-hostname>
GRB_TOKEN_SERVER_IP=<token-server-ip>
GRB_TOKEN_SERVER_PORT=<token-server-port>
```

**License file placement** (choose one):

| Path (inside container) | How to provide |
|-------------------------|----------------|
| `/app/data/uploaded_files/gurobi.lic` | Place at `data/uploaded_files/gurobi.lic` on host (shared volume, simplest) |
| `/app/data/gurobi.lic` | Bind mount via compose override |
| `/opt/gurobi/gurobi.lic` | Bake into custom image |

**Egress allowlist**: Ensure `config/sandbox_egress_allowlist.yaml` permits your token server:
```yaml
rules:
  - host: <token-server-hostname>
    protocol: tcp
    comment: "Gurobi license token server"
```

**Validation**:
```bash
make validate-sandbox-exec-user-io    # Identity switching + file I/O
make validate-cobrapy-gurobi          # Full license checkout + LP solve
```

### nsjail Kernel-Level Syscall Filtering

**Status**: Implemented, validated (22/22 tests), disabled by default

nsjail provides kernel-level syscall filtering via seccomp BPF. When enabled, code execution
runs inside a jail that blocks 22 dangerous system calls (container escape, kernel modification,
process inspection, filesystem escape).

| Deployment Type | `SANDBOX_USE_NSJAIL` | Rationale |
|-----------------|---------------------|-----------|
| Exploratory research | `false` (default) | LLM-generated code needs flexible filesystem and package management |
| Digital twins / lab automation | `true` | Code targets physical equipment; syscall restrictions prevent unintended I/O |
| Pre-production validation | `true` | Code is gated before promotion to production pipelines |
| Multi-tenant (untrusted users) | `true` | Container isolation alone is insufficient for adversarial inputs |

Enable:
```bash
# In .env:
SANDBOX_USE_NSJAIL=true

# Restart sandbox
docker compose -f docker-compose.base.yaml -f docker-compose.core.yaml \
  --profile apps restart sandbox_mcp_server
```

**DinD Opt-In** (for project teams requiring per-execution container isolation):
```bash
docker compose -f docker-compose.base.yaml -f docker-compose.core.yaml -f docker-compose.dind.yaml up -d
```
See `deployment/local/docker-compose/docker-compose.dind.yaml` for the override configuration.

**Reference**: `docs/security/SANDBOX_EXECUTION_METHOD_SECURITY.md` (section 7 Compensating Controls)

### Audit Logging

**Enable Keycloak Event Logging**:
- Realm Settings -> Events -> Save Events: ON
- Login Events -> Save Events: ON
- Admin Events -> Save Admin Events: ON

**View Audit Logs**:
```bash
# User login events
docker exec keycloak /opt/keycloak/bin/kcadm.sh get events -r master

# Admin events (user creation, group changes)
docker exec keycloak /opt/keycloak/bin/kcadm.sh get admin-events -r master
```

---

## Backup & Recovery

### Database Backup

**PostgreSQL Backup**:
```bash
# Backup all databases
docker exec postgres pg_dumpall -U admin > backup_$(date +%Y%m%d).sql

# Backup specific database
docker exec postgres pg_dump -U admin -d postgres > backup_postgres_$(date +%Y%m%d).sql

# Backup user_sessions and session_messages tables
docker exec postgres pg_dump -U admin -d postgres -t user_sessions -t session_messages \
    > backup_sessions_$(date +%Y%m%d).sql
```

**Keycloak Database Backup**:
```bash
# Backup Keycloak realm configuration
docker exec postgres pg_dump -U admin -d keycloak > backup_keycloak_$(date +%Y%m%d).sql
```

### Credential Backup

**Backup Credentials Directory**:
```bash
# Backup all credentials
tar -czf credentials_backup_$(date +%Y%m%d).tar.gz \
    deployment/local/docker-compose/.env-keycloak-credentials-dir/

# Store backup securely (AWS S3, encrypted storage)
aws s3 cp credentials_backup_$(date +%Y%m%d).tar.gz s3://my-backups/adept/
```

### Recovery Procedures

**Restore Database**:
```bash
# Stop services
make stop

# Restore database
cat backup_$(date +%Y%m%d).sql | docker exec -i postgres psql -U admin

# Start services
make start
```

**Restore Credentials**:
```bash
# Extract backup
tar -xzf credentials_backup_$(date +%Y%m%d).tar.gz

# Copy to credentials directory
cp -r .env-keycloak-credentials-dir/* \
    deployment/local/docker-compose/.env-keycloak-credentials-dir/

# Restart services to pick up credentials
make restart
```

---

## Summary

### Key Takeaways

1. **Authentication**: Admins access credentials through container volume mounts (no manual entry)
2. **User Management**: Use `add_keycloak_user.py` for user lifecycle management
3. **Service Tokens**: Use `create_service_api_token.py` for non-interactive access
4. **Credential Rotation**: Use `make fix-credentials` to regenerate all secrets
5. **Health Monitoring**: Use `service_health_manager.py` for proactive monitoring
6. **Security**: Rotate tokens before expiration, enforce strong passwords, audit logs

### Quick Reference Commands

```bash
# User Management
make add-user USERNAME=alice PASSWORD=pass GROUPS=notebook-users
make list-keycloak-groups

# Service Token Management
make create-service-token NAME=my-service GROUPS=notebook-users TTL_DAYS=90
make list-service-tokens
make revoke-service-token TOKEN=sk-service-...

# Credential Management
make fix-credentials
make sync-credentials
make validate-credentials-exist

# Service Health
make validate-comprehensive-health
make validate-credentials
make validate-mcp-tools-discovery

# Troubleshooting
./scripts/deps/discover_admin_cli_secret.sh
docker logs orchestration_service --tail 100
docker exec postgres psql -U admin -d postgres
```

### Related Documentation

#### Administrative Scripts

- **User Management Script**: `scripts/deps/add_keycloak_user.py`
- **Service Token Script**: `scripts/deps/create_service_api_token.py`
- **Service Health Manager**: `scripts/deps/service_health_manager.py`
- **Scripts README**: `scripts/deps/README.md`

#### Examples & Testing

The `examples/` directory provides comprehensive testing and integration examples for administrators:

- **Examples README**: `examples/README.md` - Complete guide to all example patterns
- **Validation Script**: `examples/scripts/validate-langgraph-examples.py` - Systematic validation of framework components
- **OpenAI Client Example**: `examples/openai_client_service_token_example.py` - Service token authentication pattern
- **Standalone Mode**: `examples/requirements.txt` - Run examples without ADEPT framework installation
- **Docker Support**: `examples/Dockerfile` - Isolated example execution in containers

**Testing Service Tokens (Standalone Mode)**:
```bash
# 1. Install minimal dependencies
pip install -r examples/requirements.txt

# 2. Set service token
export ADEPT_SERVICE_API_TOKEN="sk-service-..."
export AGENT_GATEWAY_URL="http://localhost:8083/v1"

# 3. Run example (works without ADEPT framework)
python examples/openai_client_service_token_example.py
```

**Testing with Docker** (for isolated environments):
```bash
# Build standalone image
docker build -t adept-examples:standalone --target standalone examples/

# Run with service token (dual-network pattern for service access)
docker run --rm \
    --network=adept_application_network \
    --network=adept_frontend_network \
    -e ADEPT_SERVICE_API_TOKEN="sk-service-..." \
    -e AGENT_GATEWAY_URL="http://agent_gateway:8081/v1" \
    adept-examples:standalone \
    python /app/examples/openai_client_service_token_example.py
```

**Comprehensive Validation**:
```bash
# Validate all components (dual-network pattern)
docker run --rm \
    --network=adept_application_network \
    --network=adept_frontend_network \
    -v "$(pwd)/.env-keycloak-credentials-dir":/app/credentials:ro \
    -e SECRET_RETRIEVAL_METHOD=file \
    adept-examples:standalone \
    python /app/examples/scripts/validate-langgraph-examples.py
```

#### Related Documentation

- **[Platform AI Engineer Onboarding](PLATFORM_AI_ENGINEER_ONBOARDING.md)** -- developer setup, architecture, testing, and workflows
- **[Client-Side Certificate Trust Guide](guides/CLIENT_CERTIFICATE_TRUST.md)** -- trust ADEPT's self-signed TLS cert on workstations (macOS/Linux/Windows)
- **[Ansible Deployment Guide](../deployment/ansible/README.md)** -- VM preparation playbooks, Galaxy collection prerequisites, multi-cloud deployment
- **[Domain SME Guide](DOMAIN_SME_VIBE_CODING_GUIDE.md)** -- interactive AI-powered development workflows for domain experts

---

**Document Version**: 2.0 (2026-03-30)
**Last Updated**: Major cleanup -- consolidated OAuth2 sections, removed deprecated SIGHUP content, extracted Client-Side Certificate Trust to standalone guide, fixed deprecated network references, updated TOC
**Maintainer**: ADEPT Framework Team
