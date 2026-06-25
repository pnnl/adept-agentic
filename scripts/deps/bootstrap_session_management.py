#!/usr/bin/env python3
"""
Session 32 Phase 1 - Bootstrap Session Management Schema

Purpose: Apply consolidated session management schema to fresh deployments
         or skip if schema already applied to existing deployments

Auto-Detection:
- Checks if schema_migrations table exists
- Checks if migration 004_add_tool_outputs_unique_constraint is recorded
- If yes: Skip with info message and exit 0
- If no: Apply consolidated_initial_schema.sql and exit with status

Usage:
  python bootstrap_session_management.py

Exit Codes:
  0 - Success (schema applied or already exists)
  1 - Error (schema application failed)
"""

import logging
import os
import sys
from pathlib import Path

import psycopg

# Configuration
POSTGRES_USER = os.getenv("POSTGRES_USER", "admin")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "password")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_DB = "agentic_orchestrator"

# Path to consolidated schema (relative to app root in container)
SCHEMA_FILE = Path("/app/src/agentic_framework_pkg/orchestration_service/persistence/migrations/consolidated_initial_schema.sql")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


def get_db_connection():
    """Create PostgreSQL database connection."""
    try:
        conn = psycopg.connect(
            host=POSTGRES_HOST,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            dbname=POSTGRES_DB,
            autocommit=True
        )
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to PostgreSQL: {e}")
        raise


def check_migrations_table_exists(conn):
    """Check if schema_migrations table exists."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'schema_migrations'
                )
            """)
            result = cur.fetchone()
            return result[0] if result else False
    except Exception as e:
        logger.error(f"Error checking schema_migrations table: {e}")
        return False


def check_migration_004_exists(conn):
    """Check if migration 004 is recorded in schema_migrations."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM schema_migrations
                    WHERE migration_id = '004_add_tool_outputs_unique_constraint'
                )
            """)
            result = cur.fetchone()
            return result[0] if result else False
    except Exception as e:
        logger.error(f"Error checking migration 004: {e}")
        return False


def apply_schema(conn):
    """Apply consolidated session management schema from SQL file."""
    logger.info("Applying consolidated session management schema...")
    logger.info(f"Schema file: {SCHEMA_FILE}")

    if not SCHEMA_FILE.exists():
        logger.error(f"Schema file not found: {SCHEMA_FILE}")
        return False

    try:
        # Read SQL file
        with open(SCHEMA_FILE, 'r') as f:
            sql_content = f.read()

        # Execute SQL
        with conn.cursor() as cur:
            cur.execute(sql_content)

        logger.info("Schema application completed successfully")
        return True

    except Exception as e:
        logger.error(f"Failed to apply schema: {e}")
        return False


def main():
    """Main execution."""
    logger.info("==========================================")
    logger.info("Session 32 Phase 1 Schema Bootstrap")
    logger.info("==========================================")
    logger.info(f"Target: {POSTGRES_HOST}/{POSTGRES_DB}")
    logger.info(f"User: {POSTGRES_USER}")

    try:
        # Connect to database
        conn = get_db_connection()

        # Check if migrations table exists
        logger.info("Checking if schema_migrations table exists...")
        table_exists = check_migrations_table_exists(conn)

        if table_exists:
            logger.info("schema_migrations table exists")

            # Check if migration 004 is recorded
            logger.info("Checking if migration 004 is recorded...")
            migration_004_exists = check_migration_004_exists(conn)

            if migration_004_exists:
                logger.info("==========================================")
                logger.info("Session 32 Phase 1 schema already applied")
                logger.info("Migration 004 found in schema_migrations")
                logger.info("Skipping schema application")
                logger.info("==========================================")
                conn.close()
                return 0
            else:
                logger.warning("schema_migrations table exists but migration 004 not found")
                logger.warning("This may indicate incomplete migration application")
                logger.info("Proceeding with schema application...")
        else:
            logger.info("schema_migrations table does not exist")
            logger.info("This appears to be a fresh deployment")

        # Apply consolidated schema
        if apply_schema(conn):
            logger.info("==========================================")
            logger.info("Session 32 Phase 1 schema applied successfully")
            logger.info("==========================================")

            # Verify schema application
            logger.info("Verifying schema application...")
            migration_004_exists = check_migration_004_exists(conn)

            if migration_004_exists:
                logger.info("Verification successful: Migration 004 recorded")
                conn.close()
                return 0
            else:
                logger.error("Verification failed: Migration 004 not found after application")
                conn.close()
                return 1
        else:
            logger.error("==========================================")
            logger.error("Failed to apply Session 32 Phase 1 schema")
            logger.error("==========================================")
            conn.close()
            return 1

    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
