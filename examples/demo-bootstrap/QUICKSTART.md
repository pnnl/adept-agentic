# Demo Bootstrap Container - Quick Start Guide

**Last Updated**: 2026-02-09

---

## How It Works

The bootstrap container is a **Python-based CLI orchestrator** that generates deployment artifacts:

**Architecture**:
- **Main CLI**: `bootstrap_main.py` (Click-based, 4 commands: `deploy`, `letsencrypt`, `a2a-register`, `a2a-list`)
- **Python Modules**: 3 modules (`artifact_generator`, `letsencrypt_manager`, `a2a_registrar`)
- **Generated Artifacts**: Shell scripts, configs, certificates (OUTPUT, not input)

**What the container does**:
1. You run: `docker run demo-bootstrap deploy --hostname vm1...`
2. Python modules generate artifacts (scripts, configs, certs)
3. You review artifacts in `/output/` directory
4. You manually apply artifacts to VMs

**What the container does NOT do**:
- ❌ Execute scripts on VMs directly
- ❌ Call shell scripts from `scripts/` directory
- ❌ Require SSH or privileged access to VMs

**Key Insight**: Shell scripts are **generated OUTPUT artifacts**, not dependencies. bootstrap_main.py calls Python modules directly, not shell scripts.

See [README.md § Architecture](README.md#architecture) for detailed architecture documentation.

---

## Run Tests

### Prerequisites Checklist

- [ ] **Docker is running**: `docker ps` (should show running containers or empty list)
- [ ] **Base image built**: `docker images | grep agentic-framework-deps-base`
- [ ] **For integration tests**: `docker build -t demo-bootstrap:latest -f examples/demo-bootstrap/Dockerfile .`

### Build Base Image (First Time Only)

```bash
cd /path/to/adept-extended-2025-11-07

# Build base image (~5-10 minutes first time)
docker build -t agentic-framework-deps-base:latest -f Dockerfile.base .

# Verify
docker images agentic-framework-deps-base:latest
```

### Run Tests

```bash
# All tests (unit + integration)
make validate-demo-bootstrap-all

# Unit tests only (faster, no container build needed)
make validate-demo-bootstrap-unit-all

# Integration tests (requires demo-bootstrap container built)
make validate-demo-bootstrap-integration
```

**Expected Result**: `78/78 tests passed` in ~50 seconds

---

## Generate Deployment Artifacts

### Prerequisites Checklist

- [ ] **Docker is running**: `docker ps`
- [ ] **Base image built**: `docker images | grep agentic-framework-deps-base`
- [ ] **ADEPT services running** (ONLY for A2A registration): `make start`

### Let's Encrypt Account

**Do I need to create a Let's Encrypt account?**

**NO!** Certbot creates an account automatically the first time you run it. Just provide `--email` and you're set.

**What you need**:
- Email address for expiration notifications (e.g., `admin@example.com`)
- Agreement to Let's Encrypt Terms of Service (`--agree-tos` flag)

**That's it!** No website registration, no manual account setup.

**For detailed step-by-step certificate generation on a VM, see [CERTIFICATE_SETUP_GUIDE.md](CERTIFICATE_SETUP_GUIDE.md)**

### Build Demo Bootstrap Container

```bash
cd /path/to/adept-extended-2025-11-07

# Build bootstrap container (~2 minutes)
docker build -t demo-bootstrap:latest -f examples/demo-bootstrap/Dockerfile .

# Verify
docker images demo-bootstrap:latest
```

### Generate Artifacts for VM1

**IMPORTANT**: Replace placeholder values with YOUR actual hostnames and IPs!

**Git-Safe**: The `output/` directory has a `.gitignore` that prevents generated artifacts (certificates, keys, scripts) from being committed to version control. You can safely generate artifacts without polluting `git status`.

```bash
# Output directory already exists with .gitkeep
# No need to create it manually

# Generate VM1 deployment artifacts
# REPLACE these values with YOUR actual hostnames/IPs:
#   --hostname: YOUR VM1's FQDN (e.g., vm1.api.agentic.local)
#   --peer-hostname: YOUR VM2's FQDN (e.g., vm2.api.agentic.local)
#   --vm1-ip: YOUR VM1's IP address (e.g., 192.168.1.100)
#   --vm2-ip: YOUR VM2's IP address (e.g., 192.168.1.101)
#   --email: YOUR email for Let's Encrypt notifications

docker compose -f examples/demo-bootstrap/docker-compose.bootstrap.yaml \
  --profile bootstrap run --rm demo_bootstrap deploy \
  --hostname vm1.api.agentic.local \
  --peer-hostname vm2.api.agentic.local \
  --vm1-ip 192.168.1.100 \
  --vm2-ip 192.168.1.101 \
  --email admin@example.com \
  --challenge dns
```

**What This Does**:
- Creates shell scripts with `HOSTNAME="vm1.api.agentic.local"` variable
- Scripts use `${HOSTNAME}` to reference files (e.g., `${HOSTNAME}.crt`)
- Generated artifacts are **templates** you apply on the actual VMs

**Expected Result**: Artifacts in `examples/demo-bootstrap/output/`

### Review Generated Artifacts

**Security Note**: All generated artifacts in `output/` are automatically gitignored (via `output/.gitignore`). Your certificates, private keys, and scripts will never be committed to version control.

```bash
# List all artifacts
ls -R examples/demo-bootstrap/output/

# Read deployment guide
cat examples/demo-bootstrap/output/DEPLOYMENT_GUIDE.md

# Verify scripts are executable
ls -l examples/demo-bootstrap/output/scripts/*.sh
ls -l examples/demo-bootstrap/output/configs/*.sh

# Verify git ignores artifacts (should show only .gitkeep and .gitignore)
git status examples/demo-bootstrap/output/
```

---

## Use the Container Interactively

### Prerequisites Checklist

- [ ] **ADEPT services running**: `make start`
- [ ] **Credentials synced**: `make sync-credentials`
- [ ] **Bootstrap container built**: `docker images demo-bootstrap:latest`

### Enter Interactive Shell

```bash
# Enter container
docker compose -f examples/demo-bootstrap/docker-compose.bootstrap.yaml \
  --profile bootstrap run --rm demo_bootstrap bash

# Inside container, agentic CLI is available:
agentic --help                        # Show available commands
agentic config doctor                 # Health check: SDK, config, gateway, storage
agentic config show --verbose         # Show config + directory info + disk usage
agentic a2a list-peers --format table
agentic files list

# Generate artifacts manually
python /app/examples/demo-bootstrap/bootstrap_main.py deploy \
  --hostname test.example.com \
  --peer-hostname peer.example.com \
  --vm1-ip 10.0.1.100 \
  --vm2-ip 10.0.1.101 \
  --email admin@example.com
```

---

## Deploy on Two VMs

### Complete Workflow

#### **Phase 1: Generate Artifacts (on laptop/workstation)**

```bash
# 1. Build containers
docker build -t agentic-framework-deps-base:latest -f Dockerfile.base .
docker build -t demo-bootstrap:latest -f examples/demo-bootstrap/Dockerfile .

# 2. Generate VM1 artifacts
mkdir -p examples/demo-bootstrap/output-vm1
docker compose -f examples/demo-bootstrap/docker-compose.bootstrap.yaml \
  --profile bootstrap run --rm demo_bootstrap deploy \
  --hostname vm1.api.agentic.local \
  --peer-hostname vm2.api.agentic.local \
  --vm1-ip 192.168.1.100 \
  --vm2-ip 192.168.1.101 \
  --email admin@example.com \
  --challenge dns

# Move to vm1 directory
mv examples/demo-bootstrap/output examples/demo-bootstrap/output-vm1

# 3. Generate VM2 artifacts
docker compose -f examples/demo-bootstrap/docker-compose.bootstrap.yaml \
  --profile bootstrap run --rm demo_bootstrap deploy \
  --hostname vm2.api.agentic.local \
  --peer-hostname vm1.api.agentic.local \
  --vm1-ip 192.168.1.100 \
  --vm2-ip 192.168.1.101 \
  --email admin@example.com \
  --challenge dns

# Move to vm2 directory
mv examples/demo-bootstrap/output examples/demo-bootstrap/output-vm2

# 4. Review artifacts
cat examples/demo-bootstrap/output-vm1/DEPLOYMENT_GUIDE.md
```

#### **Phase 2: Transfer Artifacts to VMs**

```bash
# Transfer to VM1
scp -r examples/demo-bootstrap/output-vm1/ user@vm1:/tmp/adept-artifacts

# Transfer to VM2
scp -r examples/demo-bootstrap/output-vm2/ user@vm2:/tmp/adept-artifacts
```

#### **Phase 3: Apply on VM1**

```bash
# SSH into VM1
ssh user@vm1

cd /tmp/adept-artifacts

# 1. Update /etc/hosts
sudo tee -a /etc/hosts < configs/hosts-entries.txt

# 2. Apply certificates
./scripts/apply-certificates.sh /path/to/adept

# 3. Update ADEPT configuration
./configs/env-updates.sh /path/to/adept/.env

# 4. Restart services
./scripts/restart-services.sh /path/to/adept

# 5. Register peer gateway
# NOTE: Uses nginx_proxy routing (/internal/registry), not direct port 8086
cd /path/to/adept
source deployment/local/docker-compose/.env-keycloak-credentials-dir/.env-keycloak-credentials
/tmp/adept-artifacts/a2a/register-vm2-gateway.sh

# Verify registration via nginx_proxy
TOKEN=$(curl -s -X POST "http://localhost:8180/realms/master/protocol/openid-connect/token" \
  -d "grant_type=client_credentials" \
  -d "client_id=$VALIDATION_RUNNER_CLIENT_ID" \
  -d "client_secret=$VALIDATION_RUNNER_CLIENT_SECRET" | jq -r '.access_token')

curl -H "Authorization: Bearer $TOKEN" \
  https://vm1.api.agentic.local/internal/registry/gateways/
```

#### **Phase 4: Apply on VM2** (repeat Phase 3)

#### **Phase 5: Verify**

```bash
# Test health endpoints
curl -I https://vm1.api.agentic.local/health
curl -I https://vm2.api.agentic.local/health

# Test A2A connectivity
agentic a2a list-peers
agentic a2a test-connection vm2-gateway
```

---

## Troubleshooting

### "docker: command not found"

**Solution**: Install Docker
```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
# Log out and back in
```

### "agentic-framework-deps-base:latest not found"

**Solution**: Build base image
```bash
docker build -t agentic-framework-deps-base:latest -f Dockerfile.base .
```

### "demo-bootstrap:latest not found"

**Solution**: Build bootstrap container
```bash
docker build -t demo-bootstrap:latest -f examples/demo-bootstrap/Dockerfile .
```

### Tests fail with "Permission denied"

**Solution**: Check Docker permissions
```bash
# Add user to docker group
sudo usermod -aG docker $USER

# Or run with sudo (not recommended)
sudo make validate-demo-bootstrap-all
```

### "ADEPT services not running"

**Solution**: Only needed for A2A registration features
```bash
# Start ADEPT
cd /path/to/adept-extended-2025-11-07
make start

# Verify services
docker ps | grep -E "agent_gateway|orchestration_service|gateway_registry"
```

### "Credentials not found"

**Solution**: Only needed for A2A registration features
```bash
# Regenerate credentials
make fix-credentials
make sync-credentials

# Verify
ls -la deployment/local/docker-compose/.env-keycloak-credentials-dir/
```

---

## Quick Reference

### Docker Commands

```bash
# Check Docker is running
docker ps

# List images
docker images

# Build base image
docker build -t agentic-framework-deps-base:latest -f Dockerfile.base .

# Build bootstrap container
docker build -t demo-bootstrap:latest -f examples/demo-bootstrap/Dockerfile .

# Remove all containers and images (nuclear option)
docker system prune -a
```

### Test Commands

```bash
# All tests
make validate-demo-bootstrap-all

# Unit tests only
make validate-demo-bootstrap-unit-all

# Integration tests only
make validate-demo-bootstrap-integration

# Specific module
make validate-demo-bootstrap-unit-artifact-generator
make validate-demo-bootstrap-unit-letsencrypt
make validate-demo-bootstrap-unit-a2a
```

### Artifact Generation Commands

```bash
# Full deployment (VM1)
docker compose -f examples/demo-bootstrap/docker-compose.bootstrap.yaml \
  --profile bootstrap run --rm demo_bootstrap deploy \
  --hostname vm1.api.agentic.local \
  --peer-hostname vm2.api.agentic.local \
  --vm1-ip 192.168.1.100 \
  --vm2-ip 192.168.1.101 \
  --email admin@example.com

# Certificate only
docker compose -f examples/demo-bootstrap/docker-compose.bootstrap.yaml \
  --profile bootstrap run --rm demo_bootstrap letsencrypt \
  --hostname vm1.api.agentic.local \
  --email admin@example.com

# A2A registration only
docker compose -f examples/demo-bootstrap/docker-compose.bootstrap.yaml \
  --profile bootstrap run --rm demo_bootstrap a2a-register \
  --alias vm2-gateway \
  --url https://vm2.api.agentic.local
```

---

## Time Estimates

| Task | Duration | Prerequisites |
|------|----------|---------------|
| Build base image (first time) | ~5-10 min | Docker |
| Build bootstrap container | ~2 min | Base image |
| Run unit tests | ~30 sec | Base image |
| Run integration tests | ~20 sec | Bootstrap container |
| Generate artifacts | ~5 sec | Bootstrap container |
| Apply artifacts on VM | ~5 min | SSH access to VM |

---

## Support

- **Full Documentation**: `README.md`
- **Test Documentation**: `TESTING.md`
- **Implementation Report**: `docs/implementation-reports/SESSION_52_DEMO_BOOTSTRAP_IMPLEMENTATION_COMPLETE.md`
- **Issues**: https://github.com/anthropics/adept/issues

---

**Last Updated**: 2026-02-09
**Status**: Production-Ready
