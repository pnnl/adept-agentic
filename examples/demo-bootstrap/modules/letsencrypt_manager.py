"""
Let's Encrypt certificate generation and management for ADEPT deployments.
"""

import subprocess
import shutil
import os
from pathlib import Path
from typing import Literal, Optional
import logging

logger = logging.getLogger(__name__)


class LetsEncryptManager:
    """Manages Let's Encrypt certificates for ADEPT."""

    def __init__(
        self,
        hostname: str,
        email: str,
        adept_cert_dir: str = "/app/deployment/local/docker-compose/certs",
        challenge_type: Literal["dns", "http"] = "dns"
    ):
        self.hostname = hostname
        self.email = email
        self.adept_cert_dir = Path(adept_cert_dir)
        self.challenge_type = challenge_type
        self.le_live = Path(f"/etc/letsencrypt/live/{hostname}")

    def generate_certificate(self) -> bool:
        """
        Generate Let's Encrypt certificate using certbot.

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Generating Let's Encrypt certificate for {self.hostname}")

        try:
            if self.challenge_type == "dns":
                self._generate_dns_challenge()
            else:
                self._generate_http_challenge()

            logger.info("Certificate generated successfully")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Certificate generation failed: {e}")
            return False

    def _generate_dns_challenge(self):
        """Generate certificate using DNS-01 challenge (manual)."""
        cmd = [
            "certbot", "certonly",
            "--manual",
            "--preferred-challenges", "dns",
            "--email", self.email,
            "--agree-tos",
            "--no-eff-email",
            "-d", self.hostname
        ]

        logger.info(f"Running: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)

    def _generate_http_challenge(self):
        """Generate certificate using HTTP-01 challenge (standalone)."""
        cmd = [
            "certbot", "certonly",
            "--standalone",
            "--preferred-challenges", "http",
            "--email", self.email,
            "--agree-tos",
            "--no-eff-email",
            "-d", self.hostname
        ]

        logger.info(f"Running: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)

    def copy_to_output(self, output_dir: str = "/output/certs") -> bool:
        """
        Copy Let's Encrypt certificates to output directory for artifact export.

        Args:
            output_dir: Output directory for certificate artifacts

        Returns:
            True if successful, False otherwise
        """
        if not self.le_live.exists():
            logger.error(f"Let's Encrypt certificates not found at {self.le_live}")
            return False

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Copy fullchain and private key
        try:
            shutil.copy(
                self.le_live / "fullchain.pem",
                output_path / f"{self.hostname}.crt"
            )
            shutil.copy(
                self.le_live / "privkey.pem",
                output_path / f"{self.hostname}.key"
            )

            # Set proper permissions
            (output_path / f"{self.hostname}.crt").chmod(0o644)
            (output_path / f"{self.hostname}.key").chmod(0o600)

            logger.info(f"Certificates exported to {output_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to copy certificates: {e}")
            return False

    def generate_renewal_hook(self, output_dir: str = "/output/certs", adept_root: str = "/app") -> bool:
        """
        Generate renewal hook script for automatic certificate updates.

        Args:
            output_dir: Output directory for renewal hook script
            adept_root: Path to ADEPT installation root

        Returns:
            True if successful, False otherwise
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        hook_script = output_path / "renewal-hook.sh"

        hook_content = f"""#!/bin/bash
# Let's Encrypt renewal hook for ADEPT
# Install to: /etc/letsencrypt/renewal-hooks/deploy/adept-reload.sh

set -e

HOSTNAME="${{RENEWED_DOMAINS}}"
ADEPT_ROOT="{adept_root}"
CERT_DIR="${{ADEPT_ROOT}}/deployment/local/docker-compose/certs"

# Copy renewed certificates
cp "${{RENEWED_LINEAGE}}/fullchain.pem" "${{CERT_DIR}}/${{HOSTNAME}}.crt"
cp "${{RENEWED_LINEAGE}}/privkey.pem" "${{CERT_DIR}}/${{HOSTNAME}}.key"

# Set permissions
chmod 644 "${{CERT_DIR}}/${{HOSTNAME}}.crt"
chmod 600 "${{CERT_DIR}}/${{HOSTNAME}}.key"

# Reload nginx
docker exec nginx_proxy nginx -s reload 2>/dev/null || true
"""

        try:
            hook_script.write_text(hook_content)
            hook_script.chmod(0o755)
            logger.info(f"Renewal hook generated at {hook_script}")
            return True

        except Exception as e:
            logger.error(f"Failed to generate renewal hook: {e}")
            return False

    def test_renewal(self) -> bool:
        """
        Test certificate renewal (dry-run).

        Returns:
            True if renewal succeeds, False otherwise
        """
        try:
            subprocess.run(
                ["certbot", "renew", "--dry-run"],
                check=True,
                capture_output=True
            )
            logger.info("Renewal dry-run successful")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Renewal dry-run failed: {e}")
            return False
