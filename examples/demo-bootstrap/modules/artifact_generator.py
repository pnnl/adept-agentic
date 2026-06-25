"""
Artifact generation for ADEPT two-VM deployments.
Generates configs, scripts, and documentation for manual/automated deployment.
"""

import json
from pathlib import Path
from typing import Dict, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class ArtifactGenerator:
    """Generates deployment artifacts for ADEPT."""

    def __init__(self, output_dir: str = "/output"):
        self.output_dir = Path(output_dir)
        self.certs_dir = self.output_dir / "certs"
        self.configs_dir = self.output_dir / "configs"
        self.scripts_dir = self.output_dir / "scripts"
        self.a2a_dir = self.output_dir / "a2a"

        # Create output directories
        for dir_path in [self.certs_dir, self.configs_dir, self.scripts_dir, self.a2a_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)

    def generate_env_updates(self, hostname: str) -> str:
        """Generate shell script to update .env file."""

        script_content = f"""#!/bin/bash
# Generated .env updates for {hostname}

ENV_FILE="${{1:-.env}}"

echo "Updating ADEPT configuration for {hostname}..."

# Backup existing .env
cp "$ENV_FILE" "${{ENV_FILE}}.backup.$(date +%Y%m%d_%H%M%S)"

# Update hostname configuration
sed -i 's|^PUBLIC_HOSTNAME=.*|PUBLIC_HOSTNAME={hostname}|' "$ENV_FILE"
sed -i 's|^PUBLIC_BASE_URL=.*|PUBLIC_BASE_URL=https://{hostname}|' "$ENV_FILE"
sed -i 's|^AGENT_GATEWAY_EXTERNAL_URL=.*|AGENT_GATEWAY_EXTERNAL_URL=https://{hostname}/v1|' "$ENV_FILE"

echo "✅ Configuration updated"
echo "Backup saved to: ${{ENV_FILE}}.backup.*"
"""

        output_file = self.configs_dir / "env-updates.sh"
        output_file.write_text(script_content)
        output_file.chmod(0o755)

        logger.info(f"Generated env update script: {output_file}")
        return str(output_file)

    def generate_hosts_entries(self, vm1_hostname: str, vm1_ip: str,
                               vm2_hostname: str, vm2_ip: str) -> str:
        """Generate /etc/hosts entries."""

        hosts_content = f"""# ADEPT Two-VM A2A Mesh
# Add these entries to /etc/hosts on BOTH VMs

{vm1_ip}  {vm1_hostname}
{vm2_ip}  {vm2_hostname}

# Apply with:
# sudo tee -a /etc/hosts < hosts-entries.txt
"""

        output_file = self.configs_dir / "hosts-entries.txt"
        output_file.write_text(hosts_content)

        logger.info(f"Generated hosts entries: {output_file}")
        return str(output_file)

    def generate_cert_apply_script(self, hostname: str) -> str:
        """Generate script to apply certificates to ADEPT.

        IMPORTANT: Certificates are copied to data/nginx_certs/ which is mounted by
        nginx_proxy for TLS termination. The nginx_proxy container expects certificates
        at /etc/nginx/certs/${HOSTNAME}.crt and .key
        """

        script_content = f"""#!/bin/bash
# Apply Let's Encrypt certificates to ADEPT
#
# IMPORTANT: Certificates are copied to data/nginx_certs/ which is mounted by
# nginx_proxy for TLS termination. The nginx_proxy container expects certificates
# at /etc/nginx/certs/${{HOSTNAME}}.crt and .key

set -e

HOSTNAME="{hostname}"
ADEPT_ROOT="${{1:-$(pwd)}}"
SOURCE_DIR="$(dirname "$0")/../certs"
DEST_DIR="${{ADEPT_ROOT}}/data/nginx_certs"

echo "📋 Applying certificates for ${{HOSTNAME}}"
echo "Destination: ${{DEST_DIR}}"

# Create destination directory
mkdir -p "${{DEST_DIR}}"

# Copy certificates
cp "${{SOURCE_DIR}}/${{HOSTNAME}}.crt" "${{DEST_DIR}}/${{HOSTNAME}}.crt"
cp "${{SOURCE_DIR}}/${{HOSTNAME}}.key" "${{DEST_DIR}}/${{HOSTNAME}}.key"

# Set permissions
chmod 644 "${{DEST_DIR}}/${{HOSTNAME}}.crt"
chmod 600 "${{DEST_DIR}}/${{HOSTNAME}}.key"

echo "✅ Certificates copied to ${{DEST_DIR}}"
echo ""
echo "Verification:"
echo "  docker exec nginx_proxy ls -la /etc/nginx/certs/"
echo ""
echo "Next steps:"
echo "  1. Run configs/env-updates.sh to update .env"
echo "  2. Run scripts/restart-services.sh to reload nginx"
"""

        output_file = self.scripts_dir / "apply-certificates.sh"
        output_file.write_text(script_content)
        output_file.chmod(0o755)

        logger.info(f"Generated certificate apply script: {output_file}")
        return str(output_file)

    def generate_a2a_registration_payload(self, alias: str, public_url: str,
                                         description: str = "", tags: List[str] = None) -> str:
        """Generate JSON payload for A2A registration."""

        capabilities = []
        if description:
            capabilities.append(f"description:{description}")
        if tags:
            capabilities.extend([f"tag:{tag}" for tag in tags])

        payload = {
            "alias": alias,
            "public_url": public_url,
            "capabilities": capabilities
        }

        output_file = self.a2a_dir / f"register-{alias}.json"
        output_file.write_text(json.dumps(payload, indent=2))

        logger.info(f"Generated A2A registration payload: {output_file}")
        return str(output_file)

    def generate_a2a_registration_script(self, alias: str, public_url: str,
                                         description: str = "", tags: List[str] = None) -> str:
        """Generate shell script for A2A registration.

        IMPORTANT: Uses nginx_proxy routing (/internal/registry) for external access.
        The gateway_registry service (port 8086) is INTERNAL and should not be exposed.
        All external access must go through nginx_proxy on ports 80/443.
        """

        tags_str = ",".join(tags) if tags else ""

        script_content = f"""#!/bin/bash
# Register peer gateway: {alias}
#
# IMPORTANT: Uses nginx_proxy routing (/internal/registry) for external access.
# The gateway_registry service (port 8086) is INTERNAL and should not be exposed.
# All external access must go through nginx_proxy on ports 80/443.

set -e

# Registry URL uses nginx_proxy routing (not direct port 8086)
REGISTRY_URL="${{GATEWAY_REGISTRY_URL:-https://localhost/internal/registry}}"

echo "📝 Registering peer gateway: {alias}"
echo "URL: {public_url}"
echo "Registry: $REGISTRY_URL"

# Method 1: Using agentic CLI (if installed)
if command -v agentic &> /dev/null; then
    agentic a2a register-peer {alias} {public_url} \\
        --description "{description}" \\
        --tags "{tags_str}" \\
        --registry-url "$REGISTRY_URL"
else
    # Method 2: Using curl with generated JSON payload
    echo "Using curl (agentic CLI not found)"

    # Get auth token
    KEYCLOAK_URL="${{KEYCLOAK_URL:-http://localhost:8180}}"
    CLIENT_ID="${{VALIDATION_RUNNER_CLIENT_ID}}"
    CLIENT_SECRET="${{VALIDATION_RUNNER_CLIENT_SECRET}}"

    TOKEN=$(curl -s -X POST "${{KEYCLOAK_URL}}/realms/master/protocol/openid-connect/token" \\
        -d "grant_type=client_credentials" \\
        -d "client_id=${{CLIENT_ID}}" \\
        -d "client_secret=${{CLIENT_SECRET}}" | jq -r '.access_token')

    # Register gateway (nginx rewrites /internal/registry/ -> /v1/)
    curl -X POST "${{REGISTRY_URL}}/gateways" \\
        -H "Authorization: Bearer ${{TOKEN}}" \\
        -H "Content-Type: application/json" \\
        -d @$(dirname "$0")/register-{alias}.json
fi

echo "✅ Registration complete"
"""

        output_file = self.a2a_dir / f"register-{alias}.sh"
        output_file.write_text(script_content)
        output_file.chmod(0o755)

        logger.info(f"Generated A2A registration script: {output_file}")
        return str(output_file)

    def generate_restart_script(self) -> str:
        """Generate script to restart ADEPT services."""

        script_content = """#!/bin/bash
# Restart ADEPT services to pick up new configuration

set -e

ADEPT_ROOT="${1:-$(pwd)}"

cd "$ADEPT_ROOT"

echo "🔄 Restarting ADEPT services..."

# Rebuild nginx to pick up new certificates
make rebuild-nginx-proxy

# Or full restart if needed
# make restart

echo "✅ Services restarted"
echo ""
echo "Verify with:"
echo "  curl -I https://$(grep PUBLIC_HOSTNAME .env | cut -d= -f2)/health"
"""

        output_file = self.scripts_dir / "restart-services.sh"
        output_file.write_text(script_content)
        output_file.chmod(0o755)

        logger.info(f"Generated restart script: {output_file}")
        return str(output_file)

    def generate_deployment_guide(self, vm1_hostname: str, vm2_hostname: str) -> str:
        """Generate markdown deployment guide."""

        guide_content = f"""# ADEPT Two-VM Deployment Guide

**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## VM Configuration

- **VM1**: {vm1_hostname}
- **VM2**: {vm2_hostname}

---

## Deployment Steps

### Phase 1: Prerequisites (Both VMs)

```bash
# 1. Install certbot
sudo apt update
sudo apt install -y certbot

# 2. Update /etc/hosts
sudo tee -a /etc/hosts < configs/hosts-entries.txt

# 3. Start ADEPT services
cd /path/to/adept-extended-2025-11-07
make start
```

### Phase 2: Apply Certificates (VM1)

```bash
# Copy certificates
./scripts/apply-certificates.sh /path/to/adept

# Update configuration
./configs/env-updates.sh /path/to/adept/.env

# Restart services
./scripts/restart-services.sh /path/to/adept
```

### Phase 3: Apply Certificates (VM2)

```bash
# Repeat Phase 2 steps on VM2
```

### Phase 4: Mutual A2A Registration

```bash
# On VM1: Register VM2
./a2a/register-vm2-gateway.sh

# On VM2: Register VM1
./a2a/register-vm1-gateway.sh
```

### Phase 5: Verification

```bash
# Test health endpoints
curl -I https://{vm1_hostname}/health
curl -I https://{vm2_hostname}/health

# Test A2A connectivity (from either VM)
agentic a2a list-peers
agentic a2a test-connection vm2-gateway
```

---

## Certificate Renewal

Certificates expire every 90 days. Renewal is automated via cron:

```bash
# Install renewal hook (already generated)
sudo cp certs/renewal-hook.sh /etc/letsencrypt/renewal-hooks/deploy/adept-reload.sh
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/adept-reload.sh

# Setup cron (twice daily)
(sudo crontab -l 2>/dev/null; echo "0 0,12 * * * certbot renew --quiet") | sudo crontab -
```

---

## Troubleshooting

See artifact directory for generated scripts and configs.
All artifacts are safe to review before applying.
"""

        output_file = self.output_dir / "DEPLOYMENT_GUIDE.md"
        output_file.write_text(guide_content)

        logger.info(f"Generated deployment guide: {output_file}")
        return str(output_file)
