#!/usr/bin/env python3
"""
Bootstrap Langfuse credentials with automatic initialization.

This script:
1. Checks if Langfuse credentials already exist in .env
2. Generates secure credentials if missing
3. Updates .env file atomically
4. Optionally initializes Langfuse (if services are available)

The script is idempotent and safe to run multiple times.
"""

import os
import sys
import time
import secrets
import logging
from pathlib import Path
from typing import Dict, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class LangfuseBootstrap:
    """Handles Langfuse credential generation and initialization."""

    def __init__(self):
        self.env_file = Path(os.getenv('ENV_FILE', '.env'))
        self.backup_file = Path('.env.langfuse')
        # Support both naming conventions
        self.required_keys = [
            'LANGFUSE_PUBLIC_KEY',
            'LANGFUSE_SECRET_KEY',
            'LANGFUSE_HOST'
        ]
        # Alternative naming convention
        self.alt_keys = {
            'LANGFUSE_PUBLIC_KEY': 'LANGFUSE_INIT_PROJECT_PUBLIC_KEY',
            'LANGFUSE_SECRET_KEY': 'LANGFUSE_INIT_PROJECT_SECRET_KEY'
        }
        self.langfuse_host = os.getenv('LANGFUSE_HOST', 'http://langfuse-web:3001')

    def credentials_exist(self) -> bool:
        """Check if Langfuse credentials already exist in .env"""
        if not self.env_file.exists():
            logger.info(f"Environment file {self.env_file} does not exist")
            return False

        existing = self.read_env_file()

        # Check if all required keys exist and have values (support both conventions)
        missing_keys = []
        for key in self.required_keys:
            # Check primary key or alternative key
            alt_key = self.alt_keys.get(key)
            primary_exists = key in existing and existing[key]
            alt_exists = alt_key and alt_key in existing and existing[alt_key]

            if not primary_exists and not alt_exists:
                missing_keys.append(key)

        if missing_keys:
            logger.info(f"Missing credentials: {', '.join(missing_keys)}")
            return False

        logger.info("✅ Langfuse credentials found in .env")
        return True

    def read_env_file(self) -> Dict[str, str]:
        """Read existing .env file into dictionary - preserves original format"""
        env_vars = {}
        if self.env_file.exists():
            with open(self.env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        # Preserve the entire value including any comments
                        # Only process Langfuse-related keys
                        if key.startswith('LANGFUSE_'):
                            # For Langfuse keys, strip quotes carefully
                            value = value.strip()
                            if len(value) >= 2:
                                if (value[0] == '"' and value[-1] == '"') or \
                                   (value[0] == "'" and value[-1] == "'"):
                                    value = value[1:-1]
                        else:
                            # For non-Langfuse keys, preserve exactly as-is
                            value = value.strip()
                        env_vars[key] = value
        return env_vars

    def generate_credentials(self) -> Dict[str, str]:
        """Generate secure Langfuse API credentials"""
        public_key = f"pk-lf-{secrets.token_hex(16)}"
        secret_key = f"sk-lf-{secrets.token_hex(16)}"

        credentials = {
            'LANGFUSE_PUBLIC_KEY': public_key,
            'LANGFUSE_SECRET_KEY': secret_key,
            'LANGFUSE_HOST': self.langfuse_host
        }

        logger.info(f"🔐 Generated public key: {public_key}")
        logger.info(f"🔐 Generated secret key: {secret_key[:10]}... (truncated)")

        return credentials

    def wait_for_services(self, timeout: int = 60) -> bool:
        """
        Wait for Langfuse services to be healthy.

        This is optional - the script will work even if services aren't ready.
        """
        # Only wait if explicitly requested
        if os.getenv('WAIT_FOR_SERVICES', 'false').lower() != 'true':
            logger.info("Skipping service health check (WAIT_FOR_SERVICES=false)")
            return True

        try:
            import requests
        except ImportError:
            logger.warning("requests library not available, skipping service check")
            return True

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # Check Langfuse API health
                response = requests.get(f"{self.langfuse_host}/api/public/health", timeout=5)
                if response.status_code == 200:
                    logger.info("✅ Langfuse services are healthy")
                    return True
            except Exception as e:
                logger.debug(f"Service check failed: {e}")

            logger.info("⏳ Waiting for Langfuse services...")
            time.sleep(5)

        logger.warning("⚠️  Timeout waiting for Langfuse services (will continue anyway)")
        return False

    def initialize_langfuse(self, credentials: Dict[str, str]) -> bool:
        """
        Initialize Langfuse with the generated credentials.

        In a production implementation, this would:
        1. Connect to Langfuse PostgreSQL
        2. Insert organization and project
        3. Insert API keys

        For now, we rely on Langfuse's environment-based initialization.
        """
        # Only initialize if explicitly requested
        if os.getenv('INITIALIZE_LANGFUSE', 'false').lower() != 'true':
            logger.info("Skipping Langfuse initialization (INITIALIZE_LANGFUSE=false)")
            return True

        logger.info("🔧 Initializing Langfuse with generated credentials...")

        # In the future, this could:
        # - Connect to Langfuse PostgreSQL directly
        # - Use Langfuse API to create org/project
        # - Insert credentials programmatically

        # For now, we assume Langfuse auto-provisions via environment variables
        logger.info("ℹ️  Langfuse will auto-provision on next restart with LANGFUSE_INIT_* variables")

        return True

    def update_env_file(self, credentials: Dict[str, str]):
        """Update ONLY Langfuse entries in .env file - preserves everything else exactly"""
        if not self.env_file.exists():
            # Create new file with just Langfuse entries
            with open(self.env_file, 'w') as f:
                f.write("# Environment configuration for ADEPT framework\n")
                f.write(f"# Langfuse credentials auto-generated at: {time.strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n")
                f.write("# Langfuse Observability\n")
                for key, value in sorted(credentials.items()):
                    f.write(f"{key}={value}\n")
                f.write("\n")
                f.write("OBSERVABILITY_BACKEND=langfuse\n")
            logger.info(f"✅ Created new {self.env_file} with Langfuse credentials")
            return

        # Read existing file
        with open(self.env_file, 'r') as f:
            lines = f.readlines()

        # Update or add Langfuse entries in-place
        updated_keys = set()
        temp_file = self.env_file.with_suffix('.tmp')

        with open(temp_file, 'w') as f:
            for line in lines:
                # Check if this line is a Langfuse key
                if '=' in line and not line.strip().startswith('#'):
                    key = line.split('=', 1)[0].strip()
                    if key in credentials:
                        # Replace with new value
                        f.write(f"{key}={credentials[key]}\n")
                        updated_keys.add(key)
                    else:
                        # Keep line exactly as-is (including comments, quotes, everything)
                        f.write(line)
                else:
                    # Keep non-assignment lines exactly as-is
                    f.write(line)

            # Add any missing Langfuse keys at the end
            missing_keys = set(credentials.keys()) - updated_keys
            if missing_keys:
                f.write("\n# Added by Langfuse bootstrap\n")
                for key in sorted(missing_keys):
                    f.write(f"{key}={credentials[key]}\n")

            # Add OBSERVABILITY_BACKEND if missing
            if 'OBSERVABILITY_BACKEND' not in self.read_env_file():
                f.write("OBSERVABILITY_BACKEND=langfuse\n")

        # Atomic replace
        temp_file.replace(self.env_file)
        logger.info(f"✅ Updated {self.env_file} with Langfuse credentials (preserved all other entries)")

    def save_backup(self, credentials: Dict[str, str]):
        """Save backup copy of credentials"""
        with open(self.backup_file, 'w') as f:
            f.write("# Langfuse credentials backup\n")
            f.write(f"# Generated at: {time.strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
            f.write("# These are also saved in your main .env file\n\n")
            for key, value in credentials.items():
                f.write(f"{key}={value}\n")
            f.write("\n# To use these credentials:\n")
            f.write("# 1. Copy to your .env file, or\n")
            f.write("# 2. Source this file: source .env.langfuse\n")
        logger.info(f"📄 Backup saved to {self.backup_file}")

    def run(self) -> int:
        """Main bootstrap logic - only runs if needed"""
        logger.info("🚀 Starting Langfuse credential bootstrap...")

        # Check if already exists
        if self.credentials_exist():
            logger.info("ℹ️  Skipping bootstrap (credentials already exist)")
            logger.info("💡 To regenerate, delete LANGFUSE_* variables from .env and run again")
            return 0

        logger.info("🔑 Langfuse credentials not found, generating...")

        # Wait for services (optional)
        self.wait_for_services()

        # Generate credentials
        credentials = self.generate_credentials()

        # Initialize Langfuse (optional)
        self.initialize_langfuse(credentials)

        # Update .env file
        try:
            self.update_env_file(credentials)
        except Exception as e:
            logger.error(f"❌ Failed to update .env file: {e}")
            return 1

        # Save backup
        try:
            self.save_backup(credentials)
        except Exception as e:
            logger.warning(f"⚠️  Failed to save backup (non-critical): {e}")

        logger.info("✅ Langfuse credentials bootstrapped successfully")
        logger.info("ℹ️  Services will use these credentials on next restart")

        return 0


def main():
    """Entry point for the bootstrap script"""
    try:
        bootstrap = LangfuseBootstrap()
        return bootstrap.run()
    except KeyboardInterrupt:
        logger.info("\n⚠️  Bootstrap interrupted by user")
        return 130
    except Exception as e:
        logger.error(f"❌ Bootstrap failed with error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())