# Let's Encrypt & Certbot - Complete Guide

**Last Updated**: 2026-02-09
**Audience**: Users deploying ADEPT with SSL certificates

---

## Prerequisites for Let's Encrypt

### Do You Need a Let's Encrypt Account?

**NO - Account Creation is Automatic!** ✅

**Common Misconception**: "I need to register on letsencrypt.org first"

**Reality**:
- Let's Encrypt has **no account registration website**
- Certbot automatically creates an account **the first time you run it**
- The `--email` parameter is all you need
- Account is created and managed locally by certbot

**What Happens First Run**:
```bash
sudo certbot certonly --standalone -d vm1.api.agentic.local --email admin@example.com --agree-tos

# Output:
# Saving debug log to /var/log/letsencrypt/letsencrypt.log
# Account registered.  ← Created automatically!
# Requesting a certificate for vm1.api.agentic.local
# Successfully received certificate.
```

**Account Storage**: `/etc/letsencrypt/accounts/`

**Key Points**:
- ✅ No manual account creation needed
- ✅ No website registration required
- ✅ Email is only for expiration notifications
- ✅ Account is tied to your email + server
- ✅ Same account reused for future certificates

### /etc/hosts Configuration (REQUIRED for CLI commands)

**CRITICAL**: After generating certificates, demo-bootstrap CLI commands require `api.agentic.local` to resolve to your ADEPT instance.

**Single-VM Development/Testing**:
```bash
# Add to /etc/hosts
echo "127.0.0.1 api.agentic.local" | sudo tee -a /etc/hosts

# Verify
ping -c 1 api.agentic.local
curl -k https://api.agentic.local/health  # After ADEPT is running
```

**Two-VM Production**:
```bash
# On each VM, add local alias + peer hostname
sudo tee -a /etc/hosts <<EOF
127.0.0.1       api.agentic.local
192.168.1.100   vm1.api.agentic.local
192.168.1.101   vm2.api.agentic.local
EOF
```

**Production with Real DNS**:
```bash
# Set PUBLIC_HOSTNAME instead of /etc/hosts
export PUBLIC_HOSTNAME=vm1.prod.example.com
```

**Why Needed**: CLI commands (`a2a-register`, `a2a-list`) connect to `https://api.agentic.local/internal/registry`. Without /etc/hosts, you'll get connection refused errors.

**See Also**: [HOSTNAME_USAGE.md](HOSTNAME_USAGE.md) for detailed hostname configuration

### System Requirements

**Operating System**:
- ✅ Ubuntu 20.04+ / Debian 11+
- ✅ RHEL 8+ / CentOS 8+
- ✅ Amazon Linux 2023
- ✅ macOS with Homebrew

**Network Requirements**:
- **For HTTP-01 challenge**: Port 80 accessible from internet
- **For DNS-01 challenge**: Access to DNS provider (manual or API)

**Disk Space**: ~50MB for certbot + certificates

### Installing Certbot

#### Ubuntu/Debian

```bash
# Update package list
sudo apt update

# Install certbot
sudo apt install -y certbot

# Verify installation
certbot --version
# Expected: certbot 1.21.0 or higher
```

#### RHEL/CentOS

```bash
# Install EPEL repository
sudo yum install -y epel-release

# Install certbot
sudo yum install -y certbot

# Verify
certbot --version
```

#### Amazon Linux 2023

```bash
# Certbot available in AL2023 repos
sudo yum install -y certbot

# Verify
certbot --version
```

#### macOS

```bash
# Install via Homebrew
brew install certbot

# Verify
certbot --version
```

### DNS Provider Access (For DNS-01 Challenge)

**Required If**:
- Your VMs are on internal/private network
- Port 80 is not publicly accessible
- You want wildcard certificates

**What You Need**:
- Access to your DNS provider (AWS Route53, Cloudflare, etc.)
- Ability to create TXT records for domain verification

**Supported Providers**:
- Manual (any DNS provider via web UI)
- AWS Route53 (via certbot-dns-route53 plugin)
- Cloudflare (via certbot-dns-cloudflare plugin)
- Google Cloud DNS (via certbot-dns-google plugin)
- 50+ other providers

### Public Internet Access (For HTTP-01 Challenge)

**Required If**:
- Using HTTP-01 challenge type
- Let's Encrypt needs to verify domain ownership

**Firewall Rules**:
```bash
# Allow port 80 from Let's Encrypt servers
# Let's Encrypt IPs: https://letsencrypt.org/docs/acme-ip-ranges/
sudo ufw allow 80/tcp comment 'Let\'s Encrypt HTTP-01'
```

---

## Utility Scripts

The bootstrap container provides **3 utility scripts** for Let's Encrypt operations:

### 1. setup-letsencrypt.sh ✅

**Purpose**: Wrapper for certificate generation

**Location**: `examples/demo-bootstrap/scripts/setup-letsencrypt.sh`

**Usage**:
```bash
# Inside bootstrap container
/app/examples/demo-bootstrap/scripts/setup-letsencrypt.sh \
  vm1.api.agentic.local \
  admin@example.com \
  dns

# Or via Docker
docker compose -f examples/demo-bootstrap/docker-compose.bootstrap.yaml \
  --profile bootstrap run --rm demo_bootstrap \
  bash /app/examples/demo-bootstrap/scripts/setup-letsencrypt.sh \
    vm1.api.agentic.local \
    admin@example.com \
    http
```

**Parameters**:
1. `hostname` - FQDN for certificate (e.g., `vm1.api.agentic.local`)
2. `email` - Let's Encrypt notification email (default: `admin@example.com`)
3. `challenge` - Challenge type: `dns` or `http` (default: `dns`)

### 2. Bootstrap CLI: letsencrypt Command ✅

**Purpose**: Generate and export certificates

**Usage**:
```bash
# Via Docker Compose
docker compose -f examples/demo-bootstrap/docker-compose.bootstrap.yaml \
  --profile bootstrap run --rm demo_bootstrap letsencrypt \
  --hostname vm1.api.agentic.local \
  --email admin@example.com \
  --challenge dns \
  --output-dir /output

# Certificates exported to: examples/demo-bootstrap/output/certs/
```

**What It Does**:
1. Runs certbot to generate certificate
2. Copies certificate to `/output/certs/`
3. Generates renewal hook script
4. Sets proper file permissions (644 for .crt, 600 for .key)

### 3. Generated Renewal Hook ✅

**Purpose**: Automatically update ADEPT certificates on renewal

**Location**: Generated in `output/certs/renewal-hook.sh`

**Installation** (after generating artifacts):
```bash
# Copy to Let's Encrypt renewal hooks directory
sudo cp /tmp/adept-artifacts/certs/renewal-hook.sh \
        /etc/letsencrypt/renewal-hooks/deploy/adept-reload.sh

# Make executable
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/adept-reload.sh

# Test (dry-run)
sudo certbot renew --dry-run
```

**What It Does**:
- Runs automatically after successful certificate renewal
- Copies new certificates to ADEPT directory
- Reloads nginx to pick up new certificates
- Logs operations for debugging

---

## Challenge Types Explained

### DNS-01 Challenge (Recommended)

**Best For**:
- Internal/private networks
- Port 80 not publicly accessible
- Wildcard certificates (*.example.com)

**How It Works**:
1. You request certificate for `vm1.api.agentic.local`
2. Let's Encrypt gives you a TXT record value
3. You create TXT record: `_acme-challenge.vm1.api.agentic.local`
4. Let's Encrypt verifies TXT record via DNS query
5. Certificate issued

**Manual Process**:
```bash
# Run certbot
sudo certbot certonly --manual --preferred-challenges dns \
  -d vm1.api.agentic.local \
  --email admin@example.com \
  --agree-tos

# Certbot will prompt:
# "Please deploy a DNS TXT record under the name
# _acme-challenge.vm1.api.agentic.local with the following value:
# XYZ123ABC..."

# 1. Log into your DNS provider
# 2. Create TXT record:
#    Name:  _acme-challenge.vm1.api.agentic.local
#    Type:  TXT
#    Value: XYZ123ABC...
# 3. Wait 1-5 minutes for DNS propagation
# 4. Press Enter in certbot

# Certificates saved to: /etc/letsencrypt/live/vm1.api.agentic.local/
```

**Automated Process** (with DNS plugin):
```bash
# Install Route53 plugin
sudo apt install -y python3-certbot-dns-route53

# Configure AWS credentials
export AWS_ACCESS_KEY_ID=your_key
export AWS_SECRET_ACCESS_KEY=your_secret

# Run certbot (fully automated)
sudo certbot certonly --dns-route53 \
  -d vm1.api.agentic.local \
  --email admin@example.com \
  --agree-tos

# No manual steps required!
```

### HTTP-01 Challenge

**Best For**:
- Public-facing servers
- Simple setup with no DNS access needed
- Quick validation

**How It Works**:
1. You request certificate for `vm1.api.agentic.local`
2. Let's Encrypt gives you a validation file
3. Certbot serves file at `http://vm1.api.agentic.local/.well-known/acme-challenge/`
4. Let's Encrypt fetches file via HTTP
5. Certificate issued

**Process**:
```bash
# Run certbot (fully automated)
sudo certbot certonly --standalone \
  -d vm1.api.agentic.local \
  --email admin@example.com \
  --agree-tos

# Certbot automatically:
# 1. Starts temporary web server on port 80
# 2. Serves validation file
# 3. Waits for Let's Encrypt verification
# 4. Issues certificate

# Certificates saved to: /etc/letsencrypt/live/vm1.api.agentic.local/
```

**Requirements**:
- Port 80 must be free (no web server running)
- OR use `--nginx` flag if nginx is running
- Firewall must allow inbound port 80 from internet

---

## Certificate Locations

### Let's Encrypt Directory Structure

```
/etc/letsencrypt/
├── live/
│   └── vm1.api.agentic.local/
│       ├── fullchain.pem -> ../../archive/.../fullchain1.pem
│       ├── privkey.pem -> ../../archive/.../privkey1.pem
│       ├── cert.pem -> ../../archive/.../cert1.pem
│       └── chain.pem -> ../../archive/.../chain1.pem
├── archive/
│   └── vm1.api.agentic.local/
│       ├── fullchain1.pem   # Actual certificate
│       ├── privkey1.pem     # Actual private key
│       └── ...
└── renewal/
    └── vm1.api.agentic.local.conf
```

### ADEPT Certificate Location

```
/path/to/adept-extended-2025-11-07/
└── deployment/local/docker-compose/certs/
    ├── vm1.api.agentic.local.crt   # Copied from fullchain.pem
    └── vm1.api.agentic.local.key   # Copied from privkey.pem
```

**Permissions**:
- `.crt` file: `644` (rw-r--r--)
- `.key` file: `600` (rw-------)

---

## Using Bootstrap Container with Let's Encrypt

### Workflow 1: Generate Certificate Inside Container

**⚠️ Limitation**: Interactive DNS-01 challenge won't work in container

```bash
# Use HTTP-01 challenge (non-interactive)
docker compose -f examples/demo-bootstrap/docker-compose.bootstrap.yaml \
  --profile bootstrap run --rm demo_bootstrap letsencrypt \
  --hostname vm1.api.agentic.local \
  --email admin@example.com \
  --challenge http \
  --output-dir /output

# Certificates exported to: examples/demo-bootstrap/output/certs/
```

### Workflow 2: Generate on Host, Import to Container

**Recommended for DNS-01 challenge**:

```bash
# Step 1: Generate on host (interactive DNS-01)
sudo certbot certonly --manual --preferred-challenges dns \
  -d vm1.api.agentic.local \
  --email admin@example.com \
  --agree-tos

# Step 2: Bootstrap container exports to artifacts
docker compose -f examples/demo-bootstrap/docker-compose.bootstrap.yaml \
  --profile bootstrap run --rm demo_bootstrap letsencrypt \
  --hostname vm1.api.agentic.local \
  --email admin@example.com \
  --output-dir /output

# Container finds existing cert in /etc/letsencrypt/live/ and exports it
```

### Workflow 3: Manual Copy to Artifacts

**If you already have certificates**:

```bash
# Copy existing certs to artifact directory
mkdir -p examples/demo-bootstrap/output/certs

sudo cp /etc/letsencrypt/live/vm1.api.agentic.local/fullchain.pem \
        examples/demo-bootstrap/output/certs/vm1.api.agentic.local.crt

sudo cp /etc/letsencrypt/live/vm1.api.agentic.local/privkey.pem \
        examples/demo-bootstrap/output/certs/vm1.api.agentic.local.key

# Set permissions
chmod 644 examples/demo-bootstrap/output/certs/*.crt
chmod 600 examples/demo-bootstrap/output/certs/*.key

# Continue with bootstrap for config/script generation
docker compose -f examples/demo-bootstrap/docker-compose.bootstrap.yaml \
  --profile bootstrap run --rm demo_bootstrap deploy \
  --hostname vm1.api.agentic.local \
  --peer-hostname vm2.api.agentic.local \
  --vm1-ip 192.168.1.100 \
  --vm2-ip 192.168.1.101 \
  --email admin@example.com \
  --output-dir /output
```

---

## Certbot Prerequisites Checklist

### Before Running Certbot

- [ ] **Root/sudo access**: Certbot needs to write to `/etc/letsencrypt/`
- [ ] **Domain ownership**: You control DNS or web server for the domain
- [ ] **Email address**: For expiration notifications
- [ ] **Port availability** (HTTP-01): Port 80 free or nginx running
- [ ] **DNS access** (DNS-01): Ability to create TXT records

### Verify Prerequisites

```bash
# Check sudo access
sudo whoami
# Expected: root

# Check port 80 (for HTTP-01)
sudo netstat -tulpn | grep :80
# Expected: Empty (port free) or nginx process

# Check DNS resolution (critical!)
dig vm1.api.agentic.local
# Expected: Your VM's IP address

# Check internet connectivity
curl -I https://acme-v02.api.letsencrypt.org/directory
# Expected: HTTP/2 200
```

---

## Utility Scripts Reference

### Script 1: setup-letsencrypt.sh

**Location**: `examples/demo-bootstrap/scripts/setup-letsencrypt.sh`

**Purpose**: Simple wrapper for Let's Encrypt operations

**Usage**:
```bash
./setup-letsencrypt.sh <hostname> [email] [dns|http]

# Examples:
./setup-letsencrypt.sh vm1.api.agentic.local admin@example.com dns
./setup-letsencrypt.sh vm2.api.agentic.local admin@example.com http
```

**What It Does**:
- Validates parameters
- Calls `bootstrap_main.py letsencrypt` command
- Handles errors gracefully

### Script 2: Bootstrap CLI letsencrypt Command

**Location**: `examples/demo-bootstrap/bootstrap_main.py` (line ~135)

**Usage**:
```bash
python bootstrap_main.py letsencrypt \
  --hostname vm1.api.agentic.local \
  --email admin@example.com \
  --challenge dns \
  --output-dir /output
```

**What It Does**:
1. Creates LetsEncryptManager instance
2. Runs `certbot certonly` with specified challenge
3. Copies certificates to output directory
4. Generates renewal hook script
5. Sets proper permissions

**Command Options**:
- `--hostname` (required): Domain for certificate
- `--email` (required): Contact email
- `--challenge` (optional): `dns` or `http` (default: `dns`)
- `--output-dir` (optional): Output directory (default: `/output`)

### Script 3: Generated renewal-hook.sh

**Location**: Generated in `output/certs/renewal-hook.sh` (after bootstrap)

**Purpose**: Automatic certificate renewal integration

**Installation**:
```bash
# Install to Let's Encrypt renewal hooks
sudo cp /tmp/adept-artifacts/certs/renewal-hook.sh \
        /etc/letsencrypt/renewal-hooks/deploy/adept-reload.sh

sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/adept-reload.sh

# Test renewal
sudo certbot renew --dry-run
```

**What It Does**:
- Triggered automatically after `certbot renew` succeeds
- Copies renewed certificates to ADEPT directory
- Reloads nginx to pick up new certificates
- Logs all operations

---

## Complete Let's Encrypt Workflows

### Workflow A: DNS-01 Challenge (Internal Networks)

**Prerequisites**:
- ✅ Certbot installed on host
- ✅ DNS provider access
- ✅ Domain resolves to VM

**Steps**:

```bash
# Step 1: Generate certificate on host (interactive)
sudo certbot certonly --manual --preferred-challenges dns \
  -d vm1.api.agentic.local \
  --email admin@example.com \
  --agree-tos

# Certbot will display:
# "Please deploy a DNS TXT record..."
# Value: ABC123XYZ...

# Step 2: Create TXT record in DNS provider
# Name:  _acme-challenge.vm1.api.agentic.local
# Type:  TXT
# Value: ABC123XYZ...

# Step 3: Verify DNS propagation
dig _acme-challenge.vm1.api.agentic.local TXT
# Should show your TXT record

# Step 4: Press Enter in certbot
# Certificates saved to: /etc/letsencrypt/live/vm1.api.agentic.local/

# Step 5: Use bootstrap to export and generate artifacts
docker compose -f examples/demo-bootstrap/docker-compose.bootstrap.yaml \
  --profile bootstrap run --rm demo_bootstrap letsencrypt \
  --hostname vm1.api.agentic.local \
  --email admin@example.com \
  --output-dir /output

# Artifacts in: examples/demo-bootstrap/output/certs/
```

### Workflow B: HTTP-01 Challenge (Public Networks)

**Prerequisites**:
- ✅ Certbot installed on host
- ✅ Port 80 accessible from internet
- ✅ Domain resolves to public IP

**Steps**:

```bash
# Step 1: Ensure port 80 is free
sudo netstat -tulpn | grep :80
# Should be empty

# Step 2: Generate certificate (fully automated)
sudo certbot certonly --standalone \
  -d vm1.api.agentic.local \
  --email admin@example.com \
  --agree-tos

# Certificates saved to: /etc/letsencrypt/live/vm1.api.agentic.local/

# Step 3: Use bootstrap to export
docker compose -f examples/demo-bootstrap/docker-compose.bootstrap.yaml \
  --profile bootstrap run --rm demo_bootstrap letsencrypt \
  --hostname vm1.api.agentic.local \
  --email admin@example.com \
  --output-dir /output
```

### Workflow C: Using Existing Certificates

**Prerequisites**:
- ✅ Existing certificates in `/etc/letsencrypt/live/`

**Steps**:

```bash
# Certificates already exist at:
# /etc/letsencrypt/live/OLD_DOMAIN/

# Option 1: Copy to new domain name
sudo cp -r /etc/letsencrypt/live/OLD_DOMAIN/ \
           /etc/letsencrypt/live/vm1.api.agentic.local/

# Option 2: Use bootstrap to export
docker compose -f examples/demo-bootstrap/docker-compose.bootstrap.yaml \
  --profile bootstrap run --rm demo_bootstrap letsencrypt \
  --hostname vm1.api.agentic.local \
  --email admin@example.com \
  --output-dir /output

# Bootstrap finds existing cert and exports it
```

---

## Certificate Renewal

### Automatic Renewal Setup

**Certificates expire every 90 days** - renewal must be automated!

```bash
# Step 1: Install renewal hook (from generated artifacts)
sudo cp /tmp/adept-artifacts/certs/renewal-hook.sh \
        /etc/letsencrypt/renewal-hooks/deploy/adept-reload.sh
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/adept-reload.sh

# Step 2: Setup cron job (twice daily)
(sudo crontab -l 2>/dev/null; echo "0 0,12 * * * certbot renew --quiet") | sudo crontab -

# Step 3: Test renewal (dry-run)
sudo certbot renew --dry-run
# Expected: "Congratulations, all renewals succeeded"
```

### Manual Renewal

```bash
# Check certificate expiration
sudo certbot certificates

# Renew specific certificate
sudo certbot renew --cert-name vm1.api.agentic.local

# Renew all certificates
sudo certbot renew

# Force renewal (even if not expiring soon)
sudo certbot renew --force-renewal
```

---

## Troubleshooting

### "certbot: command not found"

**Solution**: Install certbot
```bash
sudo apt update
sudo apt install -y certbot
```

### "Permission denied" (writing to /etc/letsencrypt)

**Solution**: Run with sudo
```bash
sudo certbot certonly ...
```

### DNS-01: "DNS query failed"

**Problem**: TXT record not found or not propagated

**Solution**:
```bash
# Verify TXT record exists
dig _acme-challenge.vm1.api.agentic.local TXT

# Check from external DNS
dig @8.8.8.8 _acme-challenge.vm1.api.agentic.local TXT

# Wait 5-10 minutes for DNS propagation
```

### HTTP-01: "Connection refused" on port 80

**Problem**: Port 80 not accessible or blocked

**Solution**:
```bash
# Check port 80 is free
sudo netstat -tulpn | grep :80

# Check firewall
sudo ufw status | grep 80

# Allow port 80
sudo ufw allow 80/tcp

# Test from external
curl http://vm1.api.agentic.local/.well-known/acme-challenge/test
```

### "Certificate already exists"

**Problem**: Certificate for domain already exists

**Solution**:
```bash
# Use existing certificate
# OR delete and regenerate
sudo certbot delete --cert-name vm1.api.agentic.local
```

### "Too many certificates already issued"

**Problem**: Let's Encrypt rate limit (5 per week)

**Solution**:
- Wait 7 days for rate limit reset
- Use staging environment for testing:
  ```bash
  certbot --staging certonly ...
  ```
- Check rate limits: https://letsencrypt.org/docs/rate-limits/

---

## Testing Certificate Validation

### Verify Certificate Contents

```bash
# Check certificate details
sudo openssl x509 -in /etc/letsencrypt/live/vm1.api.agentic.local/fullchain.pem -text -noout

# Check expiration date
sudo openssl x509 -in /etc/letsencrypt/live/vm1.api.agentic.local/fullchain.pem -enddate -noout

# Verify domain name
sudo openssl x509 -in /etc/letsencrypt/live/vm1.api.agentic.local/fullchain.pem -subject -noout
```

### Test HTTPS with New Certificate

```bash
# Test nginx with new certificate
curl -I https://vm1.api.agentic.local/health

# Check certificate via openssl
openssl s_client -connect vm1.api.agentic.local:443 -servername vm1.api.agentic.local < /dev/null

# Verify no SSL errors
curl -v https://vm1.api.agentic.local/health 2>&1 | grep "SSL certificate verify"
# Expected: "SSL certificate verify ok"
```

---

## Best Practices

### 1. Always Use DNS-01 for Internal Networks

**Why**: HTTP-01 requires public port 80 access

### 2. Setup Automatic Renewal Immediately

**Why**: Certificates expire in 90 days - forgotten renewals cause outages

### 3. Monitor Certificate Expiration

**How**:
```bash
# Check expiration dates
sudo certbot certificates

# Get notification email from Let's Encrypt
# (configured via --email flag)
```

### 4. Test Renewal Before Production

**How**:
```bash
# Dry-run renewal
sudo certbot renew --dry-run

# Test renewal hook
sudo /etc/letsencrypt/renewal-hooks/deploy/adept-reload.sh
```

### 5. Keep Renewal Hooks Idempotent

**Why**: Renewal hooks run automatically - must be safe to run multiple times

**Verify**:
```bash
# Run hook twice - should succeed both times
sudo /etc/letsencrypt/renewal-hooks/deploy/adept-reload.sh
sudo /etc/letsencrypt/renewal-hooks/deploy/adept-reload.sh
```

---

## Quick Reference

### certbot Commands

```bash
# Generate certificate (DNS-01)
sudo certbot certonly --manual --preferred-challenges dns -d DOMAIN --email EMAIL

# Generate certificate (HTTP-01)
sudo certbot certonly --standalone -d DOMAIN --email EMAIL

# List certificates
sudo certbot certificates

# Renew all certificates
sudo certbot renew

# Test renewal
sudo certbot renew --dry-run

# Delete certificate
sudo certbot delete --cert-name DOMAIN

# Revoke certificate
sudo certbot revoke --cert-path /etc/letsencrypt/live/DOMAIN/fullchain.pem
```

### Bootstrap Commands

```bash
# Generate certificate + artifacts
docker compose -f examples/demo-bootstrap/docker-compose.bootstrap.yaml \
  --profile bootstrap run --rm demo_bootstrap letsencrypt \
  --hostname DOMAIN --email EMAIL --challenge TYPE

# Full deployment artifacts
docker compose -f examples/demo-bootstrap/docker-compose.bootstrap.yaml \
  --profile bootstrap run --rm demo_bootstrap deploy \
  --hostname VM1_DOMAIN --peer-hostname VM2_DOMAIN \
  --vm1-ip VM1_IP --vm2-ip VM2_IP --email EMAIL
```

---

## References

- **Let's Encrypt Documentation**: https://letsencrypt.org/docs/
- **Certbot Documentation**: https://eff-certbot.readthedocs.io/
- **Rate Limits**: https://letsencrypt.org/docs/rate-limits/
- **Challenge Types**: https://letsencrypt.org/docs/challenge-types/
- **ACME Protocol**: https://tools.ietf.org/html/rfc8555

---

**Last Updated**: 2026-02-09
**Status**: Complete ✅
**Prerequisites Documented**: Yes ✅
**Utility Scripts Documented**: Yes ✅
**Workflows Documented**: 3 complete workflows ✅

---

## Frequently Asked Questions

### Do I need to create a Let's Encrypt account first?

**NO** - Certbot creates your account automatically.

**First time you run certbot**:
```bash
sudo certbot certonly --standalone -d example.com --email you@example.com --agree-tos
```

**What happens**:
1. Certbot checks if account exists in `/etc/letsencrypt/accounts/`
2. If not found, automatically registers new account
3. Output shows: "Account registered."
4. Account is permanently stored locally
5. Future certbot runs reuse the same account

**Where is the account stored?**
```bash
ls /etc/letsencrypt/accounts/
# Shows: acme-v02.api.letsencrypt.org/directory/abc123...
```

**Can I use the same account on multiple servers?**

Yes! Copy the accounts directory:
```bash
# On Server 1 (has account)
sudo tar -czf letsencrypt-account.tar.gz /etc/letsencrypt/accounts/

# Transfer to Server 2
scp letsencrypt-account.tar.gz user@server2:/tmp/

# On Server 2
sudo tar -xzf /tmp/letsencrypt-account.tar.gz -C /
```

### What email should I use?

**Use a monitored email address** - Let's Encrypt sends:
- Certificate expiration warnings (30 days, 14 days, 7 days before expiry)
- Security notifications
- Service announcements

**Recommended**:
- Team inbox: `devops@yourcompany.com`
- Admin inbox: `admin@yourcompany.com`

**NOT recommended**:
- Personal email that might change
- Unmonitored addresses
- Shared accounts you might lose access to

### How many certificates can I request?

**Let's Encrypt Rate Limits**:
- **50 certificates per domain per week** (e.g., 50 certs for `*.example.com`)
- **5 certificates per exact domain per week** (e.g., 5 certs for `vm1.example.com`)
- **300 new accounts per IP per 3 hours**

**For testing**:
```bash
# Use staging environment (no rate limits)
sudo certbot --staging certonly --standalone -d test.example.com --email you@example.com
```

**Production**:
- Plan certificate requests carefully
- Use staging for testing first
- Production certificates have rate limits

### Do certificates cost money?

**NO** - Let's Encrypt is 100% free!

- ✅ Free SSL/TLS certificates
- ✅ No subscription fees
- ✅ No hidden costs
- ✅ Unlimited renewals

**Only cost**: Time to setup automation

### How long are certificates valid?

**90 days** - shorter than traditional CAs (365 days)

**Why 90 days?**
- Encourages automation
- Reduces impact of compromised certificates
- Industry best practice

**Renewal recommendation**: Renew every 60 days (30-day buffer)

**Automatic renewal**:
```bash
# Setup cron (twice daily checks)
(sudo crontab -l 2>/dev/null; echo "0 0,12 * * * certbot renew --quiet") | sudo crontab -

# Certbot only renews if <30 days remain
```

### Can I get wildcard certificates?

**Yes** - but only with DNS-01 challenge

```bash
sudo certbot certonly --manual --preferred-challenges dns \
  -d '*.example.com' \
  -d example.com \
  --email admin@example.com \
  --agree-tos
```

**Note**: You need to create **2 TXT records** (one for wildcard, one for apex)

### What if port 80 is already in use?

**Option 1: Use webroot plugin** (nginx running)
```bash
sudo certbot certonly --webroot \
  -w /var/www/html \
  -d vm1.api.agentic.local \
  --email admin@example.com
```

**Option 2: Use DNS-01 challenge** (no port 80 needed)
```bash
sudo certbot certonly --manual --preferred-challenges dns \
  -d vm1.api.agentic.local \
  --email admin@example.com
```

**Option 3: Temporarily stop web server**
```bash
sudo systemctl stop nginx
sudo certbot certonly --standalone -d vm1.api.agentic.local --email admin@example.com
sudo systemctl start nginx
```

### What if my VMs are air-gapped (no internet)?

**Let's Encrypt won't work** - requires internet for validation.

**Alternatives**:
1. **Self-signed certificates**:
   ```bash
   openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
     -keyout vm1.key -out vm1.crt \
     -subj "/CN=vm1.api.agentic.local"
   ```

2. **Internal CA** (like HashiCorp Vault)

3. **Certificate from public CA** (DigiCert, etc.) - costs money

### Can I test without affecting rate limits?

**Yes** - use Let's Encrypt staging environment

```bash
# Staging environment (no rate limits, test certificates)
sudo certbot --staging certonly --standalone \
  -d test.example.com \
  --email admin@example.com \
  --agree-tos

# Certificates work for testing but show warning in browsers
```

**Switch to production** when ready:
```bash
# Remove staging certificate
sudo certbot delete --cert-name test.example.com

# Request production certificate
sudo certbot certonly --standalone -d test.example.com --email admin@example.com
```

---

**Last Updated**: 2026-02-09
