# ADEPT A2A Gateway Mesh Workshop

**Purpose**: Hands-on workshop for setting up Agent-to-Agent (A2A) communication between independent ADEPT instances across different hosts.

**Target Audience**: System administrators, platform engineers, DevOps teams deploying distributed ADEPT infrastructure.

**Prerequisites**:
- Two or more ADEPT instances running on separate hosts (VMs, containers, or physical servers)
- Network connectivity between hosts (test with `ping <remote_ip>`)
- Basic command-line familiarity

**Workshop Duration**: 45-60 minutes

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Environment Setup](#environment-setup)
3. [Workshop Steps](#workshop-steps)
4. [Validation Tests](#validation-tests)
5. [Troubleshooting](#troubleshooting)
6. [Advanced Topics](#advanced-topics)

---

## Architecture Overview

### What is A2A?

**Agent-to-Agent (A2A)** communication enables independent ADEPT instances to:
- Discover and register peer gateways
- Delegate tasks to remote instances
- Maintain complete autonomy (separate databases, credentials, services)

### Key Principles

1. **Complete Independence**: Each ADEPT instance has:
   - Own PostgreSQL database
   - Own Redis cache
   - Own Keycloak identity provider
   - Own MCP servers
   - Own nginx_proxy and certificates

2. **Zero Shared State**: No shared infrastructure between instances

3. **A2A Protocol**: ONLY interaction mechanism between instances

### Example Topology

```
┌─────────────────────────────────────┐         ┌─────────────────────────────────────┐
│  ADEPT Instance A (Azure VM)        │         │  ADEPT Instance B (AWS EC2)         │
│  IP: 10.0.0.2                     │         │  IP: 10.0.0.1                    │
│                                     │         │                                     │
│  nginx_proxy → agent_gateway        │         │  nginx_proxy → agent_gateway        │
│       ↓              ↓              │         │       ↓              ↓              │
│  orchestration   gateway_registry   │         │  orchestration   gateway_registry   │
│       ↓              ↓              │         │       ↓              ↓              │
│  PostgreSQL      Keycloak           │         │  PostgreSQL      Keycloak           │
│                                     │         │                                     │
└─────────────────────────────────────┘         └─────────────────────────────────────┘
                    │                                           │
                    │                                           │
                    └────────────── A2A Protocol ───────────────┘
                           (HTTPS, mutual registration)
```

---

## Environment Setup

### Execution Environment

**Where to Run Workshop Scripts**:

These scripts are designed to run **on the host** (your VM or physical machine), not inside Docker containers, because they:
- Need Docker access to check running containers (`docker ps`, `docker exec`)
- Run `make` commands from the ADEPT project root
- Detect the host's IP address for peer registration
- Interact with services via `localhost` port mappings

**Prerequisites on Host**:
```bash
# Required
- Docker and Docker Compose
- Bash shell
- curl
- jq (for JSON parsing)

# Optional but recommended
- agentic CLI (pip install -e src/)
- make (for convenience targets)
```

**If Host Prerequisites Missing**: See [Container-Based Alternative](#container-based-alternative-advanced) below for running workshop from inside Docker.

### Prerequisites Check

Before starting, verify:

1. **ADEPT Running**: Both instances are healthy
2. **Network Connectivity**: Hosts can reach each other
3. **Firewall Rules**: Port 443 (HTTPS) or 8083 (HTTP) open
4. **OAuth Configuration**: If accessing via IP, redirect URIs registered
5. **agentic CLI Installed**: `pip install -e src/` (from project root)
6. **CLI Health Check**: `agentic config doctor` (verifies SDK, config, gateway connectivity)

### Workshop Scripts

All workshop scripts are IP-agnostic and located in `examples/a2a-workshop/scripts/`:

| Script | Purpose | Required Args |
|--------|---------|---------------|
| `00_verify_environment.sh` | Check ADEPT services are healthy | None |
| `01_generate_a2a_token.sh` | Generate A2A service token | `--name <token-name>` |
| `02_register_peer.sh` | Register remote peer gateway | `--peer-ip <ip> --peer-alias <name>` |
| `03_test_connectivity.sh` | Test A2A connection to peer | `--peer-alias <name>` |
| `04_end_to_end_test.sh` | Full A2A workflow validation | `--peer-ip <ip> --peer-alias <name>` |
| `05_start_opentrons_server.sh` | Start OpenTrons MCP server (Host B) | None |
| `06_register_opentrons_capability.sh` | Register Opentrons capability (Host B) | None |
| `07_opentrons_a2a_delegation.sh` | Delegate protocol execution (Host A) | `--peer-alias <name>` |
| *(Academy — Makefile-driven)* | *Steps 8-10 use `make setup` from `examples/academy_mcp_server/`* | |

**All scripts automatically detect**:
- Local IP address (via hostname -I or network interface)
- ADEPT service URLs (agent_gateway, gateway_registry, keycloak)
- Credentials directory location

---

## Workshop Steps

### Step 0: Verify Environment (Both Hosts)

**Purpose**: Ensure ADEPT services are running and healthy before A2A registration.

```bash
cd examples/a2a-workshop/scripts

# Run environment verification
./00_verify_environment.sh

# Expected output:
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ADEPT Environment Verification
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Detected Local IP: 10.0.0.2
# ✅ Docker is running
# ✅ agent_gateway is running
# ✅ orchestration_service is running
# ✅ gateway_registry is running
# ✅ keycloak is running
# ✅ Agent Gateway API is accessible
# ✅ Gateway Registry health check passed
#
# Environment Status: ✅ READY FOR A2A REGISTRATION
```

**If any checks fail**: See [Troubleshooting](#troubleshooting) section.

---

### Step 0.5: Setup A2A Credentials (Both Hosts) - NEW!

**Purpose**: Configure service-to-service authentication credentials for A2A operations using the agentic CLI.

**Background**: As of Session 53, ADEPT CLI now supports automatic credential management instead of manual environment variable setup. This simplifies A2A operations and supports multiple profiles for different environments.

**On Both VMs (Azure + AWS)**:

#### Option 1: Auto-Discovery (Recommended)

```bash
# Activate Python environment
source .venv311/bin/activate

# Auto-discover credentials from ADEPT installation
agentic auth cred-setup --auto-discover --profile default --force

# Expected output:
# ✅ Found credentials in ADEPT installation
#      Client ID:  validation-runner-client
#  Client Secret:  0fhVDS3BID...
#   Keycloak URL:  http://localhost:8180
#          Realm:  master
#   Registry URL:  http://localhost:8086
#
# ✅ Credentials saved to ~/.adept-agentic/credentials (profile: default)
```

#### Option 2: Manual Setup

```bash
# Interactive setup (prompts for values)
agentic auth cred-setup --profile default

# Or specify all values
agentic auth cred-setup \
  --profile default \
  --client-id validation-runner-client \
  --client-secret <YOUR_SECRET> \
  --keycloak-url http://localhost:8180 \
  --registry-url http://localhost:8086 \
  --force
```

#### Verify Credentials

```bash
# Test authentication
agentic auth cred-test --profile default

# Expected:
# ✅ Service authentication successful!

# List configured profiles
agentic auth cred-list

# Show profile details
agentic auth cred-show --profile default
```

#### Important: Docker Service Name Resolution

For CLI usage on the host, add Docker service names to `/etc/hosts`:

```bash
echo "127.0.0.1 keycloak gateway_registry agent_gateway" | sudo tee -a /etc/hosts

# Update credentials to use Docker service names
agentic auth cred-setup \
  --profile default \
  --client-id validation-runner-client \
  --client-secret <YOUR_SECRET> \
  --keycloak-url http://keycloak:8180 \
  --registry-url http://gateway_registry:8086 \
  --force
```

**Why This Matters**: Gateway Registry validates JWT token issuers. Tokens from `http://localhost:8180` have different issuer than `http://keycloak:8180`, causing 401 errors.

#### Benefits of Credential Management

- ✅ **No manual env vars**: Credentials stored securely in `~/.adept-agentic/credentials`
- ✅ **Multi-profile support**: Separate profiles for dev/staging/prod
- ✅ **Auto-discovery**: Detects credentials from ADEPT installation
- ✅ **Secure storage**: File permissions automatically set to 600
- ✅ **Easy sharing**: Export credentials as env vars or JSON

---

### Step 1: Generate A2A Service Token (Both Hosts)

**Purpose**: Create service tokens for authentication between gateways.

**On Azure VM (10.0.0.2)**:

```bash
# Generate service token for Azure → AWS communication
./01_generate_a2a_token.sh --name a2a-azure-to-aws --ttl-days 365

# Expected output:
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Generating A2A Service Token
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Token Name: a2a-azure-to-aws
# Groups: gateway-service
# TTL: 365 days
# ✅ Service token created successfully
# Token: sk-service-a2a-azure-to-aws-4K3q2gjWHNXMM9jKuC7PbpChNogiUgwg
# Expires: 2027-02-10
#
# 💡 Save this token - you'll need it for peer authentication

# Export token for use in later steps
export LOCAL_A2A_TOKEN="sk-service-a2a-azure-to-aws-..."
```

**On AWS EC2 (10.0.0.1)**:

```bash
# Generate service token for AWS → Azure communication
./01_generate_a2a_token.sh --name a2a-aws-to-azure --ttl-days 365

# Export token
export LOCAL_A2A_TOKEN="sk-service-a2a-aws-to-azure-..."
```

**What This Does**:
- Creates a bearer token with `gateway-service` group membership
- Token authenticates A2A requests via Keycloak
- 365-day TTL suitable for long-lived inter-instance connections

---

### Step 2: Register Peer Gateway (Bidirectional)

**Purpose**: Register remote ADEPT instance as a peer for task delegation.

**On Azure VM**, register AWS as peer:

#### Option 1: Using Workshop Script

```bash
# Register AWS EC2 gateway
./02_register_peer.sh \
  --peer-ip 10.0.0.1 \
  --peer-alias aws-gateway \
  --description "AWS EC2 Production Gateway" \
  --tags "aws,ec2,us-east-1"

# Expected output:
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Registering Peer Gateway
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Local Gateway: 10.0.0.2
# Peer Gateway: 10.0.0.1 (aws-gateway)
# Registry URL: http://localhost:8086
#
# ✅ Peer gateway registered successfully
#
# Registered Peers:
# ┌──────────────┬───────────────────────────┬──────────────────────────────┐
# │ Alias        │ Public URL                │ Description                  │
# ├──────────────┼───────────────────────────┼──────────────────────────────┤
# │ aws-gateway  │ https://10.0.0.1/v1    │ AWS EC2 Production Gateway   │
# └──────────────┴───────────────────────────┴──────────────────────────────┘
```

**On AWS EC2**, register Azure as peer:

```bash
# Register Azure VM gateway
./02_register_peer.sh \
  --peer-ip 10.0.0.2 \
  --peer-alias azure-gateway \
  --description "Azure VM Development Gateway" \
  --tags "azure,vm,eastus"
```

**What This Does**:
- Stores peer metadata in gateway_registry database
- Enables task delegation via A2A protocol
- Bidirectional registration allows both instances to delegate to each other

---

### Step 3: Test Connectivity (Both Hosts)

**Purpose**: Verify A2A communication works before attempting task delegation.

**On Azure VM**, test connection to AWS:

```bash
./03_test_connectivity.sh --peer-alias aws-gateway

# Expected output:
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Testing A2A Connectivity
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Local Gateway: 10.0.0.2
# Peer Gateway: aws-gateway (10.0.0.1)
#
# Testing basic HTTP connectivity...
# ✅ HTTP connection successful
# Response time: 45ms
#
# Testing Agent Gateway API...
# ✅ Agent Gateway API accessible
# Response code: 401 (expected - auth required)
#
# Testing authenticated request...
# ✅ Authenticated request successful
# Response code: 200
# Response: {"models": [...]}
#
# Connectivity Status: ✅ READY FOR A2A TASK DELEGATION
```

**On AWS EC2**, test connection to Azure:

```bash
./03_test_connectivity.sh --peer-alias azure-gateway

# Expected response time: 40-60ms (depending on network)
```

**What This Tests**:
- Basic network connectivity (ping equivalent)
- HTTPS certificate validation
- Agent Gateway API availability
- Authentication with service token

---

### Step 4: End-to-End Validation (Optional)

**Purpose**: Run comprehensive A2A workflow including task delegation.

**On Azure VM**:

```bash
# Full E2E test against AWS peer
./04_end_to_end_test.sh \
  --peer-ip 10.0.0.1 \
  --peer-alias aws-gateway

# Expected output:
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# A2A End-to-End Validation
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Test 1: Environment verification... ✅ PASSED
# Test 2: Service token generation... ✅ PASSED
# Test 3: Peer registration... ✅ PASSED
# Test 4: Connectivity test... ✅ PASSED
# Test 5: Task delegation... ✅ PASSED
#
# All tests passed! A2A setup is complete.
#
# Next steps:
# - Use 'agentic a2a list-peers' to view all registered peers
# - Use 'agentic a2a update-peer <alias> --add-tags "tag"' to add capabilities
# - Use 'agentic a2a test-connection <alias>' to test connectivity
# - Use 'agentic a2a remove-peer <alias>' to unregister peers
# - Use 'agentic config doctor' to verify CLI health and gateway connectivity
```

**What This Tests**:
- Complete A2A registration workflow
- Bidirectional connectivity
- Task delegation (if orchestration supports it)
- Error handling and recovery

---

## Validation Tests

### Manual Validation Commands

After completing the workshop, verify A2A setup manually:

**List Registered Peers**:
```bash
agentic a2a list-peers --format table

# Or with JSON output
agentic a2a list-peers --format json | jq .
```

**Test Connection**:
```bash
agentic a2a test-connection aws-gateway --verbose
```

**Check Gateway Registry Database**:
```bash
docker exec postgres psql -U admin -d postgres -c \
  "SELECT alias, public_url, capabilities, last_health_check
   FROM gateway_registry
   ORDER BY created_at DESC;"
```

**Verify Service Tokens**:
```bash
# List all service tokens
make list-service-tokens

# Check token works for A2A auth
curl -k -H "Authorization: Bearer $LOCAL_A2A_TOKEN" \
  https://localhost/v1/models
# Expected: 200 OK with model list
```

**CLI Health Check**:
```bash
# Run comprehensive health check (SDK, config, gateway connectivity, storage)
agentic config doctor

# Show current configuration with directory info and disk usage
agentic config show --verbose

# Backup configuration before making changes
agentic config backup --output pre_workshop_config.tar.gz
```

---

## Troubleshooting

### Issue: Environment verification fails

**Symptom**: `00_verify_environment.sh` reports services are not running.

**Solution**:
```bash
# Check Docker is running
docker ps

# Start ADEPT if not running
cd /path/to/adept
make start

# Wait for services to be ready (30-60 seconds)
sleep 60

# Re-run verification
./00_verify_environment.sh
```

---

### Issue: Cannot detect local IP address

**Symptom**: Scripts report "Failed to detect local IP address".

**Solution**:
```bash
# Set LOCAL_IP environment variable manually
export LOCAL_IP="10.0.0.2"

# Re-run script
./00_verify_environment.sh
```

---

### Issue: SDK Installation Fails

**Symptom**: `ModuleNotFoundError: No module named 'agentic_framework_sdk'` or `AttributeError: module 'agentic_framework_sdk.cli.main' has no attribute 'main'`

**Root Cause**: Outdated installation path or old SDK installation.

**Solution**:
```bash
# Uninstall old version
pip uninstall agentic-framework-sdk -y

# Install from correct location (project root)
cd /path/to/adept-extended-2025-11-07
pip install -e src/

# Verify installation
python -c "import agentic_framework_sdk; print('✅ SDK installed')"
agentic --help  # Shows available commands
```

**Alternative (if host installation fails)**:
Use Docker container with SDK pre-installed:
```bash
docker run --rm -it \
  --network=adept_application_network \
  --network=adept_frontend_network \
  -v "$(pwd)":/app/adept:ro \
  -e LOCAL_IP="10.0.0.2" \
  demo-bootstrap:latest \
  bash

# Inside container, SDK is already available
agentic a2a list-peers
```

---

### Issue: Token generation fails with 401 error

**Symptom**: `01_generate_a2a_token.sh` fails with "401 unauthorized_client".

**Root Cause**: Missing or incorrect `KC_ADMIN_CLI_SECRET`.

**Solution**:
```bash
# Discover correct admin-cli secret
cd /path/to/adept
./scripts/deps/discover_admin_cli_secret.sh

# Update .env file
vim .env
# Set: KC_ADMIN_CLI_SECRET=<correct-secret>

# Rebuild orchestration service
make rebuild-orchestrator

# Re-run token generation
cd examples/a2a-workshop/scripts
./01_generate_a2a_token.sh --name a2a-test
```

---

### Issue: Peer registration fails

**Symptom**: `02_register_peer.sh` fails with "Failed to register peer gateway".

**Possible Causes**:

1. **Gateway Registry not running**:
   ```bash
   docker ps | grep gateway_registry
   # If not running: make start
   ```

2. **Missing authentication credentials**:
   ```bash
   # Check VALIDATION_RUNNER credentials exist
   ls -la deployment/local/docker-compose/.env-keycloak-credentials-dir/ | grep VALIDATION_RUNNER

   # Regenerate if missing
   make fix-credentials
   ```

3. **Invalid peer URL format**:
   - Must use HTTPS: `https://10.0.0.1/v1`
   - Include `/v1` path
   - No trailing slashes

---

### Issue: Connection test fails

**Symptom**: `03_test_connectivity.sh` reports "Connection refused" or "Connection timeout".

**Root Cause**: Network firewall blocking traffic between hosts.

**Solution**: Open required ports in security groups/firewalls.

**AWS Security Group**:
```bash
# Add inbound rule for HTTPS from Azure
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxxx \
  --protocol tcp \
  --port 443 \
  --cidr 10.0.0.2/32 \
  --description "ADEPT A2A from Azure VM"
```

**Azure NSG**:
```bash
# Add inbound rule for HTTPS from AWS
az network nsg rule create \
  --resource-group <rg-name> \
  --nsg-name <nsg-name> \
  --name allow-adept-a2a-from-aws \
  --protocol tcp \
  --priority 1000 \
  --destination-port-range 443 \
  --source-address-prefix 10.0.0.1/32
```

**Test network connectivity manually**:
```bash
# From Azure, test AWS connectivity
curl -k https://10.0.0.1/v1/models
# Expected: 401 Unauthorized (auth required) or 200 OK

# From AWS, test Azure connectivity
curl -k https://10.0.0.2/v1/models
```

---

### Issue: Authentication fails (401 Unauthorized)

**Symptom**: Connection test succeeds but returns 401 even with valid token.

**Possible Causes**:

1. **Token not in SERVICE_API_KEYS_CONFIG**:
   ```bash
   # Check if token exists in config
   docker exec orchestration_service bash -c "
     python3 -c \"
from agentic_framework_pkg.core.secrets_manager import get_secret
import json
config = json.loads(get_secret('SERVICE_API_KEYS_CONFIG'))
print('sk-service-a2a-...' in config)
     \"
   "
   # Expected: True
   ```

2. **Token expired or revoked**:
   ```bash
   # List all service tokens with status
   make list-service-tokens

   # Regenerate if expired
   ./01_generate_a2a_token.sh --name a2a-replacement
   ```

---

### Issue: Peer shows as registered but connection fails

**Symptom**: Peer appears in `agentic a2a list-peers` but connectivity test fails.

**Debug Steps**:

1. **Verify peer URL is correct**:
   ```bash
   agentic a2a list-peers --format json | jq '.[] | select(.alias == "aws-gateway")'
   # Check public_url is correct: "https://10.0.0.1/v1"
   ```

2. **Test peer gateway directly**:
   ```bash
   curl -k https://10.0.0.1/v1/models
   # Should return 401 or 200 (not connection refused)
   ```

3. **Remove and re-register peer**:
   ```bash
   agentic a2a remove-peer aws-gateway --yes
   ./02_register_peer.sh --peer-ip 10.0.0.1 --peer-alias aws-gateway
   ```

---

## Container-Based Alternative (Advanced)

For environments where the host lacks prerequisites (agentic CLI, make, etc.), you can run workshop scripts from inside a Docker container.

### Option 1: Use Orchestration Service Container

```bash
# Enter orchestration service container (has all tools)
docker exec -it orchestration_service bash

# Navigate to workshop scripts
cd /app/examples/a2a-workshop/scripts

# Set LOCAL_IP manually (container can't auto-detect host IP)
export LOCAL_IP="10.0.0.2"  # Your host's actual IP

# Run workshop steps
./00_verify_environment.sh
./01_generate_a2a_token.sh --name a2a-container-test
./02_register_peer.sh --peer-ip 10.0.0.1 --peer-alias aws-gateway
./03_test_connectivity.sh --peer-alias aws-gateway
```

**Limitations**:
- ⚠️ Must manually set `LOCAL_IP` environment variable
- ⚠️ Network access may differ (use `agent_gateway:8081` instead of `localhost:8083`)
- ⚠️ Registry URL may need adjustment: `http://gateway_registry:8086` instead of `http://localhost:8086`

### Option 2: Custom Workshop Container (Coming Soon)

For fully isolated workshop execution, a dedicated Docker image with all dependencies will be provided:

```bash
# Build workshop container (future)
docker build -t adept-a2a-workshop:latest examples/a2a-workshop/

# Run workshop interactively
docker run -it --rm \
  --network=adept_application_network \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e LOCAL_IP="10.0.0.2" \
  -e PEER_IP="10.0.0.1" \
  adept-a2a-workshop:latest
```

**Benefits**:
- ✅ No host prerequisites except Docker
- ✅ Reproducible environment
- ✅ Easy CI/CD integration

---

## Advanced Topics

### Using Custom Hostnames Instead of IPs

If you have DNS configured:

```bash
# Register peer with hostname
./02_register_peer.sh \
  --peer-ip gateway-b.example.com \
  --peer-alias prod-gateway \
  --description "Production Gateway"

# OAuth redirect URIs must be registered for hostname
# See: docs/implementation-plans/session-52/16_OAUTH_REDIRECT_URI_WEBORIGIN_REQUIREMENT.md
```

---

### Multi-Instance Mesh (3+ Gateways)

For N-gateway mesh topology:

```bash
# On Gateway A, register B and C
./02_register_peer.sh --peer-ip 10.0.0.1 --peer-alias gateway-b
./02_register_peer.sh --peer-ip 10.20.30.40 --peer-alias gateway-c

# On Gateway B, register A and C
./02_register_peer.sh --peer-ip 10.0.0.2 --peer-alias gateway-a
./02_register_peer.sh --peer-ip 10.20.30.40 --peer-alias gateway-c

# On Gateway C, register A and B
./02_register_peer.sh --peer-ip 10.0.0.2 --peer-alias gateway-a
./02_register_peer.sh --peer-ip 10.0.0.1 --peer-alias gateway-b
```

**Result**: Full mesh topology where any gateway can delegate to any other.

---

### Token Rotation

For long-lived deployments, rotate A2A tokens periodically:

```bash
# Generate new token
./01_generate_a2a_token.sh --name a2a-azure-to-aws-v2 --ttl-days 365

# Update peer registration with new token (if needed)
# ... implementation depends on A2A protocol token storage ...

# Revoke old token
make revoke-service-token TOKEN=sk-service-a2a-azure-to-aws-v1-...
```

---

### Monitoring A2A Health

**Automated health checks**:

```bash
# Cron job to test A2A connectivity every 5 minutes
*/5 * * * * /path/to/examples/a2a-workshop/scripts/03_test_connectivity.sh --peer-alias aws-gateway --quiet >> /var/log/adept-a2a-health.log 2>&1
```

**Check peer health status**:
```bash
docker exec postgres psql -U admin -d postgres -c \
  "SELECT alias, public_url, last_health_check,
          EXTRACT(EPOCH FROM (NOW() - last_health_check)) as seconds_since_check
   FROM gateway_registry
   ORDER BY last_health_check DESC;"
```

---

### Cross-VM JWKS Federation (Session 80)

When independent ADEPT instances delegate tasks across VMs, each VM's Keycloak has different signing keys. The `validate_jwt_multi_stack()` function now supports **peer JWKS federation** -- if a JWT's kid isn't found locally, it checks `A2A_TRUSTED_PEER_JWKS_URLS` for peer Keycloak endpoints.

**Configuration** (add to `.env` on each VM):
```bash
# Point to peer VM's JWKS endpoint (via nginx_proxy)
A2A_TRUSTED_PEER_JWKS_URLS=https://<PEER_IP>/realms/master/protocol/openid-connect/certs
```

For full architecture details, see:
- [A2A Architecture: Cross-VM JWKS Federation](docs/ARCHITECTURE.md#cross-vm-jwks-federation-session-80)
- [Bugfix Documentation](../../docs/bugfixes/SESSION_80_A2A_CROSS_VM_USER_TOKEN_VALIDATION.md)

---

## Related Documentation

### Core Documentation
- **Systems Administrator Onboarding**: `docs/SYSTEMS_ADMINISTRATOR_ONBOARDING.md`
  - Section: "A2A Gateway Mesh Management"
  - Section: "Accessing ADEPT via IP Address"

- **CLAUDE.md**: Project instructions and A2A architecture overview
  - Section: "A2A (Agent-to-Agent) Credential Management"

### Implementation Plans
- **Phase 2 Design**: `docs/implementation-plans/session-52/14_PHASE2_REVISED_INDEPENDENT_INSTANCES.md`
- **Phase 2 Proposal**: `docs/implementation-plans/session-52/15_PHASE2_IMPLEMENTATION_PROPOSAL.md`
- **OAuth Configuration**: `docs/implementation-plans/session-52/16_OAUTH_REDIRECT_URI_WEBORIGIN_REQUIREMENT.md`

### SDK Documentation
- **A2A CLI Commands**: `src/agentic_framework_sdk/cli/a2a_commands.py`
- **Unit Tests**: `tests/unit/agentic_framework_sdk/cli/test_a2a_commands.py`
- **E2E Tests**: `tests/e2e/test_a2a_cli_commands.py`

---

## Phase 2: A2A Task Delegation — OpenTrons Protocol Execution

Phase 2 demonstrates real multi-host, multi-cloud A2A task delegation using the OpenTrons liquid handling protocol execution as the delegated workload.

### Architecture

```
Host A (AWS EC2)                           Host B (Azure VM)
┌─────────────────────┐                    ┌─────────────────────────┐
│ ADEPT Stack         │                    │ ADEPT Stack             │
│  - agent_gateway    │  A2A delegation    │  - agent_gateway        │
│  - orchestration    │ ──────────────►    │  - orchestration        │
│  - gateway_registry │                    │  - gateway_registry     │
│  - keycloak         │                    │  - keycloak             │
│                     │                    │  - opentrons_mcp_server │
│  (no OpenTrons)     │                    │    (port 9003)          │
└─────────────────────┘                    └─────────────────────────┘
```

**Host A** (requesting host) has no OpenTrons capability. **Host B** (OpenTrons host) runs the OpenTrons MCP server and registers itself with the "Opentrons" capability tag. Host A discovers Host B via the gateway registry and delegates protocol execution via A2A.

### Prerequisites

- Phase 1 complete (Steps 0-4): Both hosts registered and connectivity verified
- Decide which host will run OpenTrons (the "OpenTrons host" / Host B)
- The other host is the "requesting host" / Host A

---

### Step 5: Start OpenTrons MCP Server (Host B Only)

**Purpose**: Build and start the OpenTrons MCP server container on the OpenTrons host.

**On Host B (Azure VM)**:

```bash
cd examples/a2a-workshop/scripts

# Start OpenTrons MCP server
./05_start_opentrons_server.sh

# Expected output:
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# OpenTrons MCP Server Setup
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ✅ Docker is available
# ✅ Docker Compose v2 is available
# ✅ adept_application_network exists
# Building OpenTrons MCP server image...
# ✅ Image built successfully
# ✅ Container started
# ✅ Health check passed
#
# ✅ Server URL: http://localhost:9003
# ✅ Health:     http://localhost:9003/health
# ✅ MCP:        http://localhost:9003/mcp
```

**Verify manually**:
```bash
curl http://localhost:9003/health
# {"status": "healthy", "hardware_mode": "simulation", "mcp_tools": ["execute_opentrons_protocol"]}
```

---

### Step 6: Register Opentrons Capability (Host B Only)

**Purpose**: Register the current gateway with the "Opentrons" capability tag in the gateway registry, making it discoverable by other hosts.

**On Host B (Azure VM)**:

```bash
# Register Opentrons capability
./06_register_opentrons_capability.sh

# Expected output:
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Register Opentrons Capability
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ✅ Gateway alias: azure-gateway
# ✅ OpenTrons MCP server is healthy
# ✅ S2S token obtained
# ✅ Updated gateway 'azure-gateway' with Opentrons capability
# ✅ OpenTrons tool registered as external MCP tool
#
# ✅ Gateway 'azure-gateway' now advertises Opentrons capability
```

**What the script does** (two registration steps):

1. **Gateway capability registration** (via S2S `gateway-client` token):
   - Registers/updates the gateway in the registry with the `Opentrons` capability tag
   - Uses client credentials grant (`gateway-client`) — requires `gateway-service` group

2. **External tool registration** (via admin ROPC token):
   - Registers `execute_opentrons_protocol` as an external **MCP** tool in the orchestration service
   - Uses ROPC grant with `login-client` and admin user — tool registration requires `admin` group
   - Tool config: `protocol: "mcp"`, URL: `http://opentrons_mcp_server:9003/mcp`
   - The `ExternalToolManager` creates a `StructuredTool` that uses FastMCP `Client` for MCP JSON-RPC (initialize → tools/call → response)
   - Stored in Redis as `external_tool:execute_opentrons_protocol`

**Critical: URL must include `/mcp` path**. FastMCP `Client(url)` passes the URL directly to `StreamableHttpTransport` — it does **NOT** auto-append `/mcp`. Without it, the client POSTs to `/` which returns 404.

**MCP protocol flow** (what happens when the tool is invoked):
```
ExternalToolManager._mcp_tool_func()
  └─ async with Client("http://opentrons_mcp_server:9003/mcp") as client:
       result = await client.call_tool("execute_opentrons_protocol_tool", args)
       # FastMCP Client handles:
       #   POST /mcp 200  (MCP initialize handshake)
       #   POST /mcp 202  (tools/call request)
       #   GET  /mcp 200  (SSE result stream)
       #   POST /mcp 200  (acknowledge)
       #   DELETE /mcp 200 (session cleanup)
```

**Pydantic schema validation**: The OpenTrons MCP server defines the tool parameter as `Union[ProtocolSchema, dict]`, where `ProtocolSchema` is a Pydantic model with nested `TransferSchema`. This gives FastMCP rich JSON schema generation:

```json
{
  "protocol_json": {
    "anyOf": [
      { "$ref": "#/$defs/ProtocolSchema" },
      { "type": "object" }
    ]
  }
}
```

The `ProtocolSchema` includes:
- `protocol_name` (string, required)
- `plate_type` (enum: "96-well" | "384-well", default: "96-well")
- `transfers` (array of `TransferSchema`, min 1, max 96):
  - `source_well`, `dest_well` (string, A1–H12 format)
  - `volume_ul` (number, 0.1–1000.0)
  - `tip_type` (enum: p10_single | p20_single | p300_single | p1000_single)

FastMCP coerces incoming JSON dicts into `ProtocolSchema` instances automatically; the `dict` fallback handles edge cases. A second validation layer (`OpentronProtocolValidator`) enforces domain-specific safety rules (volume-per-well limits, tip capacity matching).

**Note**: The script obtains two separate tokens because:
- Gateway registry operations require `gateway-service` group (S2S token)
- Tool registration endpoints require `admin` group (admin ROPC token via `login-client`)

**Alternative: Register via agentic CLI** (from a host with CLI installed):
```bash
# Delete existing registration (if any)
agentic tools delete execute_opentrons_protocol -y --username admin --password admin

# Register with MCP protocol
agentic tools register execute_opentrons_protocol \
  -d "Execute an OpenTrons liquid handling protocol..." \
  -p mcp \
  -u http://opentrons_mcp_server:9003/mcp \
  --tool-name execute_opentrons_protocol_tool \
  --args-schema '{"protocol_json":{"type":"object","description":"Protocol specification..."},"dry_run":{"type":"boolean","description":"Validate without executing","default":true}}' \
  --username admin --password admin
```

**Alternative: Set capability via environment variable** before starting the ADEPT stack:
```bash
# In .env file on Host B:
AGENT_GATEWAY_CAPABILITIES=RAG,HPC-BLAST,CodeExecution,Opentrons
```
Note: The env var approach only registers the capability tag; you still need to run the script (or CLI) to register the external tool.

---

### Makefile Automation (Session 59)

The OpenTrons MCP server lifecycle is automated via `examples/opentrons_mcp_server/Makefile`:

```bash
# From project root — one command does everything
make opentrons-setup          # Build + start + wait-healthy + register-tool + verify

# Rebuild after code changes
make opentrons-rebuild        # No-cache rebuild + re-register tool

# Tear down when done
make opentrons-teardown       # Deregister tool + stop container

# Individual operations
make opentrons-register       # Register tool via agentic CLI
make opentrons-deregister     # Remove tool from ADEPT
make opentrons-health         # Check /health endpoint
make opentrons-smoke-test     # E2E test via Response API
make opentrons-logs           # Tail container logs
```

The Makefile auto-detects the `agentic` CLI from `.venv311/`, `.venv/`, or PATH. It registers the tool with `protocol: mcp` and verifies in both Redis and the Gateway API.

---

### Step 7: Delegate Protocol Execution (Host A → Host B)

**Purpose**: From the requesting host, delegate an OpenTrons protocol execution to the peer with Opentrons capability via A2A.

**On Host A (AWS EC2)**:

```bash
# Dry-run delegation (validates protocol on remote host)
./07_opentrons_a2a_delegation.sh --peer-alias azure-gateway

# Expected output:
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# A2A OpenTrons Protocol Delegation
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ✅ S2S token obtained
# ✅ Found peer: azure-gateway
# ✅ User token obtained
#
#   Protocol: A2A Workshop - Cross-Host Transfer Protocol
#   Transfers: 3 (A1→B1 50μL, A2→B2 100μL, A3→B3 75μL)
#   Mode: Dry Run (validation only)
#
# ✅ A2A OpenTrons delegation completed successfully

# Execute protocol (simulation mode)
./07_opentrons_a2a_delegation.sh --peer-alias azure-gateway --execute
```

**Auto-discovery**: If `--peer-alias` is omitted, the script queries the gateway registry for any peer with "Opentrons" capability:
```bash
./07_opentrons_a2a_delegation.sh
# Automatically finds and delegates to the first peer with Opentrons capability
```

---

### Phase 2 Teardown

After the workshop, clean up the OpenTrons resources:

**On Host B** (OpenTrons host):
```bash
# Stop OpenTrons MCP server
docker compose -f examples/opentrons_mcp_server/docker-compose.opentrons.yaml down

# Optionally remove the Opentrons capability from registry
# (The gateway re-registers with default capabilities on restart)
```

---

### Phase 2 Troubleshooting

**OpenTrons server won't start**:
```bash
# Check container logs
docker logs opentrons_mcp_server --tail 20

# Verify adept_application_network exists
docker network ls | grep adept_application_network

# Rebuild from scratch
./05_start_opentrons_server.sh
```

**Capability not registered**:
```bash
# Check gateway alias in .env
grep AGENT_GATEWAY_ALIAS .env

# Manually specify alias
./06_register_opentrons_capability.sh --gateway-alias my-gateway
```

**A2A delegation fails**:
```bash
# Verify peer is reachable
curl -k https://<peer_ip>/v1/models

# Check SSRF allowlist includes peer IP
grep ALLOWED_PEER_CIDRS .env

# Verify OpenTrons server on peer
curl http://<peer_ip>:9003/health
```

---

### Phase 2 Key Discoveries (Session 59 UAT)

These issues were discovered during end-to-end smoke testing and are now fixed:

| # | Issue | Root Cause | Fix |
|---|-------|-----------|-----|
| 1 | MCP Client POSTs to `/` → 404 | FastMCP `Client(url)` does NOT auto-append `/mcp` | URL must include `/mcp` path |
| 2 | `protocol_json Missing required argument` | `StructuredTool` had empty schema (no `--args-schema`) | Added `args_schema` with `protocol_json` + `dry_run` |
| 3 | `Context.get_current()` AttributeError | FastMCP 2.x uses parameter injection, not `Context.get_current()` | Changed to `ctx: Context = None` parameter |
| 4 | `CallToolResult.isError` AttributeError | FastMCP `Client.call_tool()` returns `fastmcp.client.client.CallToolResult` (snake_case) not `mcp.types.CallToolResult` (camelCase) | Use `result.is_error` + `raise_on_error=False` |
| 5 | Tool function accepts bare `dict` — no schema info | `protocol_json: dict` gives FastMCP no type information | `Union[ProtocolSchema, dict]` for rich schema + dict fallback |

**Files modified during UAT**:
- `examples/opentrons_mcp_server/server.py` — Pydantic `Union[ProtocolSchema, dict]`, Context parameter injection, structured logging
- `examples/opentrons_mcp_server/main.py` — Logging configuration
- `src/.../orchestration_service/external_tool_manager.py` — `is_error` + `raise_on_error=False`
- `examples/a2a-workshop/scripts/06_register_opentrons_capability.sh` — URL `/mcp` fix, improved tool description

**Full UAT log**: `docs/implementation-reports/SESSION_59_A2A_OPENTRONS_UAT_LOG.md` (Part 6, Step 6)

---

### Related Documentation

- **Multi-Host Guide**: `docs/workshop/A2A_OPENTRONS_MULTI_HOST_GUIDE.md`
- **Implementation Tracker**: `docs/implementation-reports/SESSION_A2A_OPENTRONS_MULTI_HOST_IMPLEMENTATION_TRACKER.md`
- **UAT Log**: `docs/implementation-reports/SESSION_59_A2A_OPENTRONS_UAT_LOG.md`
- **OpenTrons Makefile**: `examples/opentrons_mcp_server/Makefile` - Build, register, and teardown automation

---

## Phase 3: A2A Task Delegation — Academy Federated Agent Orchestration

Phase 3 demonstrates A2A task delegation using [Academy](https://github.com/agentos-project/academy) federated agent lifecycle operations. Academy is a middleware for distributed scientific workflows (Slurm, sensors, Globus). This phase follows the same pattern as Phase 2 (Opentrons) but with 4 registered tools instead of 1.

### Architecture

```
Host A (AWS EC2)                           Host C (Academy Host)
┌─────────────────────┐                    ┌─────────────────────────┐
│ ADEPT Stack         │                    │ ADEPT Stack             │
│  - agent_gateway    │  A2A delegation    │  - agent_gateway        │
│  - orchestration    │ ──────────────►    │  - orchestration        │
│  - gateway_registry │                    │  - gateway_registry     │
│  - keycloak         │                    │  - keycloak             │
│                     │                    │  - academy_mcp_server   │
│  (no Academy)       │                    │    (port 9004)          │
└─────────────────────┘                    └─────────────────────────┘
```

**Host A** (requesting host) delegates agent lifecycle operations to **Host C** (Academy host) which runs the Academy MCP server with 4 tools.

### Registered Tools (4)

| Tool | Protocol | Description |
|------|----------|-------------|
| `launch_academy_agent` | MCP | Launch echo, counter, or compute agent |
| `invoke_agent_action` | MCP | Invoke action on a running agent |
| `list_academy_agents` | MCP | List all agents in current session |
| `shutdown_academy_agent` | MCP | Shut down a running agent |

### Agent Templates

| Agent | Actions | Purpose |
|-------|---------|---------|
| `EchoAgent` | `echo(message)`, `get_call_count()` | Integration testing |
| `CounterAgent` | `increment(value)`, `decrement(value)`, `get_count()`, `reset()` | Stateful demo |
| `ComputeAgent` | `factorial(n)`, `fibonacci(n)`, `is_prime(n)`, `get_computation_count()` | Scientific compute |

### Prerequisites

- Phase 1 complete (Steps 0-4): Both hosts registered and connectivity verified
- Decide which host will run Academy (the "Academy host" / Host C)

---

### Step 8: Start Academy MCP Server (Host C Only)

**Purpose**: Build and start the Academy MCP server container on the Academy host.

**On Host C**:

```bash
cd examples/academy_mcp_server

# Full lifecycle: build, start, register 4 tools, verify
make setup

# Expected output:
#   agentic CLI: /path/to/.venv311/bin/agentic
#   Docker network: adept_application_network exists
# --> Building Academy MCP Server image...
# --> Starting Academy MCP Server...
#   Container academy_mcp_server started on port 9004
# --> Waiting for container to become healthy...
#   Container healthy (attempt 3)
# --> Registering Academy tools (4 tools)...
#   [1/4] launch_academy_agent...
#   [2/4] invoke_agent_action...
#   [3/4] list_academy_agents...
#   [4/4] shutdown_academy_agent...
#   All 4 tools registered
# --> Verifying tool registration (4 tools)...
#   ✓ launch_academy_agent found in Redis
#   ✓ invoke_agent_action found in Redis
#   ✓ list_academy_agents found in Redis
#   ✓ shutdown_academy_agent found in Redis
#   Result: 4/4 tools verified
# DONE: Academy MCP Server setup complete
```

**Verify manually**:
```bash
curl http://localhost:9004/health
# {"status": "healthy", "mcp_tools": ["launch_academy_agent", "invoke_agent_action", "list_academy_agents", "shutdown_academy_agent"]}
```

---

### Step 9: Register Academy Capability (Host C Only)

**Purpose**: Register the gateway with the "Academy" capability tag so other hosts can discover it.

**On Host C**:

```bash
# Update peer capabilities to advertise Academy
agentic a2a update-peer <local-alias> --add-tags "Academy,federated-agents"
```

**Verify tools in Redis**:
```bash
docker exec redis redis-cli GET "external_tool:launch_academy_agent"
docker exec redis redis-cli GET "external_tool:invoke_agent_action"
docker exec redis redis-cli GET "external_tool:list_academy_agents"
docker exec redis redis-cli GET "external_tool:shutdown_academy_agent"
```

**Verify tools in Gateway API**:
```bash
ADMIN_TOKEN=$(curl -sf -X POST "http://localhost:8180/realms/master/protocol/openid-connect/token" \
  -d "grant_type=password&client_id=login-client&username=admin&password=admin" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -sf -H "Authorization: Bearer $ADMIN_TOKEN" "http://localhost:8083/v1/tools/list" \
  | python3 -c "import sys,json; [print(f\"  {t['name']} ({t.get('invocation',{}).get('protocol','?')})\") for t in json.load(sys.stdin) if 'academy' in t['name']]"
# Expected:
#   launch_academy_agent (mcp)
#   invoke_agent_action (mcp)
#   list_academy_agents (mcp)
#   shutdown_academy_agent (mcp)
```

---

### Step 10: Delegate Agent Orchestration (Host A → Host C)

**Purpose**: From the requesting host, use natural language to delegate Academy agent operations to the peer with Academy capability.

**On Host A** (via ADEPT agent):

```
User: "Launch an echo agent on the Academy server, send it 'Hello from Host A', then shut it down"

Agent: [calls launch_academy_agent with agent_type=echo]
Agent: [calls invoke_agent_action with action=echo, message='Hello from Host A']
Agent: [calls shutdown_academy_agent]
Agent: "Echo agent returned: 'Hello from Host A'. Agent shut down successfully."
```

**Direct E2E smoke test**:
```bash
cd examples/academy_mcp_server
make smoke-test
```

---

### Makefile Automation (Session 59)

The Academy MCP server lifecycle is automated via `examples/academy_mcp_server/Makefile`:

```bash
# From the academy_mcp_server directory
cd examples/academy_mcp_server

make setup              # Build + start + register 4 tools + verify
make rebuild            # No-cache rebuild + re-register tools
make teardown           # Deregister tools + stop container

make register-tools     # Register 4 tools via agentic CLI
make deregister-tools   # Remove 4 tools from ADEPT
make verify-tools       # Verify 4 tools in Redis
make health             # Check /health endpoint
make smoke-test         # E2E test via Response API
make logs               # Tail container logs

# Test suite (118/118 passing)
make validate-tests           # All tests (unit + integration)
make validate-unit            # Schemas + agent templates
make validate-integration     # Registry + lifecycle + endpoints
```

---

### Phase 3 Teardown

After the workshop, clean up the Academy resources:

**On Host C** (Academy host):
```bash
cd examples/academy_mcp_server

# Deregister tools and stop container
make teardown

# Or manually:
docker compose -f docker-compose.academy.yaml down
```

---

### Phase 3 Troubleshooting

**Academy server won't start**:
```bash
# Check container logs
docker logs academy_mcp_server --tail 20

# Verify adept_application_network exists
docker network ls | grep adept_application_network

# Rebuild from scratch
cd examples/academy_mcp_server && make rebuild
```

**Tools not registered**:
```bash
# Verify tools in Redis
make verify-tools

# Re-register if missing
make deregister-tools && make register-tools
```

**Agent launch fails (ExchangeClientNotFoundError)**:
This was fixed in Session 59 by explicitly binding the Academy Manager's exchange client to the Handle after launch. If you see this error, ensure you have the latest code:
```bash
cd examples/academy_mcp_server && make rebuild
```

---

### Phase 3 Key Implementation Details

**Session-Scoped Manager Registry**: The Academy MCP server uses `AcademyManagerRegistry` which creates one Academy `Manager` per `mcp_session_id`. Each Manager runs its own `LocalExchangeFactory` task group. Agents launched within a session share the Manager's exchange client.

**Exchange Client Binding Fix (Session 59)**: Academy's `Handle.exchange` property uses a `ContextVar` (`exchange_context`) that is only set inside the Manager's task-group context. MCP tool handlers run outside this context, so the Handle's exchange client is explicitly bound after launch:
```python
handle._exchange = session.manager.exchange_client
```

**Concurrency Safety**: Per-session `asyncio.Lock` prevents concurrent launches/shutdowns from corrupting session state.

### Phase 3 Related Documentation

- **Academy MCP Server README**: `examples/academy_mcp_server/README.md`
- **Academy Makefile**: `examples/academy_mcp_server/Makefile` — Build, register, test automation
- **Implementation Plan**: `docs/implementation-plans/ACADEMY_MCP_SERVER_IMPLEMENTATION_PLAN.md`

---

## Summary

### What You Learned

1. ✅ **A2A Architecture**: Independent ADEPT instances with zero shared state
2. ✅ **Service Token Generation**: Long-lived tokens for inter-gateway auth
3. ✅ **Peer Registration**: Bidirectional gateway discovery and metadata storage
4. ✅ **Connectivity Testing**: Validating A2A protocol end-to-end
5. ✅ **Troubleshooting**: Common issues and resolution strategies
6. ✅ **Task Delegation (Opentrons)**: Cross-host protocol execution via A2A (Phase 2)
7. ✅ **Task Delegation (Academy)**: Federated agent orchestration via A2A (Phase 3)
8. ✅ **Capability Discovery**: Dynamic service discovery via capability tags

### Next Steps

1. **Production Deployment**: Apply workshop steps to production instances
2. **Multi-Gateway Mesh**: Expand to 3+ gateways for distributed topology
3. **Additional Capabilities**: Register more capability types (e.g., HPC, Genomics)
4. **Custom Academy Agents**: Build domain-specific agents (Slurm, Globus) using Academy templates
5. **Monitoring**: Set up automated health checks and alerting

### Support

For issues or questions:
- Review troubleshooting section above
- Check related documentation
- Examine test suite: `tests/e2e/test_a2a_cli_commands.py`
- File issues: `https://github.com/anthropics/adept/issues`

---

**Workshop Version**: 1.1
**Last Updated**: 2026-02-16
**Maintainer**: ADEPT Framework Team
