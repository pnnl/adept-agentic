# A2A Workshop - Quick Reference Guide

**Purpose**: One-page command reference for A2A gateway setup.

---

## Prerequisites

```bash
# Verify ADEPT is running
docker ps | grep -E "agent_gateway|orchestration_service|gateway_registry"

# Check network connectivity to peer
ping <peer_ip>

# Verify agentic CLI is installed
which agentic || pip install -e src/
```

---

## Workshop Commands (Azure VM Example)

### Azure VM (10.0.0.2) → Register AWS Peer (10.0.0.1)

```bash
cd examples/a2a-workshop/scripts

# Step 0: Verify environment
./00_verify_environment.sh

# Step 1: Generate A2A token
./01_generate_a2a_token.sh --name a2a-azure-to-aws --ttl-days 365
export LOCAL_A2A_TOKEN="sk-service-a2a-azure-to-aws-..."

# Step 2: Register AWS peer
./02_register_peer.sh \
  --peer-ip 10.0.0.1 \
  --peer-alias aws-gateway \
  --description "AWS EC2 Production Gateway" \
  --tags "aws,ec2,us-east-1"

# Step 3: Test connectivity
./03_test_connectivity.sh --peer-alias aws-gateway --verbose

# Optional: Full E2E test
./04_end_to_end_test.sh --peer-ip 10.0.0.1 --peer-alias aws-gateway
```

### AWS EC2 (10.0.0.1) → Register Azure Peer (10.0.0.2)

```bash
cd examples/a2a-workshop/scripts

# Step 0: Verify environment
./00_verify_environment.sh

# Step 1: Generate A2A token
./01_generate_a2a_token.sh --name a2a-aws-to-azure --ttl-days 365
export LOCAL_A2A_TOKEN="sk-service-a2a-aws-to-azure-..."

# Step 2: Register Azure peer
./02_register_peer.sh \
  --peer-ip 10.0.0.2 \
  --peer-alias azure-gateway \
  --description "Azure VM Development Gateway" \
  --tags "azure,vm,eastus"

# Step 3: Test connectivity
./03_test_connectivity.sh --peer-alias azure-gateway --verbose
```

---

## Phase 2: OpenTrons A2A Delegation

### On OpenTrons Host (Host B)

```bash
cd examples/a2a-workshop/scripts

# Step 5: Start OpenTrons MCP server
./05_start_opentrons_server.sh

# Verify health
curl http://localhost:9003/health
# {"status": "healthy", "hardware_mode": "simulation", "mcp_tools": ["execute_opentrons_protocol"]}

# Step 6: Register Opentrons capability + external MCP tool
./06_register_opentrons_capability.sh

# Verify tool registration (from Docker network)
TOKEN=$(curl -s -X POST http://keycloak:8180/realms/master/protocol/openid-connect/token \
  -d "grant_type=password&client_id=login-client&username=admin&password=admin" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
curl -s -H "Authorization: Bearer $TOKEN" http://agent_gateway:8081/v1/tools/list \
  | python3 -c "import sys,json; [print(f\"{t['name']} ({t.get('invocation',{}).get('protocol','?')})\") for t in json.load(sys.stdin)]"
# Should include: execute_opentrons_protocol (mcp)

# Alternative: Register via agentic CLI (from host machine)
agentic tools delete execute_opentrons_protocol -y --username admin --password admin
agentic tools register execute_opentrons_protocol \
  -d "Execute an OpenTrons liquid handling protocol..." \
  -p mcp -u http://opentrons_mcp_server:9003/mcp \
  --tool-name execute_opentrons_protocol_tool \
  --args-schema '{"protocol_json":{"type":"object","description":"Protocol spec"},"dry_run":{"type":"boolean","description":"Validate without executing","default":true}}' \
  --username admin --password admin
```

> **Note**: Script 06 uses two tokens — S2S (`gateway-client`) for registry capability,
> admin ROPC (`login-client`) for tool registration. Tool uses **MCP protocol** (not HTTP) —
> FastMCP Client handles the JSON-RPC handshake. URL must include `/mcp` path.
> See the workshop README for details.

### On Requesting Host (Host A)

```bash
cd examples/a2a-workshop/scripts

# Step 7: Delegate protocol (dry run)
./07_opentrons_a2a_delegation.sh --peer-alias azure-gateway

# Step 7: Delegate protocol (execute in simulation)
./07_opentrons_a2a_delegation.sh --peer-alias azure-gateway --execute

# Auto-discover peer with Opentrons capability
./07_opentrons_a2a_delegation.sh
```

### OpenTrons Lifecycle (Makefile)

```bash
# From project root — preferred approach
make opentrons-setup          # First-time: build + start + register + verify
make opentrons-rebuild        # Rebuild from scratch + re-register tool
make opentrons-teardown       # Stop container + deregister tool
make opentrons-health         # Check server health
make opentrons-smoke-test     # E2E test via Response API

# Or from examples/opentrons_mcp_server/
cd examples/opentrons_mcp_server
make setup                    # Full lifecycle
make rebuild                  # Rebuild + re-register
make teardown                 # Stop + deregister
make help                     # Show all targets
```

### OpenTrons Teardown (Manual)

```bash
# On Host B: Stop OpenTrons server (run from project root)
cd "$(git rev-parse --show-toplevel)"
docker compose -f examples/opentrons_mcp_server/docker-compose.opentrons.yaml down
```

---

## Phase 3: Academy Federated Agents

### On Academy Host (Host C)

```bash
cd examples/academy_mcp_server

# Step 8: Full lifecycle — build, start, register 4 tools, verify
make setup

# Verify health
curl http://localhost:9004/health
# {"status": "healthy", "mcp_tools": ["launch_academy_agent", "invoke_agent_action", ...]}

# Step 9: Register Academy capability
agentic a2a update-peer <local-alias> --add-tags "Academy,federated-agents"

# Verify 4 tools in Redis
make verify-tools
# Expected: 4/4 tools verified

# Run test suite (118/118 passing)
make validate-tests
```

### On Requesting Host (Host A)

```bash
# Step 10: Delegate agent operations (via natural language)
# "Launch a compute agent, calculate factorial of 12, then shut it down"
# Agent discovers Academy host via capability tag and delegates

# Or run E2E smoke test
cd examples/academy_mcp_server
make smoke-test
```

### Academy Lifecycle (Makefile)

```bash
# From examples/academy_mcp_server/
cd examples/academy_mcp_server
make setup              # First-time: build + start + register 4 tools + verify
make rebuild            # Rebuild from scratch + re-register tools
make teardown           # Stop container + deregister 4 tools
make health             # Check server health
make smoke-test         # E2E test via Response API

# Test suite
make validate-tests     # All tests (118/118)
make validate-unit      # Schema + agent template tests
make validate-integration  # Registry + lifecycle + endpoint tests
make help               # Show all targets
```

### Academy Teardown (Manual)

```bash
# On Host C: Stop Academy server
cd examples/academy_mcp_server
make teardown

# Or manually:
docker compose -f docker-compose.academy.yaml down
```

---

## Manual CLI Commands

### Using agentic CLI Directly

```bash
# List registered peers
agentic a2a list-peers --format table

# Register peer manually
agentic a2a register-peer aws-gateway https://10.0.0.1/v1 \
  --description "AWS Gateway" \
  --tags "aws,production"

# Update peer capabilities (merge tags, don't replace)
agentic a2a update-peer aws-gateway --add-tags "Opentrons,lab-automation"
agentic a2a update-peer aws-gateway --remove-tags "old-tag"
agentic a2a update-peer aws-gateway --description "New description"

# Test connection
agentic a2a test-connection aws-gateway --verbose

# Remove peer
agentic a2a remove-peer aws-gateway --yes
```

### Configuration Management

```bash
# Check CLI health and connectivity
agentic config doctor

# Show current config (verbose includes directory info + disk usage)
agentic config show --verbose

# Interactive setup wizard
agentic config init

# Authenticate with the gateway
agentic config auth                          # Interactive (Keycloak ROPC)
agentic config auth --token <your_token>     # Direct token

# Set individual values (type-validated)
agentic config set gateway_url https://api.agentic.local
agentic config set temperature 0.5

# Backup and restore
agentic config backup --output my_config.tar.gz
agentic config restore my_config.tar.gz

# Cleanup
agentic config clean --cache    # Remove cache files
agentic config clean --all      # Remove cache, temp, and logs

# Reset to defaults
agentic config reset
```

---

## Verification Commands

```bash
# Check registered peers in database
docker exec postgres psql -U admin -d postgres -c \
  "SELECT alias, public_url, capabilities, last_health_check
   FROM gateway_registry
   ORDER BY created_at DESC;"

# List service tokens
make list-service-tokens

# Test A2A token authentication
curl -k -H "Authorization: Bearer $LOCAL_A2A_TOKEN" \
  https://localhost/v1/models
# Expected: 200 OK with model list

# Test peer gateway accessibility
curl -k https://10.0.0.1/v1/models
# Expected: 401 Unauthorized (or 200 if no auth required)
```

---

## Troubleshooting Quick Fixes

### Connection Refused
```bash
# Check firewall rules
# AWS: Open port 443 from Azure IP (10.0.0.2)
# Azure: Open port 443 from AWS IP (10.0.0.1)

# Test connectivity manually
curl -k https://<peer_ip>/v1/models
```

### 401 Unauthorized During Registration
```bash
# Regenerate credentials
make fix-credentials

# Verify VALIDATION_RUNNER credentials
docker exec gateway_registry env | grep VALIDATION_RUNNER
```

### Peer Not Found
```bash
# List all registered peers
agentic a2a list-peers

# Re-register if missing
./02_register_peer.sh --peer-ip <ip> --peer-alias <alias>
```

### Services Not Running
```bash
# Check Docker containers
docker ps

# Start ADEPT if needed
make start

# Wait for services to be ready
sleep 60
```

---

## Environment Variables

```bash
# Required for scripts
export LOCAL_IP="10.0.0.2"           # Your instance's IP
export LOCAL_A2A_TOKEN="sk-service-..." # Your A2A service token

# Optional overrides
export REGISTRY_URL="http://localhost:8086"  # Gateway Registry URL
export AGENT_GATEWAY_URL="http://localhost:8083/v1"  # Agent Gateway URL
```

---

## Firewall Configuration

### AWS Security Group

```bash
# Add inbound rule for HTTPS from Azure
aws ec2 authorize-security-group-ingress \
  --group-id <sg-id> \
  --protocol tcp \
  --port 443 \
  --cidr 10.0.0.2/32 \
  --description "ADEPT A2A from Azure"
```

### Azure NSG

```bash
# Add inbound rule for HTTPS from AWS
az network nsg rule create \
  --resource-group <rg> \
  --nsg-name <nsg> \
  --name allow-adept-a2a-from-aws \
  --protocol tcp \
  --priority 1000 \
  --destination-port-range 443 \
  --source-address-prefix 10.0.0.1/32
```

---

## Success Criteria

### Phase 1
✅ **Environment Check**: All services running and healthy
✅ **Token Generation**: Service token created with 365-day TTL
✅ **Peer Registration**: Peer appears in `agentic a2a list-peers`
✅ **Connectivity Test**: Connection successful with <100ms latency
✅ **Authentication**: Service token validates on peer gateway

### Phase 2 (OpenTrons)
✅ **OpenTrons Server**: Container healthy on port 9003, MCP endpoint at `/mcp`
✅ **Capability Registered**: Gateway advertises "Opentrons" capability
✅ **External Tool Registered**: `execute_opentrons_protocol` with `protocol: mcp` in `/v1/tools/list` and Redis
✅ **Pydantic Schema**: MCP `tools/list` exposes full `ProtocolSchema` + `TransferSchema` JSON schema
✅ **MCP JSON-RPC**: FastMCP Client completes initialize → tools/call → result → cleanup handshake
✅ **A2A Delegation**: Protocol execution delegated to remote peer
✅ **Result Received**: Protocol validation/execution result returned via A2A
✅ **Makefile Automation**: `make opentrons-setup` completes full lifecycle (build + register + verify)

### Phase 3 (Academy)
✅ **Academy Server**: Container healthy on port 9004, MCP endpoint at `/mcp`
✅ **Capability Registered**: Gateway advertises "Academy" capability
✅ **4 Tools Registered**: `launch_academy_agent`, `invoke_agent_action`, `list_academy_agents`, `shutdown_academy_agent` in Redis
✅ **Agent Templates**: EchoAgent, CounterAgent, ComputeAgent operational
✅ **Session Isolation**: Per-session Manager with exchange client binding
✅ **Test Suite**: 118/118 tests passing (unit + integration)
✅ **Makefile Automation**: `make setup` completes full lifecycle (build + register 4 tools + verify)

---

## Common Workflows

### Add New Peer

```bash
./02_register_peer.sh --peer-ip <new_peer_ip> --peer-alias <alias>
./03_test_connectivity.sh --peer-alias <alias>
```

### Update Peer Capabilities

```bash
# Add tags (merge with existing)
agentic a2a update-peer <alias> --add-tags "Opentrons,lab-automation"

# Remove tags
agentic a2a update-peer <alias> --remove-tags "deprecated-tag"

# Update description only (tags preserved)
agentic a2a update-peer <alias> --description "Updated Gateway"
```

### Remove Peer

```bash
agentic a2a remove-peer <alias> --yes
```

### Rotate A2A Token

```bash
# Generate new token
./01_generate_a2a_token.sh --name a2a-<instance>-v2 --ttl-days 365

# Update peer configurations to use new token
# (Implementation depends on how tokens are stored)

# Revoke old token
make revoke-service-token TOKEN=sk-service-a2a-<instance>-v1-...
```

### Monitor Peer Health

```bash
# Automated health check (add to cron)
*/5 * * * * cd /path/to/examples/a2a-workshop/scripts && ./03_test_connectivity.sh --peer-alias aws-gateway --quiet >> /var/log/a2a-health.log 2>&1
```

---

## Related Documentation

- **Workshop README**: `../README.md` - Complete workshop guide
- **Multi-Host OpenTrons Guide**: `../../../docs/workshop/A2A_OPENTRONS_MULTI_HOST_GUIDE.md`
- **Examples README**: `../../README.md` - Integration examples
- **Systems Admin Onboarding**: `../../../docs/SYSTEMS_ADMINISTRATOR_ONBOARDING.md`
- **OpenTrons Makefile**: `../../opentrons_mcp_server/Makefile` - Build, register, and teardown automation
- **Academy Makefile**: `../../academy_mcp_server/Makefile` - Build, register 4 tools, test suite automation
- **Academy README**: `../../academy_mcp_server/README.md` - Academy MCP server documentation
- **CLAUDE.md**: `../../../CLAUDE.md` - Project instructions

---

**Last Updated**: February 16, 2026
**Workshop Version**: 1.4 (Academy Phase 3, Makefile automation, MCP protocol fixes, Pydantic schema validation, CLI registration)
