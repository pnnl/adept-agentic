# Step-by-Step: Generate Let's Encrypt Certificate on a VM

**Last Updated**: 2026-02-09

---

## Prerequisites

### /etc/hosts Configuration (REQUIRED for CLI commands)

The demo-bootstrap CLI commands (`a2a-register`, `a2a-list`) require `api.agentic.local` to resolve to your local ADEPT instance.

**Single-VM Development/Testing**:
```bash
# Add to /etc/hosts
echo "127.0.0.1 api.agentic.local" | sudo tee -a /etc/hosts

# Verify DNS resolution
ping -c 1 api.agentic.local
# Should resolve to 127.0.0.1

# Verify nginx_proxy access (after ADEPT is running)
curl -k https://api.agentic.local/health
# Should return HTTP 200 OK
```

**Two-VM Production**:
```bash
# On each VM, add entries for BOTH VMs
sudo tee -a /etc/hosts <<EOF
127.0.0.1       api.agentic.local
192.168.1.100   vm1.api.agentic.local
192.168.1.101   vm2.api.agentic.local
EOF

# Or use generated hosts-entries.txt (after artifact generation)
sudo tee -a /etc/hosts < examples/demo-bootstrap/output/configs/hosts-entries.txt
echo "127.0.0.1 api.agentic.local" | sudo tee -a /etc/hosts
```

**Production with Real DNS** (no /etc/hosts needed):
```bash
# Set PUBLIC_HOSTNAME environment variable
export PUBLIC_HOSTNAME=vm1.prod.example.com

# Or add to .env file
echo "PUBLIC_HOSTNAME=vm1.prod.example.com" >> .env
```

**Why This is Needed**:
- CLI commands connect to `https://api.agentic.local/internal/registry`
- This URL must resolve to your ADEPT instance for nginx_proxy routing
- Without /etc/hosts, you'll get "connection refused" errors

**Troubleshooting**:
- **Connection refused**: Missing /etc/hosts entry or ADEPT not running
- **SSL certificate error**: Use `-k` flag with curl for self-signed certs
- **Name not resolved**: Check /etc/hosts syntax (no typos)

---

## TL;DR - Fastest Path (Copy & Paste)

**On the VM where ADEPT is installed**:

```bash
# 1. Install prerequisites
sudo apt update && sudo apt install -y certbot docker.io
sudo usermod -aG docker $USER && newgrp docker

# 2. Clone repo and build containers
cd ~
git clone <repo-url>
cd adept-extended-2025-11-07
docker build -t agentic-framework-deps-base:latest -f Dockerfile.base .
docker build -t demo-bootstrap:latest -f examples/demo-bootstrap/Dockerfile .

# 3. Generate certificate (REPLACE vm1.api.agentic.local with YOUR hostname)
sudo certbot certonly --manual --preferred-challenges dns \
  -d vm1.api.agentic.local \
  --email admin@example.com \
  --agree-tos
# PAUSE: Create DNS TXT record with the value certbot shows
# THEN: Press ENTER to continue

# 4. Export certificate to ADEPT format
docker run --rm \
  -v /etc/letsencrypt:/etc/letsencrypt:ro \
  -v $(pwd)/examples/demo-bootstrap/output:/output \
  demo-bootstrap:latest letsencrypt \
  --hostname vm1.api.agentic.local \
  --email admin@example.com

# 5. Apply to ADEPT (REPLACE /path/to/adept with your ADEPT location)
cd examples/demo-bootstrap/output
./scripts/apply-certificates.sh /path/to/adept
./configs/env-updates.sh /path/to/adept/.env
./scripts/restart-services.sh /path/to/adept

# 6. Verify
curl -I https://vm1.api.agentic.local/health
```

**Total Time**: ~15-20 minutes

---

## Option A: Generate Directly on the VM (Detailed Steps)

### Prerequisites

```bash
# 1. Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
# Log out and back in

# 2. Install certbot
sudo apt update
sudo apt install -y certbot
```

### Step 1: Clone Repository on VM

```bash
cd ~
git clone https://github.com/your-org/adept-extended-2025-11-07.git
cd adept-extended-2025-11-07
```

### Step 2: Build Base Image (First Time Only)

```bash
# This takes 5-10 minutes the first time
docker build -t agentic-framework-deps-base:latest -f Dockerfile.base .
```

### Step 3: Build Demo Bootstrap Container

```bash
# This takes ~2 minutes
docker build -t demo-bootstrap:latest -f examples/demo-bootstrap/Dockerfile .

# Verify build
docker images | grep demo-bootstrap
```

### Step 4: Generate Certificate with DNS-01 Challenge

**For internal/private networks** (recommended):

```bash
# REPLACE vm1.api.agentic.local with YOUR actual hostname
sudo certbot certonly --manual --preferred-challenges dns \
  -d vm1.api.agentic.local \
  --email admin@example.com \
  --agree-tos

# Certbot will output:
# "Please deploy a DNS TXT record under the name
#  _acme-challenge.vm1.api.agentic.local with the following value:
#
#  XYZ123ABC456..."

# PAUSE HERE - DO NOT PRESS ENTER YET
```

### Step 5: Create DNS TXT Record

**In your DNS provider console** (Route53, Cloudflare, etc.):

```
Record Type: TXT
Name: _acme-challenge.vm1.api.agentic.local
Value: XYZ123ABC456...  (the value certbot showed you)
TTL: 300 seconds
```

**Verify DNS propagation**:
```bash
# Wait 1-2 minutes, then verify
dig _acme-challenge.vm1.api.agentic.local TXT

# Should show your TXT record value
```

### Step 6: Complete Certificate Generation

**Go back to certbot terminal** and press ENTER.

```bash
# Certbot output:
# Successfully received certificate.
# Certificate is saved at: /etc/letsencrypt/live/vm1.api.agentic.local/fullchain.pem
# Key is saved at:         /etc/letsencrypt/live/vm1.api.agentic.local/privkey.pem
```

### Step 7: Export Certificate to ADEPT Format

```bash
# Run bootstrap container to export certificates
docker run --rm \
  -v /etc/letsencrypt:/etc/letsencrypt:ro \
  -v $(pwd)/examples/demo-bootstrap/output:/output \
  demo-bootstrap:latest letsencrypt \
  --hostname vm1.api.agentic.local \
  --email admin@example.com \
  --challenge dns

# Certificates exported to: examples/demo-bootstrap/output/certs/
```

### Step 8: Apply Certificates to ADEPT

```bash
cd examples/demo-bootstrap/output

# Copy certificates to ADEPT
./scripts/apply-certificates.sh /path/to/your/adept-installation

# Update ADEPT configuration
./configs/env-updates.sh /path/to/your/adept-installation/.env

# Restart services
./scripts/restart-services.sh /path/to/your/adept-installation
```

### Certificate Verification

After applying certificates, verify nginx_proxy can access them:

```bash
# Check nginx_proxy can read certificates
docker exec nginx_proxy ls -la /etc/nginx/certs/

# Expected output:
# -rw-r--r-- vm1.api.agentic.local.crt
# -rw------- vm1.api.agentic.local.key

# Verify nginx_proxy configuration
docker exec nginx_proxy nginx -t

# Expected: "nginx: configuration file /etc/nginx/nginx.conf test is successful"
```

**How Certificate Mounting Works**:
1. Certificates copied to `${ADEPT_ROOT}/data/nginx_certs/`
2. Docker volume `nginx_certs` binds to `data/nginx_certs/`
3. nginx_proxy mounts `nginx_certs:/etc/nginx/certs`
4. nginx config expects `/etc/nginx/certs/${PUBLIC_HOSTNAME}.crt` and `.key`

### Step 9: Verify HTTPS Works

```bash
curl -I https://vm1.api.agentic.local/health

# Expected: HTTP/2 200 OK
```

---

## Option B: HTTP-01 Challenge (Public VMs Only)

**Requirements**:
- VM has public IP address
- Port 80 accessible from internet
- Domain resolves to VM's public IP

### Generate Certificate

```bash
sudo certbot certonly --standalone --preferred-challenges http \
  -d vm1.api.agentic.local \
  --email admin@example.com \
  --agree-tos

# Certbot automatically validates via port 80
# Certificate generated immediately (no manual DNS steps)
```

Then proceed to Step 7-9 from Option A.

---

## Option C: Generate on Laptop, Transfer to VM

### On Your Laptop

```bash
# 1. Generate certificate locally (using DNS-01 challenge)
sudo certbot certonly --manual --preferred-challenges dns \
  -d vm1.api.agentic.local \
  --email admin@example.com \
  --agree-tos

# 2. Follow DNS TXT record steps (same as Option A, Step 5)

# 3. Export certificates using bootstrap container
cd ~/path/to/adept-extended-2025-11-07
docker build -t demo-bootstrap:latest -f examples/demo-bootstrap/Dockerfile .

docker run --rm \
  -v /etc/letsencrypt:/etc/letsencrypt:ro \
  -v $(pwd)/examples/demo-bootstrap/output:/output \
  demo-bootstrap:latest letsencrypt \
  --hostname vm1.api.agentic.local \
  --email admin@example.com \
  --challenge dns

# 4. Package artifacts
cd examples/demo-bootstrap
tar czf output.tar.gz output/
```

### Transfer to VM

```bash
# Copy to VM
scp output.tar.gz user@vm1.api.agentic.local:/tmp/

# SSH into VM
ssh user@vm1.api.agentic.local
cd /tmp
tar xzf output.tar.gz
cd output
```

### Apply on VM

```bash
# Apply certificates
./scripts/apply-certificates.sh /path/to/adept

# Update configuration
./configs/env-updates.sh /path/to/adept/.env

# Restart services
./scripts/restart-services.sh /path/to/adept

# Verify
curl -I https://vm1.api.agentic.local/health
```

---

## Certificate Renewal Setup

### Install Renewal Hook

```bash
# Install the generated renewal hook
sudo cp examples/demo-bootstrap/output/certs/renewal-hook.sh \
        /etc/letsencrypt/renewal-hooks/deploy/adept-reload.sh

sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/adept-reload.sh
```

### Setup Automated Renewal (Cron)

```bash
# Add cron job to run certbot renewal twice daily
(sudo crontab -l 2>/dev/null; echo "0 0,12 * * * certbot renew --quiet") | sudo crontab -

# Verify cron job
sudo crontab -l
```

### Test Renewal (Dry Run)

```bash
sudo certbot renew --dry-run

# Expected: "Congratulations, all simulated renewals succeeded"
```

---

## Troubleshooting

### "certbot: command not found"

```bash
sudo apt update
sudo apt install -y certbot
```

### "Docker permission denied"

```bash
sudo usermod -aG docker $USER
# Log out and back in
```

### "DNS TXT record not found"

```bash
# Verify DNS propagation
dig _acme-challenge.vm1.api.agentic.local TXT

# Wait 5-10 minutes for DNS propagation
# Some DNS providers are slow
```

### "Challenge validation failed"

**For DNS-01**:
- Verify TXT record value matches exactly (no quotes, no spaces)
- Use `dig` to confirm record is visible
- Wait longer for DNS propagation

**For HTTP-01**:
- Verify port 80 is open: `sudo netstat -tlnp | grep :80`
- Verify domain resolves to your VM: `dig vm1.api.agentic.local`
- Check firewall rules

### "Certificate already exists"

```bash
# If you already have a certificate, just export it
docker run --rm \
  -v /etc/letsencrypt:/etc/letsencrypt:ro \
  -v $(pwd)/examples/demo-bootstrap/output:/output \
  demo-bootstrap:latest letsencrypt \
  --hostname vm1.api.agentic.local \
  --email admin@example.com \
  --challenge dns

# Skip certbot generation, just exports existing cert
```

---

## Quick Reference

### Single-VM Certificate Setup (Fastest Path)

```bash
# On VM with ADEPT installed
cd /path/to/adept-extended-2025-11-07

# 1. Build containers (first time only)
docker build -t agentic-framework-deps-base:latest -f Dockerfile.base .
docker build -t demo-bootstrap:latest -f examples/demo-bootstrap/Dockerfile .

# 2. Generate certificate with certbot
sudo certbot certonly --manual --preferred-challenges dns \
  -d vm1.api.agentic.local \
  --email admin@example.com \
  --agree-tos
# (follow DNS TXT record steps)

# 3. Export to ADEPT format
docker run --rm \
  -v /etc/letsencrypt:/etc/letsencrypt:ro \
  -v $(pwd)/examples/demo-bootstrap/output:/output \
  demo-bootstrap:latest letsencrypt \
  --hostname vm1.api.agentic.local \
  --email admin@example.com

# 4. Apply to ADEPT
cd examples/demo-bootstrap/output
./scripts/apply-certificates.sh /path/to/adept
./configs/env-updates.sh /path/to/adept/.env
./scripts/restart-services.sh /path/to/adept

# 5. Verify
curl -I https://vm1.api.agentic.local/health
```

**Total Time**: ~15-20 minutes (5 min DNS propagation + 10 min building + 5 min applying)

---

## What Gets Generated

After running the bootstrap container, you'll have:

```
examples/demo-bootstrap/output/
├── certs/
│   ├── vm1.api.agentic.local.crt    # SSL certificate
│   ├── vm1.api.agentic.local.key    # Private key
│   └── renewal-hook.sh              # Auto-renewal script
├── configs/
│   └── env-updates.sh               # Update PUBLIC_HOSTNAME in .env
└── scripts/
    ├── apply-certificates.sh        # Copy certs to ADEPT
    └── restart-services.sh          # Restart ADEPT services
```

**Security**: All files in `output/` are gitignored except `.gitkeep` and `.gitignore`.

---

## Next Steps

After certificate setup:
1. **Two-VM Deployment**: See [QUICKSTART.md § Deploy on Two VMs](QUICKSTART.md#deploy-on-two-vms)
2. **A2A Gateway Registration**: Run `deploy` command with `--peer-hostname` to generate A2A artifacts
3. **Certificate Renewal**: Install renewal hook and cron job (see "Certificate Renewal Setup" above)

---

**Questions?** See [README.md](README.md) for complete documentation or [LETSENCRYPT_GUIDE.md](LETSENCRYPT_GUIDE.md) for Let's Encrypt deep dive.
