#!/usr/bin/env python3
"""
Langfuse Headless Initialization Script
========================================
Initializes Langfuse with default organization and project without UI interaction.

Based on: https://langfuse.com/self-hosting/administration/headless-initialization

This script uses environment variables to configure Langfuse during first startup:
- LANGFUSE_INIT_ORG_ID: Organization ID (optional, auto-generated if not provided)
- LANGFUSE_INIT_ORG_NAME: Organization name (default: "ADEPT")
- LANGFUSE_INIT_PROJECT_ID: Project ID (optional)
- LANGFUSE_INIT_PROJECT_NAME: Project name (default: "ADEPT-Default")
- LANGFUSE_INIT_PROJECT_PUBLIC_KEY: Public API key (optional, reads from LANGFUSE_PUBLIC_KEY if not set)
- LANGFUSE_INIT_PROJECT_SECRET_KEY: Secret API key (optional, reads from LANGFUSE_SECRET_KEY if not set)
- LANGFUSE_INIT_USER_EMAIL: Initial user email
- LANGFUSE_INIT_USER_NAME: Initial user name
- LANGFUSE_INIT_USER_PASSWORD: Initial user password

The script can be run in two modes:
1. Environment Variable Mode: Sets env vars in docker-compose.langfuse.yaml
2. Direct Database Mode: Connects to Langfuse PostgreSQL and creates entries

CRITICAL: The script now reads existing credentials from environment to prevent regeneration
on every restart, fixing the credential mismatch issue between .env and Langfuse database.
"""

import os
import sys
import uuid
import hashlib
import secrets
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
import bcrypt
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
import argparse
import yaml
import time
from dotenv import dotenv_values

# Configure logging with ADEPT framework standard format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s:%(funcName)s:%(lineno)d - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)


class LangfuseHeadlessInit:
    """Handles headless initialization of Langfuse."""

    def __init__(self,
                 db_host: str = "localhost",
                 db_port: int = 5434,
                 db_name: str = "langfuse",
                 db_user: str = "langfuse",
                 db_password: str = "langfuse_secure_password"):
        """Initialize with database connection parameters."""
        self.db_host = db_host
        self.db_port = db_port
        self.db_name = db_name
        self.db_user = db_user
        self.db_password = db_password
        self.conn = None
        self.cursor = None

    def connect_db(self) -> bool:
        """Establish database connection."""
        try:
            self.conn = psycopg2.connect(
                host=self.db_host,
                port=self.db_port,
                database=self.db_name,
                user=self.db_user,
                password=self.db_password
            )
            self.cursor = self.conn.cursor(cursor_factory=RealDictCursor)
            logger.info(f"Connected to Langfuse database at {self.db_host}:{self.db_port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            return False

    def close_db(self):
        """Close database connection."""
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()

    def wait_for_db(self, max_retries: int = 30, delay: int = 2) -> bool:
        """Wait for database to be ready."""
        for i in range(max_retries):
            if self.connect_db():
                return True
            logger.info(f"Waiting for database... ({i+1}/{max_retries})")
            time.sleep(delay)
        return False

    def check_if_initialized(self) -> bool:
        """Check if Langfuse is already initialized."""
        try:
            # Check if any users exist
            self.cursor.execute("SELECT COUNT(*) as count FROM users")
            result = self.cursor.fetchone()
            if result and result['count'] > 0:
                logger.info(f"Langfuse already initialized with {result['count']} users")
                return True
            return False
        except Exception as e:
            # Table might not exist yet if migrations haven't run
            logger.warning(f"Could not check initialization status: {e}")
            return False

    def load_credentials_from_env(
        self,
        env_file_path: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """Load credentials from .env file, then from os.environ.

        This method implements the fix for the credential drift issue by explicitly
        loading the .env file instead of only checking os.environ.

        Args:
            env_file_path: Path to .env file (auto-detected if None)

        Returns:
            (public_key, secret_key): Tuple of credentials, or (None, None) if not found
        """
        # Determine .env file path with fallback priority
        if not env_file_path:
            if os.path.exists("/app/.env"):
                env_file_path = "/app/.env"
            elif os.path.exists("/data/codeworkspace/adept-extended-2025-11-07/.env"):
                env_file_path = "/data/codeworkspace/adept-extended-2025-11-07/.env"
            elif os.path.exists(".env"):
                env_file_path = os.path.abspath(".env")
            else:
                logger.warning("No .env file found, will check os.environ only")
                env_vars = {}

        # Load .env file if it exists
        if env_file_path and os.path.exists(env_file_path):
            try:
                env_vars = dotenv_values(env_file_path)  # Returns dict, no side effects
                logger.info(f"Loaded environment from {env_file_path}")
            except Exception as e:
                logger.warning(f"Failed to load .env file: {e}, will check os.environ only")
                env_vars = {}
        else:
            env_vars = {}

        # Credential precedence: .env file → os.environ → None
        # Support both naming conventions:
        # - LANGFUSE_INIT_PROJECT_* (official Langfuse convention)
        # - LANGFUSE_* (simplified convention for runtime use)
        public_key = (
            env_vars.get("LANGFUSE_INIT_PROJECT_PUBLIC_KEY") or
            env_vars.get("LANGFUSE_PUBLIC_KEY") or
            os.getenv("LANGFUSE_INIT_PROJECT_PUBLIC_KEY") or
            os.getenv("LANGFUSE_PUBLIC_KEY")
        )
        secret_key = (
            env_vars.get("LANGFUSE_INIT_PROJECT_SECRET_KEY") or
            env_vars.get("LANGFUSE_SECRET_KEY") or
            os.getenv("LANGFUSE_INIT_PROJECT_SECRET_KEY") or
            os.getenv("LANGFUSE_SECRET_KEY")
        )

        if public_key and secret_key:
            logger.info(f"Found credentials:")
            logger.info(f"   Source: {env_file_path if env_vars else 'os.environ'}")
            logger.info(f"   Public Key: {public_key}")
            logger.info(f"   Secret Key: {secret_key[:15]}...")
        else:
            logger.info("No credentials found in .env file or os.environ")

        return public_key, secret_key

    def generate_api_keys(self) -> tuple[str, str]:
        """Generate public and secret API keys in UUID v4 format.

        LangFuse requires UUID v4 format with hyphens, not plain hex.
        This matches the format used by LangFuse web UI key generation.

        Format examples:
        - Public key:  pk-lf-2642c56d-d0e5-42b6-ae77-a453aa0400ef (42 chars)
        - Secret key:  sk-lf-605d18cd-cc38-4117-8427-d269d1951eb3 (42 chars)

        Previously used secrets.token_hex() which generated keys without hyphens:
        - pk-lf-5bbcfaa0a9eaf9a4d1bb13f1c5c79074 (38 chars) - WRONG FORMAT
        This caused 401 authentication errors with LangFuse API.
        """
        # Use UUID v4 format to match LangFuse web UI expectations
        public_key = f"pk-lf-{uuid.uuid4()}"
        secret_key = f"sk-lf-{uuid.uuid4()}"

        return public_key, secret_key

    def hash_password(self, password: str) -> str:
        """Hash password using bcrypt."""
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')

    def create_organization(self, org_id: Optional[str] = None,
                          org_name: str = "ADEPT") -> str:
        """Create organization in database."""
        if not org_id:
            org_id = str(uuid.uuid4())

        try:
            self.cursor.execute("""
                INSERT INTO organizations (id, name, created_at, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                RETURNING id
            """, (org_id, org_name, datetime.utcnow(), datetime.utcnow()))

            self.conn.commit()
            logger.info(f"Created organization: {org_name} (ID: {org_id})")
            return org_id
        except Exception as e:
            logger.error(f"Failed to create organization: {e}")
            self.conn.rollback()
            raise

    def create_project(self, org_id: str,
                      project_id: Optional[str] = None,
                      project_name: str = "ADEPT-Default",
                      public_key: Optional[str] = None,
                      secret_key: Optional[str] = None) -> Dict[str, str]:
        """Create project in database."""
        if not project_id:
            project_id = str(uuid.uuid4())

        if not public_key or not secret_key:
            public_key, secret_key = self.generate_api_keys()

        try:
            # First, create the project (projects table doesn't have API key columns)
            self.cursor.execute("""
                INSERT INTO projects (
                    id, name, org_id,
                    created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                RETURNING id
            """, (
                project_id, project_name, org_id,
                datetime.utcnow(), datetime.utcnow()
            ))

            # Now create the API key for this project in the api_keys table
            api_key_id = str(uuid.uuid4())

            # CRITICAL: Hash using LangFuse's algorithm: SHA256(secret_key + SHA256(salt))
            # This matches the createShaHash function in:
            # temp/langfuse/packages/shared/src/server/auth/apiKeys.ts
            salt = os.getenv("LANGFUSE_SALT", "changeme_32_char_minimum_salt")
            salt_hash = hashlib.sha256(salt.encode('utf-8')).hexdigest()
            hashed_secret = hashlib.sha256((secret_key + salt_hash).encode('utf-8')).hexdigest()

            display_secret = secret_key[:8] + "..."  # Display version for UI

            self.cursor.execute("""
                INSERT INTO api_keys (
                    id, project_id, organization_id, public_key,
                    hashed_secret_key, display_secret_key,
                    fast_hashed_secret_key, note,
                    created_at, scope
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (fast_hashed_secret_key) DO NOTHING
                RETURNING id
            """, (
                api_key_id, project_id, org_id, public_key,
                hashed_secret, display_secret,
                hashed_secret,  # Using same hash for fast_hashed for simplicity
                "Headless initialization key",
                datetime.utcnow(), "PROJECT"
            ))

            self.conn.commit()
            logger.info(f"Created project: {project_name} (ID: {project_id})")
            logger.info(f"Created API key for project")
            logger.info(f"   Public Key: {public_key}")
            logger.info(f"   Secret Key: {secret_key}")

            return {
                "id": project_id,
                "public_key": public_key,
                "secret_key": secret_key
            }
        except Exception as e:
            logger.error(f"Failed to create project: {e}")
            self.conn.rollback()
            raise

    def create_user(self, email: str, name: str, password: str) -> str:
        """Create user in database."""
        user_id = str(uuid.uuid4())
        hashed_password = self.hash_password(password)

        try:
            self.cursor.execute("""
                INSERT INTO users (
                    id, email, name, password,
                    email_verified, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (email) DO NOTHING
                RETURNING id
            """, (
                user_id, email, name, hashed_password,
                datetime.utcnow(),  # email_verified is a timestamp - use current time to mark as verified
                datetime.utcnow(), datetime.utcnow()
            ))

            self.conn.commit()
            logger.info(f"Created user: {email} (Name: {name})")
            return user_id
        except Exception as e:
            logger.error(f"Failed to create user: {e}")
            self.conn.rollback()
            raise

    def link_user_to_org(self, user_id: str, org_id: str, role: str = "ADMIN"):
        """Link user to organization with specified role."""
        membership_id = str(uuid.uuid4())
        try:
            self.cursor.execute("""
                INSERT INTO organization_memberships (
                    id, user_id, org_id, role,
                    created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, org_id) DO NOTHING
            """, (
                membership_id, user_id, org_id, role,
                datetime.utcnow(), datetime.utcnow()
            ))

            self.conn.commit()
            logger.info(f"Linked user to organization with role: {role}")
        except Exception as e:
            logger.error(f"Failed to link user to organization: {e}")
            self.conn.rollback()
            raise

    def initialize_from_env(self, force_reset: bool = False) -> Dict[str, Any]:
        """Initialize Langfuse using environment variables.

        Args:
            force_reset: If True, regenerate credentials even if they exist

        Returns:
            Dict with organization_id, project_id, public_key, secret_key, user_email
        """
        # Get configuration from environment
        org_id = os.getenv("LANGFUSE_INIT_ORG_ID")
        org_name = os.getenv("LANGFUSE_INIT_ORG_NAME", "ADEPT")
        project_id = os.getenv("LANGFUSE_INIT_PROJECT_ID")
        project_name = os.getenv("LANGFUSE_INIT_PROJECT_NAME", "ADEPT-Default")

        user_email = os.getenv("LANGFUSE_INIT_USER_EMAIL", "admin@adept.local")
        user_name = os.getenv("LANGFUSE_INIT_USER_NAME", "Admin")
        user_password = os.getenv("LANGFUSE_INIT_USER_PASSWORD", "admin_password")

        # Wait for database
        if not self.wait_for_db():
            raise Exception("Database not available")

        # Check if already initialized
        if self.check_if_initialized() and not force_reset:
            logger.info("Skipping initialization - Langfuse already configured")
            return {}

        # Load credentials from .env file (this is the FIX for credential drift)
        public_key, secret_key = self.load_credentials_from_env()

        # CREDENTIAL PRECEDENCE LOGIC (clear hierarchy, no circular logic)
        must_update_env = False

        if force_reset:
            # Flag set → Always generate new credentials
            logger.info("--force-reset flag detected, generating new credentials")
            public_key, secret_key = self.generate_api_keys()
            must_update_env = True

        elif public_key and secret_key:
            # Credentials exist in .env or environment → Use them
            logger.info(f"Using existing credentials from .env/environment:")
            logger.info(f"   Public Key: {public_key}")
            logger.info(f"   Secret Key: {secret_key[:15]}...")
            must_update_env = False

        else:
            # No credentials found → Generate new ones
            logger.info("No existing credentials found, generating new ones")
            public_key, secret_key = self.generate_api_keys()
            must_update_env = True

        # Create organization
        org_id = self.create_organization(org_id, org_name)

        # Create project
        project = self.create_project(
            org_id, project_id, project_name,
            public_key, secret_key
        )

        # Create user
        user_id = self.create_user(user_email, user_name, user_password)

        # Link user to organization
        self.link_user_to_org(user_id, org_id)

        # Close connection
        self.close_db()

        # Prepare credentials dict
        credentials = {
            "organization_id": org_id,
            "project_id": project["id"],
            "public_key": project["public_key"],
            "secret_key": project["secret_key"],
            "user_email": user_email
        }

        # Update .env if credentials were generated (not just when --update-env flag set)
        if must_update_env:
            logger.info("Updating .env file with new credentials")
            self.update_env_file(credentials, force_update=True)

        return credentials

    def update_env_file(self, credentials: Dict[str, Any], force_update: bool = False):
        """Update .env file with Langfuse credentials.

        This method implements the fix for credential drift by replacing existing
        credential values instead of returning early when they exist.

        Args:
            credentials: Dict containing public_key, secret_key, etc.
            force_update: If True, replaces existing credentials. If False, only appends if missing.
        """
        # Determine .env file path with fallback priority
        env_file = "/app/.env" if os.path.exists("/app/.env") else "/data/codeworkspace/adept-extended-2025-11-07/.env"

        if not os.path.exists(env_file):
            # No .env file exists, create new one
            with open(env_file, "w") as f:
                f.write("# Langfuse Observability Credentials (Auto-generated)\n")
                f.write(f"LANGFUSE_PUBLIC_KEY={credentials['public_key']}\n")
                f.write(f"LANGFUSE_SECRET_KEY={credentials['secret_key']}\n")
                f.write(f"LANGFUSE_INIT_PROJECT_PUBLIC_KEY={credentials['public_key']}\n")
                f.write(f"LANGFUSE_INIT_PROJECT_SECRET_KEY={credentials['secret_key']}\n")
                f.write("LANGFUSE_HOST=http://langfuse-web:3001\n")
                f.write(f"# Organization: {credentials.get('organization_id', 'N/A')}\n")
                f.write(f"# Project: {credentials.get('project_id', 'N/A')}\n")
                f.write(f"# User: {credentials.get('user_email', 'N/A')}\n")
            logger.info(f"Created {env_file} with Langfuse credentials")
            return

        # Read existing content line by line
        with open(env_file, "r") as f:
            lines = f.readlines()

        # Check if credentials exist
        has_public_key = any(line.startswith("LANGFUSE_PUBLIC_KEY=") for line in lines)
        has_secret_key = any(line.startswith("LANGFUSE_SECRET_KEY=") for line in lines)
        has_init_public = any(line.startswith("LANGFUSE_INIT_PROJECT_PUBLIC_KEY=") for line in lines)
        has_init_secret = any(line.startswith("LANGFUSE_INIT_PROJECT_SECRET_KEY=") for line in lines)

        if has_public_key and not force_update:
            logger.info(f"Langfuse credentials already in {env_file}, use --force-reset to update")
            return

        # Update existing lines or prepare to append new ones
        updated_lines = []
        keys_updated = set()

        for line in lines:
            if line.startswith("LANGFUSE_PUBLIC_KEY="):
                updated_lines.append(f"LANGFUSE_PUBLIC_KEY={credentials['public_key']}\n")
                keys_updated.add("LANGFUSE_PUBLIC_KEY")
            elif line.startswith("LANGFUSE_SECRET_KEY="):
                updated_lines.append(f"LANGFUSE_SECRET_KEY={credentials['secret_key']}\n")
                keys_updated.add("LANGFUSE_SECRET_KEY")
            elif line.startswith("LANGFUSE_INIT_PROJECT_PUBLIC_KEY="):
                updated_lines.append(f"LANGFUSE_INIT_PROJECT_PUBLIC_KEY={credentials['public_key']}\n")
                keys_updated.add("LANGFUSE_INIT_PROJECT_PUBLIC_KEY")
            elif line.startswith("LANGFUSE_INIT_PROJECT_SECRET_KEY="):
                updated_lines.append(f"LANGFUSE_INIT_PROJECT_SECRET_KEY={credentials['secret_key']}\n")
                keys_updated.add("LANGFUSE_INIT_PROJECT_SECRET_KEY")
            elif line.startswith("LANGFUSE_HOST="):
                updated_lines.append("LANGFUSE_HOST=http://langfuse-web:3001\n")
                keys_updated.add("LANGFUSE_HOST")
            else:
                updated_lines.append(line)

        # Append missing keys
        if "LANGFUSE_PUBLIC_KEY" not in keys_updated:
            updated_lines.append(f"LANGFUSE_PUBLIC_KEY={credentials['public_key']}\n")
        if "LANGFUSE_SECRET_KEY" not in keys_updated:
            updated_lines.append(f"LANGFUSE_SECRET_KEY={credentials['secret_key']}\n")
        if "LANGFUSE_INIT_PROJECT_PUBLIC_KEY" not in keys_updated:
            updated_lines.append(f"LANGFUSE_INIT_PROJECT_PUBLIC_KEY={credentials['public_key']}\n")
        if "LANGFUSE_INIT_PROJECT_SECRET_KEY" not in keys_updated:
            updated_lines.append(f"LANGFUSE_INIT_PROJECT_SECRET_KEY={credentials['secret_key']}\n")
        if "LANGFUSE_HOST" not in keys_updated:
            updated_lines.append("LANGFUSE_HOST=http://langfuse-web:3001\n")

        # Write updated content
        with open(env_file, "w") as f:
            f.writelines(updated_lines)

        logger.info(f"✅ Updated {env_file} with Langfuse credentials")
        logger.info(f"   Public Key: {credentials['public_key']}")
        logger.info(f"   Secret Key: {credentials['secret_key'][:15]}...")

    def validate_credentials(self, public_key: str, secret_key: str) -> bool:
        """Validate that credentials exist in LangFuse database.

        This method checks if the provided public_key exists in the api_keys table.
        Note: We only validate public_key existence, not secret_key hash, since
        LangFuse may use different hashing algorithms (bcrypt, SHA256, etc.).

        Args:
            public_key: The LangFuse public API key (pk-lf-*)
            secret_key: The LangFuse secret API key (sk-lf-*) - not used in validation

        Returns:
            True if credentials are valid, False otherwise
        """
        if not self.cursor:
            logger.error("Database cursor not initialized, cannot validate credentials")
            return False

        try:
            # Check if public_key exists in api_keys table
            self.cursor.execute("""
                SELECT COUNT(*) as count FROM api_keys
                WHERE public_key = %s
            """, (public_key,))

            result = self.cursor.fetchone()
            is_valid = result and result['count'] > 0

            if is_valid:
                logger.info(f"✅ Credentials validated successfully")
                logger.info(f"   Public Key: {public_key}")
            else:
                logger.warning(f"⚠️ Credentials validation failed")
                logger.warning(f"   Public Key not found: {public_key}")

            return is_valid

        except Exception as e:
            logger.error(f"❌ Credential validation failed with error: {e}")
            return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Initialize Langfuse with default organization and project"
    )
    parser.add_argument(
        "--mode",
        choices=["env", "direct"],
        default="env",
        help="Initialization mode: env (via environment variables) or direct (database)"
    )
    parser.add_argument(
        "--db-host",
        default="localhost",
        help="Database host (default: localhost)"
    )
    parser.add_argument(
        "--db-port",
        type=int,
        default=5434,
        help="Database port (default: 5434)"
    )
    parser.add_argument(
        "--update-env",
        action="store_true",
        help="Update .env file with generated credentials"
    )
    parser.add_argument(
        "--force-reset",
        action="store_true",
        help="Force regeneration of credentials even if they exist"
    )

    args = parser.parse_args()

    logger.info("Langfuse Headless Initialization")
    logger.info("=" * 40)

    # Initialize
    init = LangfuseHeadlessInit(
        db_host=args.db_host,
        db_port=args.db_port
    )

    try:
        if args.mode == "env":
            logger.info("Using environment variable mode")
            credentials = init.initialize_from_env(force_reset=args.force_reset)

            if credentials and args.update_env:
                init.update_env_file(credentials)
        else:
            logger.error("Direct database mode not yet implemented")
            sys.exit(1)

        logger.info("\nLangfuse initialization complete!")

    except Exception as e:
        logger.error(f"\nInitialization failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()