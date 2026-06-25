#!/usr/bin/env python3
"""
Langfuse Credentials Management CLI
====================================
Robust command-line utility for managing Langfuse credentials.

Commands:
    list      - Show current credential status
    validate  - Check credential consistency
    regenerate - Generate new credentials
    insert    - Insert credentials into database
    delete    - Remove credentials from database
    diagnose  - Troubleshooting diagnostics

Usage:
    python scripts/langfuse/manage_langfuse_credentials.py <command> [options]
"""

import os
import sys
import argparse
import secrets
import hashlib
import logging
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
import json

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False
    print("⚠️  Warning: psycopg2 not installed - database operations limited")
    print("   Install with: pip install psycopg2-binary")

try:
    from langfuse import Langfuse
    from langfuse.decorators import observe
    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class LangfuseCredentialsManager:
    """Manage Langfuse credentials."""

    def __init__(self):
        """Initialize the manager."""
        self.env_file = project_root / ".env"
        self.env_example_file = project_root / ".env.example"
        self.env_data = {}
        self.load_environment()

    def load_environment(self):
        """Load environment variables from .env file."""
        if self.env_file.exists():
            with open(self.env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        self.env_data[key] = value.strip('"').strip("'")

    def save_environment(self):
        """Save environment variables back to .env file."""
        # Read current file to preserve comments and order
        lines = []
        if self.env_file.exists():
            with open(self.env_file, 'r') as f:
                lines = f.readlines()

        # Update or add Langfuse variables (support both naming conventions)
        public_key = (
            self.env_data.get("LANGFUSE_INIT_PROJECT_PUBLIC_KEY") or
            self.env_data.get("LANGFUSE_PUBLIC_KEY", "")
        )
        secret_key = (
            self.env_data.get("LANGFUSE_INIT_PROJECT_SECRET_KEY") or
            self.env_data.get("LANGFUSE_SECRET_KEY", "")
        )

        langfuse_vars = {
            "LANGFUSE_PUBLIC_KEY": public_key,
            "LANGFUSE_SECRET_KEY": secret_key,
            "LANGFUSE_INIT_PROJECT_PUBLIC_KEY": public_key,  # Keep both conventions
            "LANGFUSE_INIT_PROJECT_SECRET_KEY": secret_key,  # Keep both conventions
            "LANGFUSE_HOST": self.env_data.get("LANGFUSE_HOST", "http://langfuse-web:3000"),
            "LANGFUSE_BASE_URL": self.env_data.get("LANGFUSE_BASE_URL", "http://langfuse-web:3000"),
            "LANGFUSE_SALT": self.env_data.get("LANGFUSE_SALT", "changeme_32_char_minimum_salt"),
            "LANGFUSE_ENCRYPTION_KEY": self.env_data.get("LANGFUSE_ENCRYPTION_KEY", "0" * 64),
            "LANGFUSE_ENABLED": self.env_data.get("LANGFUSE_ENABLED", "true"),
            # Add OTEL configuration
            "OTEL_EXPORTER_OTLP_ENDPOINT": self.env_data.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://langfuse-web:3000"),
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": self.env_data.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://langfuse-web:3000/v1/traces"),
            "OTEL_EXPORTER_OTLP_PROTOCOL": self.env_data.get("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf"),
            "OTEL_EXPORTER_OTLP_COMPRESSION": self.env_data.get("OTEL_EXPORTER_OTLP_COMPRESSION", "gzip"),
            "LANGFUSE_BASEURL_OTEL": self.env_data.get("LANGFUSE_BASEURL_OTEL", "http://langfuse-web:3000")
        }

        # Update existing lines or add new ones
        updated = set()
        new_lines = []
        for line in lines:
            wrote_line = False
            for key, value in langfuse_vars.items():
                if line.startswith(f"{key}="):
                    new_lines.append(f"{key}={value}\n")
                    updated.add(key)
                    wrote_line = True
                    break
            if not wrote_line:
                new_lines.append(line)

        # Add any missing variables
        for key, value in langfuse_vars.items():
            if key not in updated and value:
                new_lines.append(f"{key}={value}\n")

        # Write back
        with open(self.env_file, 'w') as f:
            f.writelines(new_lines)

    def get_db_connection(self) -> Optional[Any]:
        """Get database connection."""
        if not PSYCOPG2_AVAILABLE:
            return None

        try:
            conn = psycopg2.connect(
                host=os.getenv("LANGFUSE_DB_HOST", "langfuse-postgres"),
                port=int(os.getenv("LANGFUSE_DB_PORT", "5432")),
                database="langfuse",
                user="langfuse",
                password=os.getenv("LANGFUSE_POSTGRES_PASSWORD", "langfuse_secure_password")
            )
            return conn
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            return None

    def generate_credentials(self) -> Tuple[str, str]:
        """Generate new Langfuse API key pair."""
        public_key = f"pk-lf-{secrets.token_hex(16)}"
        secret_key = f"sk-lf-{secrets.token_hex(32)}"
        return public_key, secret_key

    def hash_secret_key(self, secret_key: str, salt: str) -> str:
        """Hash secret key with salt matching LangFuse's createShaHash algorithm.

        Implements the same algorithm as LangFuse's createShaHash in apiKeys.ts:
        hash = SHA256(secret_key + SHA256(salt))
        """
        # Step 1: Create hasher and update with secret key
        hasher = hashlib.sha256()
        hasher.update(secret_key.encode())

        # Step 2: Compute SHA-256 of salt and add to hasher
        salt_hash = hashlib.sha256(salt.encode('utf-8')).hexdigest()
        hasher.update(salt_hash.encode())

        # Step 3: Return final hex digest
        return hasher.hexdigest()

    # Command implementations

    def cmd_list(self, args) -> int:
        """List current credential status."""
        print("\n📋 Langfuse Credentials Status")
        print("=" * 60)

        # Environment credentials
        print("\n🔧 Environment (.env):")
        env_creds = {
            "LANGFUSE_PUBLIC_KEY": self.env_data.get("LANGFUSE_PUBLIC_KEY"),
            "LANGFUSE_SECRET_KEY": self.env_data.get("LANGFUSE_SECRET_KEY"),
            "LANGFUSE_HOST": self.env_data.get("LANGFUSE_HOST"),
            "LANGFUSE_SALT": self.env_data.get("LANGFUSE_SALT"),
            "LANGFUSE_ENABLED": self.env_data.get("LANGFUSE_ENABLED")
        }

        for key, value in env_creds.items():
            if value:
                # Truncate secret keys for display
                if "SECRET" in key:
                    display_value = f"{value[:15]}..." if len(value) > 15 else value
                else:
                    display_value = value
                print(f"   {key}: {display_value}")
            else:
                print(f"   {key}: ❌ Not set")

        # Database credentials
        print("\n🗄️ Database (api_keys table):")
        conn = self.get_db_connection()
        if conn:
            try:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute("""
                    SELECT ak.public_key, ak.project_id, p.name as project_name
                    FROM api_keys ak
                    LEFT JOIN projects p ON ak.project_id = p.id
                """)
                results = cursor.fetchall()

                if results:
                    for row in results:
                        print(f"   public_key: {row['public_key']}")
                        print(f"   project_id: {row['project_id']}")
                        print(f"   project_name: {row['project_name'] or 'N/A'}")
                else:
                    print("   ❌ No API keys found in database")

                cursor.close()
            except Exception as e:
                print(f"   ❌ Error querying database: {e}")
            finally:
                conn.close()
        else:
            print("   ⚠️  Cannot connect to database")

        return 0

    def cmd_validate(self, args) -> int:
        """Validate credential consistency."""
        print("\n✅ Validating Langfuse Credentials")
        print("=" * 60)

        issues = []

        # Check environment variables
        print("\n🔧 Checking environment variables...")
        required_env = ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_SALT"]
        for key in required_env:
            if key in self.env_data:
                print(f"   ✅ {key} is set")
            else:
                print(f"   ❌ {key} is missing")
                issues.append(f"Missing {key}")


        # Check database
        print("\n🗄️ Checking database...")
        conn = self.get_db_connection()
        if conn:
            try:
                cursor = conn.cursor(cursor_factory=RealDictCursor)

                # Check for API keys
                cursor.execute("SELECT COUNT(*) as count FROM api_keys")
                count = cursor.fetchone()['count']
                if count > 0:
                    print(f"   ✅ Found {count} API key(s) in database")

                    # Check if our key is there (support both naming conventions)
                    public_key = (
                        self.env_data.get("LANGFUSE_INIT_PROJECT_PUBLIC_KEY") or
                        self.env_data.get("LANGFUSE_PUBLIC_KEY")
                    )
                    if public_key:
                        cursor.execute(
                            "SELECT * FROM api_keys WHERE public_key = %s",
                            (public_key,)
                        )
                        if cursor.fetchone():
                            print(f"   ✅ Current public key found in database")
                        else:
                            print(f"   ❌ Current public key NOT in database")
                            issues.append("API key not in database")
                else:
                    print("   ❌ No API keys in database")
                    issues.append("No API keys in database")

                cursor.close()
            except Exception as e:
                print(f"   ❌ Database error: {e}")
                issues.append(f"Database error: {e}")
            finally:
                conn.close()
        else:
            print("   ⚠️  Cannot validate database")

        # Test trace creation
        print("\n📊 Testing trace creation...")
        if LANGFUSE_AVAILABLE:
            try:
                langfuse = Langfuse(
                    public_key=self.env_data.get("LANGFUSE_PUBLIC_KEY"),
                    secret_key=self.env_data.get("LANGFUSE_SECRET_KEY"),
                    host=self.env_data.get("LANGFUSE_HOST", "http://langfuse-web:3000")
                )

                @observe(name="validation_test")
                def test_trace():
                    return "Validation successful"

                result = test_trace()
                langfuse.flush()
                print("   ✅ Test trace created successfully")
            except Exception as e:
                print(f"   ❌ Failed to create trace: {e}")
                if "401" in str(e):
                    issues.append("Authentication failed (401)")
        else:
            print("   ⚠️  Langfuse SDK not available")

        # Summary
        print("\n" + "=" * 60)
        if issues:
            print("❌ Validation FAILED with issues:")
            for issue in issues:
                print(f"   - {issue}")
            return 1
        else:
            print("✅ Validation PASSED - credentials are properly configured")
            return 0

    def cmd_regenerate(self, args) -> int:
        """Generate new credentials."""
        print("\n🔑 Regenerating Langfuse Credentials")
        print("=" * 60)

        if not args.force:
            response = input("\n⚠️  This will replace existing credentials. Continue? (y/N): ")
            if response.lower() != 'y':
                print("Cancelled.")
                return 1

        # Generate new credentials
        public_key, secret_key = self.generate_credentials()
        print(f"\n✅ Generated new credentials:")
        print(f"   Public Key: {public_key}")
        print(f"   Secret Key: {secret_key[:15]}...")

        # Update environment - Update BOTH naming conventions to ensure save_environment() writes new values
        self.env_data["LANGFUSE_PUBLIC_KEY"] = public_key
        self.env_data["LANGFUSE_SECRET_KEY"] = secret_key
        self.env_data["LANGFUSE_INIT_PROJECT_PUBLIC_KEY"] = public_key
        self.env_data["LANGFUSE_INIT_PROJECT_SECRET_KEY"] = secret_key

        # Save to file
        self.save_environment()
        print("\n✅ Updated .env file")

        # Insert into database if requested
        if args.insert:
            print("\n🗄️ Inserting into database...")
            return self.insert_credentials_to_db(public_key, secret_key)

        print("\n⚠️  Remember to:")
        print("   1. Insert credentials into database: python manage_langfuse_credentials.py insert")
        print("   2. Restart services: make restart")

        return 0

    def insert_credentials_to_db(self, public_key: str, secret_key: str) -> int:
        """Insert credentials into database."""
        conn = self.get_db_connection()
        if not conn:
            print("   ❌ Cannot connect to database")
            return 1

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # Get or create project
            cursor.execute("SELECT id FROM projects LIMIT 1")
            project = cursor.fetchone()

            if not project:
                # Create project if none exists
                project_id = secrets.token_hex(16)
                cursor.execute("""
                    INSERT INTO projects (id, name, org_id, created_at, updated_at)
                    VALUES (%s, %s, (SELECT id FROM organizations LIMIT 1), %s, %s)
                    RETURNING id
                """, (project_id, "ADEPT-Default", datetime.utcnow(), datetime.utcnow()))
                project = cursor.fetchone()

            project_id = project['id']

            # Hash the secret key
            salt = self.env_data.get("LANGFUSE_SALT", "changeme_32_char_minimum_salt")
            hashed_secret = self.hash_secret_key(secret_key, salt)

            # Insert API key
            api_key_id = secrets.token_hex(16)
            cursor.execute("""
                INSERT INTO api_keys (
                    id, project_id, public_key,
                    hashed_secret_key, display_secret_key,
                    fast_hashed_secret_key, note,
                    created_at, scope
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (public_key) DO UPDATE SET
                    hashed_secret_key = EXCLUDED.hashed_secret_key,
                    fast_hashed_secret_key = EXCLUDED.fast_hashed_secret_key
                RETURNING id
            """, (
                api_key_id, project_id, public_key,
                hashed_secret, f"{secret_key[:8]}...",
                hashed_secret, "Managed by manage_langfuse_credentials.py",
                datetime.utcnow(), "PROJECT"
            ))

            conn.commit()
            print(f"   ✅ Inserted API key into database")
            return 0

        except Exception as e:
            conn.rollback()
            print(f"   ❌ Failed to insert: {e}")
            return 1
        finally:
            cursor.close()
            conn.close()

    def cmd_insert(self, args) -> int:
        """Insert current credentials into database."""
        print("\n🗄️ Inserting Credentials into Database")
        print("=" * 60)

        # Support both naming conventions
        public_key = (
            self.env_data.get("LANGFUSE_INIT_PROJECT_PUBLIC_KEY") or
            self.env_data.get("LANGFUSE_PUBLIC_KEY")
        )
        secret_key = (
            self.env_data.get("LANGFUSE_INIT_PROJECT_SECRET_KEY") or
            self.env_data.get("LANGFUSE_SECRET_KEY")
        )

        if not public_key or not secret_key:
            print("❌ No credentials found in .env file")
            print("   Run: python manage_langfuse_credentials.py regenerate")
            return 1

        print(f"📍 Public Key: {public_key}")
        print(f"🔑 Secret Key: {secret_key[:15]}...")

        return self.insert_credentials_to_db(public_key, secret_key)

    def cmd_delete(self, args) -> int:
        """Delete credentials from database."""
        print("\n🗑️ Deleting Credentials from Database")
        print("=" * 60)

        if not args.confirm:
            response = input("\n⚠️  This will delete ALL API keys. Continue? (y/N): ")
            if response.lower() != 'y':
                print("Cancelled.")
                return 1

        conn = self.get_db_connection()
        if not conn:
            print("❌ Cannot connect to database")
            return 1

        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM api_keys")
            count = cursor.rowcount
            conn.commit()
            print(f"✅ Deleted {count} API key(s)")
            return 0
        except Exception as e:
            conn.rollback()
            print(f"❌ Failed to delete: {e}")
            return 1
        finally:
            cursor.close()
            conn.close()

    def cmd_diagnose(self, args) -> int:
        """Run comprehensive diagnostics."""
        print("\n🔍 Langfuse Diagnostics Report")
        print("=" * 60)

        # Environment variables
        print("\n📋 Environment Variables:")
        env_checks = [
            ("LANGFUSE_HOST", "Service URL"),
            ("LANGFUSE_PUBLIC_KEY", "Public API key"),
            ("LANGFUSE_SECRET_KEY", "Secret API key"),
            ("LANGFUSE_SALT", "Salt for hashing"),
            ("LANGFUSE_ENCRYPTION_KEY", "Encryption key"),
            ("LANGFUSE_ENABLED", "Tracing enabled")
        ]

        for key, desc in env_checks:
            value = self.env_data.get(key) or os.getenv(key)
            if value:
                if "SECRET" in key or "KEY" in key:
                    status = f"✅ Set ({len(value)} chars)"
                else:
                    status = f"✅ {value}"
            else:
                status = "❌ Not set"
            print(f"   {key:30} {status}")

        # Database connection
        print("\n🗄️ Database Connection:")
        conn = self.get_db_connection()
        if conn:
            try:
                cursor = conn.cursor(cursor_factory=RealDictCursor)

                # Check tables
                tables_to_check = ["users", "api_keys", "projects", "organizations", "traces"]
                for table in tables_to_check:
                    try:
                        cursor.execute(f"SELECT COUNT(*) as count FROM {table}")
                        count = cursor.fetchone()['count']
                        print(f"   {table:20} ✅ {count} record(s)")
                    except:
                        print(f"   {table:20} ❌ Table not found")

                cursor.close()
            except Exception as e:
                print(f"   ❌ Database error: {e}")
            finally:
                conn.close()
        else:
            print("   ❌ Cannot connect to database")

        # Service health
        print("\n🏥 Service Health:")
        services = [
            ("langfuse-web", "3000"),
            ("langfuse-worker", None),
            ("langfuse-postgres", "5432"),
            ("langfuse-clickhouse", "8123"),
            ("langfuse-redis", "6379")
        ]

        for service, port in services:
            try:
                # Try to check if container is running
                result = subprocess.run(
                    ["docker", "ps", "--filter", f"name={service}", "--format", "{{.Status}}"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.stdout.strip():
                    print(f"   {service:20} ✅ {result.stdout.strip()}")
                else:
                    print(f"   {service:20} ❌ Not running")
            except:
                print(f"   {service:20} ⚠️  Cannot check")

        # Trace export test
        print("\n📊 Trace Export Test:")
        if LANGFUSE_AVAILABLE:
            try:
                langfuse = Langfuse(
                    public_key=self.env_data.get("LANGFUSE_PUBLIC_KEY"),
                    secret_key=self.env_data.get("LANGFUSE_SECRET_KEY"),
                    host=self.env_data.get("LANGFUSE_HOST", "http://langfuse-web:3000"),
                    enabled=True,
                    debug=args.verbose
                )
                print("   Client initialization: ✅ Success")

                @observe(name="diagnostic_test")
                def test_trace():
                    return "Diagnostic test"

                test_trace()
                print("   Trace creation: ✅ Success")

                langfuse.flush()
                print("   OTLP export: ✅ Success")

            except Exception as e:
                print(f"   ❌ Test failed: {e}")
                if "401" in str(e):
                    print("\n   💡 Authentication issue detected!")
                    print("      Try: python manage_langfuse_credentials.py insert")
                    print("      Or: make langfuse-fix-auth")
        else:
            print("   ⚠️  Langfuse SDK not available")

        print("\n" + "=" * 60)
        print("📍 Next Steps:")
        print("   1. Fix any ❌ issues above")
        print("   2. Run: python manage_langfuse_credentials.py validate")
        print("   3. If auth fails: make langfuse-fix-auth")

        return 0


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Manage Langfuse credentials",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s list                    # Show current credentials
  %(prog)s validate                # Check credential consistency
  %(prog)s regenerate --insert     # Generate new credentials and insert
  %(prog)s insert                  # Insert current credentials to database
  %(prog)s delete --confirm        # Delete all API keys from database
  %(prog)s diagnose --verbose      # Run detailed diagnostics
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # List command
    subparsers.add_parser('list', help='Show current credential status')

    # Validate command
    subparsers.add_parser('validate', help='Check credential consistency')

    # Regenerate command
    regen_parser = subparsers.add_parser('regenerate', help='Generate new credentials')
    regen_parser.add_argument('--force', action='store_true', help='Skip confirmation')
    regen_parser.add_argument('--insert', action='store_true', help='Also insert into database')

    # Insert command
    subparsers.add_parser('insert', help='Insert credentials into database')

    # Delete command
    del_parser = subparsers.add_parser('delete', help='Remove credentials from database')
    del_parser.add_argument('--confirm', action='store_true', help='Skip confirmation')

    # Diagnose command
    diag_parser = subparsers.add_parser('diagnose', help='Run diagnostics')
    diag_parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Create manager and run command
    manager = LangfuseCredentialsManager()
    command_method = getattr(manager, f"cmd_{args.command}", None)

    if command_method:
        return command_method(args)
    else:
        print(f"Unknown command: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())