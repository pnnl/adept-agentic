# A2A Federation Quick-Start Checklist

**Purpose**: Fast setup checklist for federating two ADEPT VMs using IP addresses with modern credential management.

**Time**: 15-20 minutes (assumes ADEPT already installed on both VMs)

**VMs**:
- **VM-A** (Azure): `20.115.123.45`
- **VM-B** (AWS): `54.210.89.123`

**Key Features** (as of Session 53):
- ✅ **Modern Credential Management**: `agentic auth` CLI commands (no manual env vars)
- ✅ **Auto-Discovery**: Automatic credential detection from ADEPT installation
- ✅ **Multi-Profile Support**: Separate profiles for dev/staging/prod
- ✅ **JWT Issuer Validation**: Proper Docker service name resolution for 401 prevention

---

## Pre-Flight Checklist

- [ ] Both VMs have ADEPT installed and running (`docker ps | grep agent_gateway`)
- [ ] Port 443 open in firewall rules (both VMs)
- [ ] SSH access to both VMs
- [ ] Public IPs confirmed: `curl ifconfig.me`
- [ ] agentic CLI installed: `pip install -e src/` (from ADEPT project root)
- [ ] Python 3.11+ available: `python3 --version`
- [ ] jq installed for JSON parsing: `which jq || sudo apt install jq`

---

## Part 1: Self-Signed Certificates (Both VMs)

### On VM-A (Azure - 20.115.123.45)

```bash
# 1. Set variables
export VM_IP="20.115.123.45"
export CERT_DIR="/etc/ssl/adept"

# 2. Create cert directory
sudo mkdir -p $CERT_DIR

# 3. Create OpenSSL config
cat > /tmp/cert.conf <<EOF
[req]
default_bits = 2048
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
CN = $VM_IP

[v3_req]
subjectAltName = @alt_names

[alt_names]
IP.1 = $VM_IP
EOF

# 4. Generate certificate (365 days)
sudo openssl req -new -x509 -nodes \
  -keyout $CERT_DIR/$VM_IP.key \
  -out $CERT_DIR/$VM_IP.crt \
  -days 365 \
  -config /tmp/cert.conf \
  -extensions v3_req

# 5. Set permissions
sudo chmod 644 $CERT_DIR/$VM_IP.crt
sudo chmod 600 $CERT_DIR/$VM_IP.key

# 6. Verify certificate
openssl x509 -in $CERT_DIR/$VM_IP.crt -text -noout | grep -A1 "Subject Alternative Name"
# Should show: IP Address:20.115.123.45

# 7. Update nginx config
sudo sed -i "s|ssl_certificate .*|ssl_certificate $CERT_DIR/$VM_IP.crt;|" \
  /path/to/nginx/conf.d/adept.conf
sudo sed -i "s|ssl_certificate_key .*|ssl_certificate_key $CERT_DIR/$VM_IP.key;|" \
  /path/to/nginx/conf.d/adept.conf

# 8. Restart nginx
docker restart nginx_proxy

# 9. Test HTTPS
curl -k https://$VM_IP/health
```

**Checkpoint**: ✅ Should return `{"status": "healthy"}`

---

### On VM-B (AWS - 54.210.89.123)

```bash
# 1. Set variables
export VM_IP="54.210.89.123"
export CERT_DIR="/etc/ssl/adept"

# 2-9. Repeat steps 2-9 from VM-A (same commands)
```

**Checkpoint**: ✅ Both VMs respond to `curl -k https://<IP>/health`

---

## Part 2: Credential Management (Both VMs)

**Purpose**: Configure service-to-service authentication credentials for A2A operations using the agentic CLI.

**Background**: ADEPT CLI supports automatic credential management with multi-profile support. This eliminates manual environment variable setup and enables secure credential storage in `~/.adept-agentic/credentials/`.

### On VM-A (Azure)

#### Step 2.1: Install agentic CLI (if not already installed)

```bash
# From ADEPT project root
cd /path/to/adept-extended-2025-11-07

# Activate Python environment (or create one)
source .venv311/bin/activate  # Or: python3 -m venv .venv && source .venv/bin/activate

# Install agentic CLI in editable mode
pip install -e src/
```

#### Step 2.2: Setup Docker Service Name Resolution

**CRITICAL**: Gateway Registry validates JWT token issuers. Tokens from `http://localhost:8180` have different issuer than `http://keycloak:8180`, causing **401 errors**.

```bash
# Add Docker service names to /etc/hosts (required for CLI on host)
echo "127.0.0.1 keycloak gateway_registry agent_gateway" | sudo tee -a /etc/hosts

# Verify DNS resolution
ping -c 1 keycloak
ping -c 1 gateway_registry
```

**Why This Matters**:
- Keycloak issues JWT tokens with issuer claim `http://keycloak:8180/realms/master`
- Gateway Registry validates issuer claim must match exactly
- Using `localhost:8180` creates token with different issuer → 401 Unauthorized

#### Step 2.3: Auto-Discover Credentials from ADEPT Installation

**Option 1: Auto-Discovery (Recommended)**

```bash
# Auto-discover credentials from ADEPT installation
agentic auth cred-setup --auto-discover --profile default --force

# Expected output:
# ✅ Found credentials in ADEPT installation
#      Client ID:  validation-runner-client
#  Client Secret:  0fhVDS3BID...
#   Keycloak URL:  http://keycloak:8180  # Note: Docker service name, not localhost
#          Realm:  master
#   Registry URL:  http://gateway_registry:8086
#
# ✅ Credentials saved to ~/.adept-agentic/credentials (profile: default)
```

**Option 2: Manual Setup (if auto-discovery fails)**

```bash
# Get credentials from Docker container
VALIDATION_CLIENT_ID=$(docker exec gateway_registry env | grep VALIDATION_RUNNER_CLIENT_ID | cut -d'=' -f2)
VALIDATION_CLIENT_SECRET=$(docker exec gateway_registry env | grep VALIDATION_RUNNER_CLIENT_SECRET | cut -d'=' -f2)

# Setup credentials manually with Docker service names
agentic auth cred-setup \
  --profile default \
  --client-id "$VALIDATION_CLIENT_ID" \
  --client-secret "$VALIDATION_CLIENT_SECRET" \
  --keycloak-url http://keycloak:8180 \
  --registry-url http://gateway_registry:8086 \
  --realm agentic-framework \
  --force
```

#### Step 2.4: Verify Credentials

```bash
# Test authentication (validates token generation from Keycloak)
agentic auth cred-test --profile default

# Expected output:
# ✅ Service authentication successful!
#    Token: eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...
#    Expires in: 300 seconds (5 minutes)
#    Groups: ['gateway-service']

# Show credential details (without exposing secret)
agentic auth cred-show --profile default

# List all configured profiles
agentic auth cred-list
```

**Checkpoint**: ✅ `cred-test` shows "Service authentication successful"

---

### On VM-B (AWS)

#### Step 2.1-2.4: Repeat All Steps from VM-A

```bash
# 1. Install agentic CLI
pip install -e src/

# 2. Setup Docker service name resolution
echo "127.0.0.1 keycloak gateway_registry agent_gateway" | sudo tee -a /etc/hosts

# 3. Auto-discover credentials
agentic auth cred-setup --auto-discover --profile default --force

# 4. Test credentials
agentic auth cred-test --profile default
```

**Checkpoint**: ✅ Both VMs have working credentials stored in `~/.adept-agentic/credentials/`

---

### Benefits of New Credential Management

- ✅ **No manual env vars**: Credentials stored securely in `~/.adept-agentic/credentials/`
- ✅ **Multi-profile support**: Separate profiles for dev/staging/prod environments
- ✅ **Auto-discovery**: Detects credentials from ADEPT installation automatically
- ✅ **Secure storage**: File permissions automatically set to 600 (owner read/write only)
- ✅ **Easy export**: Export credentials as env vars or JSON for backup/sharing
- ✅ **Profile-scoped operations**: All `a2a` commands use `--profile` flag
- ✅ **Token caching**: JWT tokens cached and auto-refreshed (5-minute TTL)

---

## Part 3: Mutual A2A Registration

### On VM-A (Azure) - Register AWS as Peer

```bash
# Register AWS VM as peer
agentic a2a register-peer aws-prod \
  --url https://54.210.89.123/v1 \
  --description "AWS EC2 Production Gateway" \
  --tags "aws,us-east-1,production" \
  --profile default

# Verify registration
agentic a2a list-peers --profile default --format table
```

**Checkpoint**: ✅ `list-peers` shows `aws-prod` with status "active"

---

### On VM-B (AWS) - Register Azure as Peer

```bash
# Register Azure VM as peer
agentic a2a register-peer azure-prod \
  --url https://20.115.123.45/v1 \
  --description "Azure VM Production Gateway" \
  --tags "azure,eastus,production" \
  --profile default

# Verify registration
agentic a2a list-peers --profile default --format table
```

**Checkpoint**: ✅ `list-peers` shows `azure-prod` with status "active"

---

## Part 4: Connectivity Testing

### From VM-A (Azure) → VM-B (AWS)

```bash
# Test connectivity
agentic a2a test-connection aws-prod --verbose --profile default
```

**Expected Output**:
```
✅ Connection successful!
   Response time: ~50-100ms
   Gateway status: healthy
```

---

### From VM-B (AWS) → VM-A (Azure)

```bash
# Test connectivity
agentic a2a test-connection azure-prod --verbose --profile default
```

**Expected Output**:
```
✅ Connection successful!
   Response time: ~50-100ms
   Gateway status: healthy
```

---

## Part 5: Final Validation

### On VM-A (Azure)

```bash
# Show all registered peers
agentic a2a list-peers --profile default --format json

# Export credentials for backup
agentic auth cred-export --profile default --format env > ~/adept-creds.env
```

---

### On VM-B (AWS)

```bash
# Show all registered peers
agentic a2a list-peers --profile default --format json

# Export credentials for backup
agentic auth cred-export --profile default --format env > ~/adept-creds.env
```

---

## Completion Checklist

### Infrastructure Setup
- [ ] VM-A has self-signed cert for its IP (Subject Alternative Name)
- [ ] VM-B has self-signed cert for its IP (Subject Alternative Name)
- [ ] VM-A has agentic CLI installed (`which agentic`)
- [ ] VM-B has agentic CLI installed (`which agentic`)
- [ ] VM-A has Docker service names in /etc/hosts
- [ ] VM-B has Docker service names in /etc/hosts

### Credential Management
- [ ] VM-A credentials setup complete (`agentic auth cred-setup`)
- [ ] VM-B credentials setup complete (`agentic auth cred-setup`)
- [ ] VM-A credentials tested successfully (`agentic auth cred-test`)
- [ ] VM-B credentials tested successfully (`agentic auth cred-test`)
- [ ] VM-A credentials use `http://keycloak:8180` (not `localhost`)
- [ ] VM-B credentials use `http://keycloak:8180` (not `localhost`)
- [ ] VM-A credential profile backed up (`cred-export`)
- [ ] VM-B credential profile backed up (`cred-export`)

### A2A Registration
- [ ] VM-A registered VM-B as peer (`aws-prod`)
- [ ] VM-B registered VM-A as peer (`azure-prod`)
- [ ] VM-A can list peers successfully (`agentic a2a list-peers`)
- [ ] VM-B can list peers successfully (`agentic a2a list-peers`)

### Connectivity Validation
- [ ] VM-A can connect to VM-B (`test-connection` passes)
- [ ] VM-B can connect to VM-A (`test-connection` passes)
- [ ] Both VMs show 2+ peers in `list-peers` output
- [ ] Response time < 200ms for both connections

**Status**: ✅ Federation complete!

---

## Quick Troubleshooting

### Issue: `curl -k https://<IP>/health` fails

```bash
# Check nginx is running
docker ps | grep nginx_proxy

# Check nginx config
docker exec nginx_proxy nginx -t

# Check certificate paths
ls -la /etc/ssl/adept/

# Restart nginx
docker restart nginx_proxy
```

---

### Issue: `cred-test` fails with "Cannot connect to Keycloak"

**Symptom**:
```
❌ Failed to authenticate with Keycloak
   Error: Connection refused or timeout
```

**Common Causes**:
1. Keycloak service not running
2. Docker service name not resolvable from host
3. Incorrect Keycloak URL in credentials

**Fix**:
```bash
# 1. Check Keycloak is running
docker ps | grep keycloak

# 2. Add Docker service names to /etc/hosts (REQUIRED for host CLI usage)
echo "127.0.0.1 keycloak gateway_registry agent_gateway" | sudo tee -a /etc/hosts

# 3. Verify DNS resolution
ping -c 1 keycloak  # Should resolve to 127.0.0.1

# 4. Re-setup credentials with Docker service names
agentic auth cred-setup --auto-discover --profile default --force

# 5. Test again
agentic auth cred-test --profile default
```

**Important**: Always use Docker service names (`http://keycloak:8180`, not `http://localhost:8180`) for CLI credential configuration to avoid JWT issuer mismatch errors.

---

### Issue: `test-connection` fails with SSL error

```bash
# Verify certificate has IP in SAN
openssl x509 -in /etc/ssl/adept/<IP>.crt -text -noout | grep -A1 "Subject Alternative Name"

# Test with curl (should work with -k flag)
curl -k -I https://<PEER_IP>/health

# Check nginx logs
docker logs nginx_proxy --tail 50
```

---

### Issue: `register-peer` fails with 401 Unauthorized

**Symptom**:
```
❌ Failed to register peer
   Error: 401 Unauthorized - Invalid credentials
```

**Common Causes**:
1. JWT issuer mismatch (`localhost:8180` vs `keycloak:8180`)
2. Expired or invalid client credentials
3. Gateway Registry not accessible

**Fix**:
```bash
# 1. Verify credentials are valid and generate fresh token
agentic auth cred-test --profile default

# Expected: ✅ Service authentication successful

# 2. Show credential details (check Keycloak URL uses Docker service name)
agentic auth cred-show --profile default

# Expected:
#   Keycloak URL: http://keycloak:8180  # NOT localhost:8180
#   Registry URL: http://gateway_registry:8086

# 3. If Keycloak URL shows localhost, fix with Docker service names
echo "127.0.0.1 keycloak gateway_registry agent_gateway" | sudo tee -a /etc/hosts
agentic auth cred-setup --auto-discover --profile default --force
agentic auth cred-test --profile default

# 4. Verify Gateway Registry is accessible
curl -I http://localhost:8086/health
# Expected: HTTP/1.1 200 OK

# 5. Regenerate service credentials if needed (from project root)
make fix-credentials
make restart
```

**JWT Issuer Mismatch Debug**:
```bash
# Get current token to check issuer claim
TOKEN=$(agentic auth cred-show --profile default --format json | jq -r '.access_token')

# Decode JWT payload (base64)
echo "$TOKEN" | cut -d'.' -f2 | base64 -d | jq '.iss'

# Expected: "http://keycloak:8180/realms/master"
# If shows "http://localhost:8180/...", credentials need to be re-created with Docker service names
```

---

## Important Notes

### ⚠️ No Credential Exchange Needed

**Common Misconception**: "Do I need to copy credentials from VM-A to VM-B?"

**Answer**: ❌ **NO!** Each VM uses its own credentials to authenticate to its own Keycloak instance.

**How Credential Management Works**:

```
VM-A (Azure)                              VM-B (AWS)
├─ ~/.adept-agentic/credentials/         ├─ ~/.adept-agentic/credentials/
│  └─ default.json                       │  └─ default.json
│     ├─ client_id: validation-runner    │     ├─ client_id: validation-runner
│     ├─ client_secret: ABC123...        │     ├─ client_secret: XYZ789...  (DIFFERENT!)
│     ├─ keycloak_url: http://keycloak:8180  │     ├─ keycloak_url: http://keycloak:8180
│     └─ registry_url: http://...        │     └─ registry_url: http://...
│                                        │
├─ Keycloak (VM-A's instance)            ├─ Keycloak (VM-B's instance)
├─ Gateway Registry (VM-A's instance)    ├─ Gateway Registry (VM-B's instance)
└─ PostgreSQL (VM-A's data)              └─ PostgreSQL (VM-B's data)
```

**What's Shared Between VMs**:
- ✅ Public IP addresses (for peer URLs)
- ✅ Gateway URLs (e.g., `https://20.115.123.45/v1`)

**What's NOT Shared Between VMs**:
- ❌ Client IDs/secrets (each VM has unique credentials)
- ❌ Keycloak instances (separate databases)
- ❌ JWT tokens (issued by different Keycloak instances)
- ❌ Gateway Registry data (separate peer lists)
- ❌ PostgreSQL data (complete data isolation)

**Why This Matters**:
- Each ADEPT instance is **completely autonomous**
- A2A protocol is the **ONLY** interaction mechanism
- Credentials are **local-only** (never transmitted to peer VMs)
- Zero shared state (compliance, security, resilience)

### ⚠️ Critical: Docker Service Name Resolution

**Most Common A2A Setup Issue**: JWT issuer mismatch causing 401 Unauthorized errors.

**The Problem**:
```bash
# ❌ WRONG: Using localhost in credentials
Keycloak URL: http://localhost:8180

# JWT token issued with:
{
  "iss": "http://localhost:8180/realms/agentic-framework",
  ...
}

# Gateway Registry expects issuer:
"http://keycloak:8180/realms/master"

# Result: 401 Unauthorized (issuer mismatch)
```

**The Solution**:
```bash
# ✅ CORRECT: Add Docker service names to /etc/hosts FIRST
echo "127.0.0.1 keycloak gateway_registry agent_gateway" | sudo tee -a /etc/hosts

# Then setup credentials with Docker service names
agentic auth cred-setup --auto-discover --profile default --force

# JWT token now issued with correct issuer:
{
  "iss": "http://keycloak:8180/realms/master",  # Matches expected!
  ...
}
```

**Why This Happens**:
- agentic CLI runs on **host** (not inside containers)
- Must resolve Docker service names to localhost (127.0.0.1)
- Gateway Registry validates JWT issuer claim strictly
- Issuer must match between token and expected value

**Validation**:
```bash
# Check /etc/hosts has Docker service names
grep keycloak /etc/hosts
# Expected: 127.0.0.1 keycloak gateway_registry agent_gateway

# Verify credentials use correct URLs
agentic auth cred-show --profile default | grep keycloak
# Expected: http://keycloak:8180 (NOT localhost)
```

---

### 🔒 Security Considerations (Production)

**For Production Deployments**:
1. **Replace self-signed certs** with CA-issued certificates when using domain names
2. **Use strong passwords** for Keycloak admin accounts
3. **Enable firewall rules** to restrict port 443 to known IPs
4. **Rotate credentials** regularly:
   ```bash
   # Regenerate service credentials
   make fix-credentials

   # Update CLI profile
   agentic auth cred-setup --auto-discover --profile default --force

   # Test new credentials
   agentic auth cred-test --profile default
   ```
5. **Monitor logs** for unauthorized access attempts
6. **Backup credential profiles** regularly:
   ```bash
   agentic auth cred-export --profile default --format env > ~/adept-creds-backup.env
   ```

**Development/Testing**:
- Self-signed certs are fine (use `-k` or `verify=False`)
- Default passwords acceptable
- Open firewall rules acceptable
- Credential backup recommended but not critical

---

### 📂 Credential Storage & Management

**Credential File Location**:

Credentials are stored in `~/.adept-agentic/credentials/<profile>.json`:

```bash
# View credential file location
ls -la ~/.adept-agentic/credentials/

# Example output:
# drwx------ 2 user user 4096 Feb 11 05:00 .
# -rw------- 1 user user  512 Feb 11 05:00 default.json
# -rw------- 1 user user  498 Feb 11 04:30 staging.json
# -rw------- 1 user user  523 Feb 11 04:15 production.json
```

**File Permissions**: Automatically set to `600` (owner read/write only) for security.

**Profile Structure** (`~/.adept-agentic/credentials/default.json`):
```json
{
  "client_id": "validation-runner-client",
  "client_secret": "0fhVDS3BID...",
  "keycloak_url": "http://keycloak:8180",
  "realm": "agentic-framework",
  "registry_url": "http://gateway_registry:8086"
}
```

**Multi-Profile Workflow**:

```bash
# Setup different profiles for different environments
agentic auth cred-setup --auto-discover --profile dev --force
agentic auth cred-setup --auto-discover --profile staging --force
agentic auth cred-setup --auto-discover --profile prod --force

# Use specific profile for operations
agentic a2a list-peers --profile prod --format table
agentic a2a register-peer azure-staging \
  --url https://10.20.30.40/v1 \
  --profile staging

# Switch profiles for different environments
export ADEPT_PROFILE=prod  # Default profile for all commands
agentic a2a list-peers  # Uses 'prod' profile automatically
```

**Credential Backup & Restore**:

```bash
# Export credentials for backup
agentic auth cred-export --profile default --format env > ~/adept-creds-backup.env
agentic auth cred-export --profile default --format json > ~/adept-creds-backup.json

# Restore credentials from backup (on new VM or after profile deletion)
# Method 1: Manual re-setup using exported values
agentic auth cred-setup \
  --profile default \
  --client-id $(grep CLIENT_ID ~/adept-creds-backup.env | cut -d'=' -f2) \
  --client-secret $(grep CLIENT_SECRET ~/adept-creds-backup.env | cut -d'=' -f2) \
  --keycloak-url $(grep KEYCLOAK_URL ~/adept-creds-backup.env | cut -d'=' -f2) \
  --registry-url $(grep REGISTRY_URL ~/adept-creds-backup.env | cut -d'=' -f2) \
  --force

# Method 2: Auto-discover (simpler, recommended if ADEPT still running)
agentic auth cred-setup --auto-discover --profile default --force
```

---

## Quick Reference Commands

### Credential Management (agentic auth)

```bash
# Auto-discover credentials from ADEPT installation (recommended)
agentic auth cred-setup --auto-discover --profile <name> --force

# Manual credential setup
agentic auth cred-setup \
  --profile <name> \
  --client-id validation-runner-client \
  --client-secret <SECRET> \
  --keycloak-url http://keycloak:8180 \
  --registry-url http://gateway_registry:8086 \
  --realm agentic-framework \
  --force

# Test authentication (validates token generation)
agentic auth cred-test --profile <name>

# Show credential details (without exposing secret)
agentic auth cred-show --profile <name>

# List all configured profiles
agentic auth cred-list

# Export credentials for backup/sharing
agentic auth cred-export --profile <name> --format env > creds.env
agentic auth cred-export --profile <name> --format json > creds.json

# Delete credential profile
agentic auth cred-delete --profile <name>
```

### A2A Operations (agentic a2a)

```bash
# List registered peers
agentic a2a list-peers --profile <name> --format table
agentic a2a list-peers --profile <name> --format json

# Register peer gateway
agentic a2a register-peer <alias> \
  --url https://<peer-ip>/v1 \
  --description "Description of peer gateway" \
  --tags "tag1,tag2,tag3" \
  --profile <name>

# Test connection to peer
agentic a2a test-connection <alias> --profile <name> --verbose

# Remove peer
agentic a2a remove-peer <alias> --yes --profile <name>
```

### System Health

```bash
# Test gateway HTTPS
curl -k https://<IP>/health

# Check services are running
docker ps | grep -E "agent_gateway|orchestration_service|gateway_registry|keycloak"

# View service logs
docker logs agent_gateway --tail 50
docker logs gateway_registry --tail 50
docker logs orchestration_service --tail 50

# Check credential files on host
ls -la ~/.adept-agentic/credentials/

# Check Docker service name resolution
ping -c 1 keycloak
ping -c 1 gateway_registry
```

---

## Next Steps

Once federation is working:

1. **Test A2A Protocol**: Send actual agent-to-agent tasks between VMs
   ```bash
   # Use Workshop E2E test
   cd examples/a2a-workshop/scripts
   ./04_end_to_end_test.sh --peer-ip <peer-ip> --peer-alias <alias>
   ```

2. **Setup Multi-Profile Credentials**: Configure separate profiles for different environments
   ```bash
   agentic auth cred-setup --auto-discover --profile dev --force
   agentic auth cred-setup --auto-discover --profile staging --force
   agentic auth cred-setup --auto-discover --profile prod --force
   ```

3. **Add More Peers**: Register additional gateways as needed
   ```bash
   agentic a2a register-peer <alias> \
     --url https://<peer-ip>/v1 \
     --description "Description" \
     --tags "tag1,tag2" \
     --profile default
   ```

4. **Monitor Performance**: Track latency and throughput
   ```bash
   # Monitor A2A connectivity health
   watch -n 30 'agentic a2a test-connection aws-prod --profile default'

   # View registry logs
   docker logs gateway_registry --tail 50 -f
   ```

5. **Setup Credential Rotation**: Schedule regular credential updates
   ```bash
   # Add to cron (monthly credential rotation)
   0 0 1 * * cd /path/to/adept && make fix-credentials && \
     agentic auth cred-setup --auto-discover --profile default --force && \
     agentic auth cred-test --profile default
   ```

6. **Backup Credentials**: Export and store securely
   ```bash
   agentic auth cred-export --profile default --format json > ~/adept-creds-$(date +%Y%m%d).json
   chmod 600 ~/adept-creds-*.json
   ```

7. **Document Infrastructure**: Keep IP address inventory for network planning
   ```bash
   # Create A2A topology document
   echo "# ADEPT A2A Mesh Topology" > ~/adept-a2a-topology.md
   echo "" >> ~/adept-a2a-topology.md
   agentic a2a list-peers --profile default --format json >> ~/adept-a2a-topology.md
   ```

---

## Related Documentation

### Quick References
- 📚 **Full A2A Guide**: `docs/guides/A2A_IP_BASED_VM_FEDERATION_GUIDE.md` (833 lines) - Comprehensive federation guide with detailed architecture
- 📚 **A2A Workshop**: `examples/a2a-workshop/README.md` (600+ lines) - Hands-on workshop with IP-agnostic scripts
- 📚 **Workshop Quick Reference**: `examples/a2a-workshop/docs/QUICK_REFERENCE.md` - One-page command reference

### Architecture Documentation
- 📚 **A2A Architecture**: `examples/a2a-workshop/docs/ARCHITECTURE.md` (700+ lines) - Service tokens, mesh communication, gateway registry
- 📚 **Workshop Presentation**: `docs/workshop/ADEPT_WORKSHOP_PRESENTATION_OUTLINE.md` - Slide 9: Federated A2A Communication
- 📚 **CLAUDE.md**: A2A credential management section

### Related Workshop Slides
- **Slide 9**: Federated A2A Communication Flow (sequence diagram)
- **Slide 15A**: Network Isolation Deep-Dive (three-tier architecture)
- **Slide 19A**: Secrets Management Architecture (credential storage patterns)

---

## Updates & Version History

**Session 53 (2026-02-11)**: Major credential management update
- ✅ Migrated from manual env vars to `agentic auth` CLI commands
- ✅ Added Docker service name resolution requirement (`/etc/hosts` setup)
- ✅ Added JWT issuer mismatch troubleshooting
- ✅ Added multi-profile workflow examples
- ✅ Added credential backup/restore instructions
- ✅ Aligned with Workshop README Step 0.5 credential setup
- ✅ Expanded completion checklist (8 → 18 items)

**Previous Version**: Manual environment variable configuration (deprecated)

---

**Estimated Time**: 15-20 minutes ⏱️
**Difficulty**: Intermediate 🔧
**Last Updated**: 2026-02-11 (Session 53)
**Support**: File issues at GitHub repository
