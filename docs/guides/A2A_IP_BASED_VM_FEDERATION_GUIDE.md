# A2A Federation Guide: IP-Based VMs with Self-Signed Certificates

**Purpose**: Step-by-step guide for federating two ADEPT instances across Azure and AWS VMs using only IP addresses with self-signed certificates.

**Target Audience**: System administrators setting up production or staging ADEPT federations across cloud providers.

**Prerequisites**:
- Two VMs (Azure + AWS) with ADEPT installed
- Public IP addresses (or VPN/private network connectivity)
- SSH access to both VMs
- Port 443 open in firewall rules

**Estimated Time**: 45-60 minutes

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Certificate Generation (Self-Signed)](#certificate-generation-self-signed)
3. [Credential Management Setup](#credential-management-setup)
4. [Mutual A2A Registration](#mutual-a2a-registration)
5. [Token and Secret Exchange](#token-and-secret-exchange)
6. [End-to-End Validation](#end-to-end-validation)
7. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

### Federation Topology

```
┌─────────────────────────────────────────────────┐
│  Azure VM (Instance A)                          │
│  Public IP: 20.115.123.45                       │
│  Cert: /etc/ssl/adept/20.115.123.45             │
│                                                  │
│  ┌─────────────┐      ┌──────────────────┐     │
│  │ nginx_proxy │──────│ agent_gateway    │     │
│  │   (443)     │      │   (8081)         │     │
│  └─────────────┘      └──────────────────┘     │
│         │                       │               │
│         │             ┌──────────────────┐     │
│         │             │ gateway_registry │     │
│         │             │   (8086)         │     │
│         │             └──────────────────┘     │
│         │                       │               │
│  ┌─────────────┐      ┌──────────────────┐     │
│  │  Keycloak   │      │   PostgreSQL     │     │
│  │   (8180)    │      │   (5432)         │     │
│  └─────────────┘      └──────────────────┘     │
└─────────────────────────────────────────────────┘
                    │
                    │  A2A Protocol (HTTPS)
                    │  Mutual TLS
                    │  Service Auth Tokens
                    │
┌─────────────────────────────────────────────────┐
│  AWS EC2 (Instance B)                           │
│  Public IP: 54.210.89.123                       │
│  Cert: /etc/ssl/adept/54.210.89.123             │
│                                                  │
│  ┌─────────────┐      ┌──────────────────┐     │
│  │ nginx_proxy │──────│ agent_gateway    │     │
│  │   (443)     │      │   (8081)         │     │
│  └─────────────┘      └──────────────────┘     │
│         │                       │               │
│         │             ┌──────────────────┐     │
│         │             │ gateway_registry │     │
│         │             │   (8086)         │     │
│         │             └──────────────────┘     │
│         │                       │               │
│  ┌─────────────┐      ┌──────────────────┐     │
│  │  Keycloak   │      │   PostgreSQL     │     │
│  │   (8180)    │      │   (5432)         │     │
│  └─────────────┘      └──────────────────┘     │
└─────────────────────────────────────────────────┘
```

### Key Components

**Per VM**:
- **nginx_proxy**: SSL/TLS termination, reverse proxy
- **agent_gateway**: A2A protocol handler (port 8081 internal)
- **gateway_registry**: Peer gateway discovery and management
- **Keycloak**: Identity provider (service-to-service auth)
- **PostgreSQL**: State persistence

**Between VMs**:
- **A2A Protocol**: HTTPS communication (port 443)
- **Service Tokens**: JWT tokens for authentication
- **Mutual Registration**: Each VM registers the other as a peer

---

## Certificate Generation (Self-Signed)

### Background: Why Self-Signed for IP Addresses?

Let's Encrypt (via certbot) **does not issue certificates for IP addresses**. RFC 8738 prohibits public CAs from issuing certs for:
- Private IP addresses (10.x.x.x, 172.16.x.x, 192.168.x.x)
- Public IP addresses without domain validation

**Solution**: Generate self-signed certificates using the same OpenSSL tooling that certbot uses.

### Step 1: Certificate Generation on VM A (Azure)

**SSH into Azure VM**:
```bash
ssh azureuser@20.115.123.45
cd /path/to/adept-extended-2025-11-07
```

**Generate self-signed certificate with IP address in SAN**:
```bash
# Set your public IP
export VM_IP="20.115.123.45"

# Create certificate directory
sudo mkdir -p /etc/ssl/adept/${VM_IP}
cd /etc/ssl/adept/${VM_IP}

# Generate private key (4096-bit RSA)
sudo openssl genrsa -out privkey.pem 4096

# Create OpenSSL config with IP in Subject Alternative Name
cat <<EOF | sudo tee openssl.cnf
[req]
default_bits = 4096
prompt = no
default_md = sha256
req_extensions = req_ext
distinguished_name = dn

[dn]
C=US
ST=California
L=San Francisco
O=ADEPT Framework
OU=Development
CN=${VM_IP}

[req_ext]
subjectAltName = @alt_names

[alt_names]
IP.1 = ${VM_IP}
EOF

# Generate certificate signing request (CSR)
sudo openssl req -new -key privkey.pem -out csr.pem -config openssl.cnf

# Self-sign the certificate (valid for 365 days)
sudo openssl x509 -req -days 365 -in csr.pem -signkey privkey.pem \
  -out fullchain.pem -extensions req_ext -extfile openssl.cnf

# Create chain file (for self-signed, fullchain = cert)
sudo cp fullchain.pem chain.pem

# Create combined cert+key for nginx (optional)
sudo cat fullchain.pem privkey.pem | sudo tee cert.pem > /dev/null

# Set permissions
sudo chmod 644 fullchain.pem chain.pem cert.pem
sudo chmod 600 privkey.pem

# Verify certificate
openssl x509 -in fullchain.pem -text -noout | grep -A1 "Subject Alternative Name"
# Expected: IP Address:20.115.123.45
```

**Update nginx_proxy configuration**:
```bash
cd /path/to/adept-extended-2025-11-07

# Update deployment/local/docker-compose/docker-compose.nginx-proxy.yaml
# Change SSL_CERT_DIR to use IP-based path
vim deployment/local/docker-compose/docker-compose.nginx-proxy.yaml
```

Find the `ssl_certificate` and `ssl_certificate_key` paths and update:
```yaml
# Before:
- ../../../certs/letsencrypt:/etc/letsencrypt:ro

# After (for IP-based cert):
- /etc/ssl/adept/${VM_IP}:/etc/letsencrypt/live/${VM_IP}:ro
```

Or update nginx config to point to new certificate location:
```bash
# Edit nginx config
vim deployment/local/docker-compose/nginx.conf
```

```nginx
# Update SSL certificate paths
ssl_certificate /etc/letsencrypt/live/20.115.123.45/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/20.115.123.45/privkey.pem;
```

**Restart nginx_proxy**:
```bash
make rebuild-nginx-proxy
# Or
docker-compose -f deployment/local/docker-compose/docker-compose.nginx-proxy.yaml restart
```

### Step 2: Certificate Generation on VM B (AWS)

**Repeat the same process on AWS VM**:
```bash
ssh ec2-user@54.210.89.123
cd /path/to/adept-extended-2025-11-07

export VM_IP="54.210.89.123"

# Follow same steps as VM A (certificate generation + nginx config)
# ... (same commands as above)
```

### Step 3: Trust Self-Signed Certificates (Both VMs)

**Option 1: Accept Self-Signed in Client Code (Development)**

Python httpx/requests allows disabling SSL verification:
```python
import httpx

client = httpx.Client(verify=False)  # Disable SSL verification
response = client.get("https://20.115.123.45/health")
```

**Already configured in A2A commands** (`a2a_commands.py` uses `verify=False`).

**Option 2: Add Certificates to System Trust Store (Production)**

On VM A, trust VM B's certificate:
```bash
# Copy VM B's certificate to VM A
scp ec2-user@54.210.89.123:/etc/ssl/adept/54.210.89.123/fullchain.pem \
  /tmp/vm-b-cert.pem

# Install in system trust store (Ubuntu/Debian)
sudo cp /tmp/vm-b-cert.pem /usr/local/share/ca-certificates/vm-b.crt
sudo update-ca-certificates

# Or for RHEL/CentOS
sudo cp /tmp/vm-b-cert.pem /etc/pki/ca-trust/source/anchors/vm-b.crt
sudo update-ca-trust
```

Repeat on VM B to trust VM A's certificate.

---

## Credential Management Setup

### Step 1: Install agentic CLI (Both VMs)

```bash
cd /path/to/adept-extended-2025-11-07

# Activate Python 3.11 environment
source .venv311/bin/activate

# Install agentic CLI
pip install -e src/

# Verify installation
agentic --help
agentic auth --help
```

### Step 2: Configure DNS Resolution for Docker Services

The Gateway Registry validates JWT token issuers. Tokens from `http://localhost:8180` have different issuer than `http://keycloak:8180`.

**Solution**: Add Docker service names to `/etc/hosts`:
```bash
echo "127.0.0.1 keycloak gateway_registry agent_gateway" | sudo tee -a /etc/hosts
```

### Step 3: Setup Credentials on VM A (Auto-Discovery)

```bash
# Auto-discover credentials from ADEPT installation
agentic auth cred-setup --auto-discover --profile default --force

# Expected output:
# ✅ Found credentials in ADEPT installation
#      Client ID:  validation-runner-client
#  Client Secret:  0fhVDS3BID...
#   Keycloak URL:  http://keycloak:8180
#          Realm:  master
#   Registry URL:  http://gateway_registry:8086
#
# ✅ Credentials saved to ~/.adept-agentic/credentials (profile: default)
```

**Verify credentials**:
```bash
agentic auth cred-test --profile default

# Expected:
# ✅ Service authentication successful!
```

**List profiles**:
```bash
agentic auth cred-list

# Expected:
# ┏━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┓
# ┃ Profile ┃ Keycloak URL          ┃ Client ID                ┃ Realm  ┃
# ┡━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━┩
# │ default │ http://keycloak:8180  │ validation-runner-client │ master │
# └─────────┴───────────────────────┴──────────────────────────┴────────┘
```

### Step 4: Setup Credentials on VM B (AWS)

Repeat the same process on VM B:
```bash
ssh ec2-user@54.210.89.123
cd /path/to/adept-extended-2025-11-07
source .venv311/bin/activate

# Add Docker service names to /etc/hosts
echo "127.0.0.1 keycloak gateway_registry agent_gateway" | sudo tee -a /etc/hosts

# Setup credentials
agentic auth cred-setup --auto-discover --profile default --force

# Verify
agentic auth cred-test --profile default
```

### Step 5: Create Environment-Specific Profiles (Optional)

You can create separate profiles for different environments:

**On VM A (Azure - Production)**:
```bash
agentic auth cred-setup \
  --profile azure-prod \
  --client-id validation-runner-client \
  --client-secret <AZURE_SECRET> \
  --keycloak-url http://keycloak:8180 \
  --registry-url http://gateway_registry:8086 \
  --force
```

**On VM B (AWS - Staging)**:
```bash
agentic auth cred-setup \
  --profile aws-staging \
  --client-id validation-runner-client \
  --client-secret <AWS_SECRET> \
  --keycloak-url http://keycloak:8180 \
  --registry-url http://gateway_registry:8086 \
  --force
```

---

## Mutual A2A Registration

### Overview: What is Mutual Registration?

Each ADEPT instance registers the other as a "peer gateway" in its local Gateway Registry. This creates bidirectional trust.

**Workflow**:
1. VM A registers VM B as "aws-gateway"
2. VM B registers VM A as "azure-gateway"
3. Both can now delegate tasks to each other

### Step 1: Register VM B on VM A (Azure → AWS)

**On VM A (Azure)**:
```bash
source .venv311/bin/activate

# Register AWS VM as a peer
agentic a2a register-peer \
  aws-gateway \
  https://54.210.89.123/v1 \
  --description "AWS EC2 Production Gateway" \
  --tags "production,aws,us-east-1" \
  --profile default

# Expected output:
# ✓ Peer gateway 'aws-gateway' registered successfully
# Base URL: https://54.210.89.123/v1
# Description: AWS EC2 Production Gateway
# Tags: production, aws, us-east-1
```

**Verify registration**:
```bash
agentic a2a list-peers --profile default

# Expected:
# ┏━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┓
# ┃ Alias       ┃ Public URL             ┃ Capabilities             ┃ Health Status ┃
# ┡━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━┩
# │ aws-gateway │ https://54.210.89.123… │ description:AWS EC2 P…, │ Unknown       │
# │             │                        │ tag:production, tag:aw…  │               │
# └─────────────┴────────────────────────┴──────────────────────────┴───────────────┘
```

### Step 2: Register VM A on VM B (AWS → Azure)

**On VM B (AWS)**:
```bash
source .venv311/bin/activate

# Register Azure VM as a peer
agentic a2a register-peer \
  azure-gateway \
  https://20.115.123.45/v1 \
  --description "Azure VM Production Gateway" \
  --tags "production,azure,eastus" \
  --profile default

# Expected output:
# ✓ Peer gateway 'azure-gateway' registered successfully
# Base URL: https://20.115.123.45/v1
# Description: Azure VM Production Gateway
# Tags: production, azure, eastus
```

**Verify registration**:
```bash
agentic a2a list-peers --profile default

# Expected:
# ┏━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┓
# ┃ Alias         ┃ Public URL             ┃ Capabilities             ┃ Health Status ┃
# ┡━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━┩
# │ azure-gateway │ https://20.115.123.4…  │ description:Azure VM …, │ Unknown       │
# │               │                        │ tag:production, tag:az…  │               │
# └───────────────┴────────────────────────┴──────────────────────────┴───────────────┘
```

### Step 3: Test Connectivity

**On VM A, test connection to VM B**:
```bash
agentic a2a test-connection aws-gateway --profile default --verbose

# Expected (if successful):
# Gateway Alias: aws-gateway
# Base URL: https://54.210.89.123/v1
# Description: AWS EC2 Production Gateway
#
# Testing connection to https://54.210.89.123/v1...
# ● Connection Status: healthy
# Latency: 45ms
```

**On VM B, test connection to VM A**:
```bash
agentic a2a test-connection azure-gateway --profile default --verbose

# Expected (if successful):
# Gateway Alias: azure-gateway
# Base URL: https://20.115.123.45/v1
# Description: Azure VM Production Gateway
#
# Testing connection to https://20.115.123.45/v1...
# ● Connection Status: healthy
# Latency: 52ms
```

---

## Token and Secret Exchange

### Background: What Needs to be Shared?

For A2A operations, each VM needs:
1. **Service Client Credentials**: For authenticating to its own Keycloak
2. **Peer Gateway URLs**: Public URLs of remote gateways
3. **Trust Relationship**: Mutual registration in Gateway Registry

**What is NOT shared**:
- User credentials (each VM has independent users)
- Database state (PostgreSQL is not shared)
- Session data (completely independent)

### Option 1: Manual Credential Exchange (Simple)

**On VM A, export credentials**:
```bash
agentic auth cred-export --profile default --format env

# Output:
export VALIDATION_RUNNER_CLIENT_ID='validation-runner-client'
export VALIDATION_RUNNER_CLIENT_SECRET='0fhVDS3BIDvOCHZXqGop47O6En7IoMQA'
export KEYCLOAK_URL='http://keycloak:8180'
export KEYCLOAK_REALM='master'
export GATEWAY_REGISTRY_URL='http://gateway_registry:8086'
```

**Securely share with VM B admin**:
- Encrypted email
- Shared password manager (1Password, LastPass)
- Secure messaging (Signal, Wire)
- Corporate secrets vault (HashiCorp Vault, AWS Secrets Manager)

**On VM B, import credentials**:
```bash
# Option A: Create profile manually
agentic auth cred-setup \
  --profile vm-a-remote \
  --client-id validation-runner-client \
  --client-secret 0fhVDS3BIDvOCHZXqGop47O6En7IoMQA \
  --keycloak-url http://keycloak:8180 \
  --registry-url http://gateway_registry:8086 \
  --force

# Option B: Set environment variables temporarily
export VALIDATION_RUNNER_CLIENT_ID='validation-runner-client'
export VALIDATION_RUNNER_CLIENT_SECRET='0fhVDS3BIDvOCHZXqGop47O6En7IoMQA'
# (CLI will fall back to env vars if profile not found)
```

### Option 2: Automated Secret Distribution (Production)

**Using HashiCorp Vault**:
```bash
# On VM A, store credentials in Vault
vault kv put secret/adept/vm-a/a2a-credentials \
  client_id=validation-runner-client \
  client_secret=0fhVDS3BIDvOCHZXqGop47O6En7IoMQA \
  keycloak_url=http://keycloak:8180 \
  realm=master \
  registry_url=http://gateway_registry:8086

# On VM B, retrieve and setup
vault kv get -format=json secret/adept/vm-a/a2a-credentials | \
  jq -r '.data.data' | \
  agentic auth cred-setup --profile vm-a-remote --force --from-json
```

**Using AWS Secrets Manager**:
```bash
# On VM A, store in AWS Secrets Manager
aws secretsmanager create-secret \
  --name adept/vm-a/a2a-credentials \
  --secret-string '{
    "client_id": "validation-runner-client",
    "client_secret": "0fhVDS3BIDvOCHZXqGop47O6En7IoMQA",
    "keycloak_url": "http://keycloak:8180",
    "realm": "master",
    "registry_url": "http://gateway_registry:8086"
  }'

# On VM B, retrieve and setup (with IAM role)
aws secretsmanager get-secret-value \
  --secret-id adept/vm-a/a2a-credentials \
  --query SecretString --output text | \
  agentic auth cred-setup --profile vm-a-remote --force --from-json
```

### Option 3: No Secret Exchange Needed (Recommended)

**Key Insight**: Each VM only needs its OWN credentials to authenticate to its OWN Keycloak. VMs do NOT need each other's credentials.

**What each VM needs**:
1. **Own service credentials**: For authenticating to local Keycloak
2. **Peer gateway URL**: To know where to send A2A requests

**Authentication flow**:
```
VM A wants to delegate task to VM B:

1. VM A uses its OWN credentials to get token from VM A's Keycloak
2. VM A sends A2A request to VM B's public URL (https://54.210.89.123/v1)
3. VM B receives request, validates VM A's token
4. VM B executes task, returns result

No credential sharing needed!
```

**This is already working** - the mutual registration in Step 1 & 2 is sufficient.

---

## End-to-End Validation

### Step 1: Verify A2A Protocol Flow

**On VM A (Azure), initiate A2A call to VM B**:
```bash
# Using curl to test A2A endpoint directly
curl -X POST https://54.210.89.123/a2a/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(agentic a2a generate-token --output token)" \
  -d '{
    "jsonrpc": "2.0",
    "method": "task.delegate",
    "params": {
      "task": "Analyze protein sequence MKLLVESCLLLSLLVMGCQDA",
      "context": {"source": "azure-vm"}
    },
    "id": 1
  }' -k

# Expected:
# {
#   "jsonrpc": "2.0",
#   "result": {
#     "status": "accepted",
#     "task_id": "task-uuid-here"
#   },
#   "id": 1
# }
```

### Step 2: Test via agentic CLI

The CLI doesn't have a built-in A2A task delegation command yet, but you can test the infrastructure:

```bash
# List peers (both should show up)
agentic a2a list-peers --profile default --format table

# Test connectivity to each peer
agentic a2a test-connection aws-gateway --profile default --verbose
agentic a2a test-connection azure-gateway --profile default --verbose
```

### Step 3: Full Workflow Test (Workshop Script)

```bash
cd examples/a2a-workshop/scripts

# Run end-to-end test from VM A
./04_end_to_end_test.sh --peer-ip 54.210.89.123 --peer-alias aws-gateway

# Run end-to-end test from VM B
./04_end_to_end_test.sh --peer-ip 20.115.123.45 --peer-alias azure-gateway
```

### Step 4: Verify in Logs

**Check Agent Gateway logs on VM B**:
```bash
docker logs agent_gateway --tail 100 | grep "A2A"

# Look for:
# [INFO] A2A request received from 20.115.123.45
# [INFO] Task delegation accepted: task-uuid-here
```

**Check Gateway Registry**:
```bash
curl http://localhost:8086/v1/gateways/ | jq

# Should show both gateways registered
```

---

## Troubleshooting

### Issue 1: SSL Certificate Verification Fails

**Symptom**:
```
SSL: CERTIFICATE_VERIFY_FAILED
```

**Cause**: Self-signed certificates not trusted by client.

**Solutions**:
1. **Development**: Use `verify=False` in httpx/requests (already done in CLI)
2. **Production**: Add certificates to system trust store (see Certificate Generation section)
3. **Verify SAN**: Ensure IP address is in Subject Alternative Name:
   ```bash
   openssl x509 -in /etc/ssl/adept/${VM_IP}/fullchain.pem -text -noout | grep -A1 "Subject Alternative Name"
   # Expected: IP Address:20.115.123.45
   ```

### Issue 2: 401 Unauthorized from Gateway Registry

**Symptom**:
```
HTTP Error: 401
{"detail":"Token validation error: Invalid issuer"}
```

**Cause**: Token issuer mismatch (localhost vs keycloak hostname).

**Solution**: Ensure `/etc/hosts` has Docker service names:
```bash
cat /etc/hosts | grep keycloak
# Expected: 127.0.0.1 keycloak gateway_registry

# If missing:
echo "127.0.0.1 keycloak gateway_registry agent_gateway" | sudo tee -a /etc/hosts
```

**Update credentials**:
```bash
agentic auth cred-setup \
  --profile default \
  --client-id validation-runner-client \
  --client-secret <SECRET> \
  --keycloak-url http://keycloak:8180 \
  --registry-url http://gateway_registry:8086 \
  --force
```

### Issue 3: Connection Refused to Peer Gateway

**Symptom**:
```
✗ Cannot connect to https://54.210.89.123/v1
Connection refused
```

**Causes**:
1. nginx_proxy not running: `docker ps | grep nginx_proxy`
2. Firewall blocking port 443: Check cloud provider security groups
3. Wrong IP address: Verify with `curl -I https://54.210.89.123/health`

**Solutions**:
```bash
# Restart nginx_proxy
make rebuild-nginx-proxy

# Check firewall (AWS)
aws ec2 describe-security-groups --group-ids sg-xxxxx | jq '.SecurityGroups[0].IpPermissions'

# Check firewall (Azure)
az network nsg rule list --resource-group <rg> --nsg-name <nsg> --output table
```

### Issue 4: Agent Gateway Not Accessible

**Symptom**:
```
502 Bad Gateway
```

**Cause**: agent_gateway container not running or unhealthy.

**Solution**:
```bash
# Check container status
docker ps | grep agent_gateway

# Check logs
docker logs agent_gateway --tail 50

# Restart
make rebuild-gateway
```

### Issue 5: Credentials File Permission Error

**Symptom**:
```
PermissionError: Credentials file has insecure permissions
```

**Cause**: Credentials file has world-readable permissions.

**Solution**:
```bash
chmod 600 ~/.adept-agentic/credentials
chmod 700 ~/.adept-agentic
```

### Issue 6: High Latency Between VMs

**Symptom**:
```
Latency: 2500ms
⚠ High latency detected (>1s)
```

**Causes**:
1. VMs in different regions (expected)
2. Network congestion
3. Slow DNS resolution

**Solutions**:
1. Accept higher latency for cross-region A2A
2. Use VPN or direct peering (AWS VPC Peering, Azure VNet Peering)
3. Set up regional hubs to reduce cross-region calls

---

## Summary

You now have:
- ✅ Self-signed certificates on both VMs
- ✅ Credential management setup on both VMs
- ✅ Mutual A2A registration (bidirectional)
- ✅ End-to-end validation

**Next Steps**:
1. Test task delegation between VMs
2. Set up monitoring and alerting
3. Configure production-grade secret management
4. Document your federation topology

**Credentials Security Checklist**:
- [x] Credentials stored in `~/.adept-agentic/` with chmod 600
- [x] Secrets not committed to git
- [x] Different credentials per environment (dev/staging/prod)
- [x] Service tokens rotated regularly
- [x] Audit logs enabled for A2A operations

**Production Hardening**:
- [ ] Replace self-signed certs with CA-signed certs (if domain available)
- [ ] Enable mutual TLS (mTLS) for A2A communication
- [ ] Set up secret rotation automation
- [ ] Configure network security groups to allow only specific IPs
- [ ] Enable audit logging for all A2A operations
- [ ] Set up monitoring dashboards for cross-VM latency

---

**Questions? Issues?**
- Check logs: `docker logs agent_gateway`, `docker logs gateway_registry`
- Review workshop: `examples/a2a-workshop/README.md`
- Test CLI: `agentic a2a --help`, `agentic auth --help`
