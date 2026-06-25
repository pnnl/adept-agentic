#!/usr/bin/env python3
"""
Checkpoint Schema Management CLI Tool

Command-line interface for managing LangGraph checkpoint schema migrations.

This tool provides idempotent schema management for LangGraph 1.0.5 checkpoints:
- Detects current schema state (MISSING, OLD, CURRENT, DRIFT)
- Migrates old schemas to new (automatic or dry-run mode)
- Validates schema against ORM definitions
- Creates backups before destructive operations

Integration:
- Quick-start script: Called automatically before service startup
- Manual usage: Run directly for troubleshooting or manual migration
- CI/CD: Validate schema in deployment pipelines

Usage:
    # Auto-migrate with backup (recommended for quick-start)
    python scripts/deps/manage_checkpoint_schema.py --auto-migrate --backup

    # Dry-run (detect only, no changes)
    python scripts/deps/manage_checkpoint_schema.py --dry-run

    # Validate schema only
    python scripts/deps/manage_checkpoint_schema.py --validate

    # Force DROP/CREATE migration
    python scripts/deps/manage_checkpoint_schema.py --auto-migrate --strategy drop_create

Examples:
    # Quick-start integration (auto-fixes schema issues)
    ./scripts/quick-start-adept-and-subsystems.sh
    # Internally calls: python scripts/deps/manage_checkpoint_schema.py --auto-migrate --backup

    # Manual troubleshooting
    python scripts/deps/manage_checkpoint_schema.py --dry-run
    # Output: Schema state: OLD (LangGraph 0.0.8 detected)

    # Manual migration with backup
    python scripts/deps/manage_checkpoint_schema.py --auto-migrate --backup --strategy drop_create
    # Output: Migration successful: Migrated from 0.0.8 to 1.0.5 (DROP/CREATE)
"""

import os
import sys
import argparse
import asyncio
from pathlib import Path

# Add src to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))

from agentic_framework_pkg.orchestration_service.persistence.schema_migrator import (
    CheckpointSchemaMigrator,
    SchemaState,
    MigrationStrategy,
)


def print_banner(title: str):
    """Print formatted banner."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70 + "\n")


def print_schema_state(detection):
    """Print detailed schema state information."""
    state_emoji = {
        SchemaState.MISSING: "ℹ️ ",
        SchemaState.OLD: "⚠️ ",
        SchemaState.CURRENT: "✅",
        SchemaState.DRIFT: "❌",
    }

    emoji = state_emoji.get(detection.state, "❓")
    print(f"{emoji} Schema State: {detection.state.value.upper()}")
    print(f"   Table Exists: {detection.table_exists}")

    if detection.table_exists:
        print(f"   Column Count: {detection.column_count}")
        print(f"   Columns: {list(detection.columns.keys())}")
        print(f"   Primary Key: {detection.primary_key}")
        print(f"   Indexes: {detection.indexes}")

        if detection.state == SchemaState.DRIFT:
            print(f"\n❌ Drift Details: {detection.drift_details}")
            print("   Manual investigation required!")

        if detection.state == SchemaState.OLD:
            print("\n⚠️  Old LangGraph 0.0.8 Schema Detected:")
            print("   - 3-5 columns (thread_id, checkpoint, metadata, created_at, updated_at)")
            print("   - BYTEA types for checkpoint and metadata")
            print("   - Single primary key (thread_id)")
            print("\n   Migration needed to LangGraph 1.0.5:")
            print("   - 7 columns (add checkpoint_ns, checkpoint_id, parent_checkpoint_id, type)")
            print("   - JSONB types (more efficient querying)")
            print("   - Composite primary key (thread_id, checkpoint_ns, checkpoint_id)")

        if detection.state == SchemaState.CURRENT:
            print("\n✅ LangGraph 1.0.5 Schema Up to Date:")
            print("   - 7 columns with correct types")
            print("   - JSONB types for checkpoint and metadata")
            print("   - Composite primary key (thread_id, checkpoint_ns, checkpoint_id)")


async def main():
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Manage LangGraph checkpoint schema migrations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Detect schema state (no changes)
  python scripts/deps/manage_checkpoint_schema.py --dry-run

  # Auto-migrate with backup (recommended)
  python scripts/deps/manage_checkpoint_schema.py --auto-migrate --backup

  # Validate schema only
  python scripts/deps/manage_checkpoint_schema.py --validate

  # Force DROP/CREATE migration
  python scripts/deps/manage_checkpoint_schema.py --auto-migrate --strategy drop_create

Quick-Start Integration:
  The quick-start script calls this tool automatically:
  ./scripts/quick-start-adept-and-subsystems.sh

Exit Codes:
  0: Success (schema current or migration succeeded)
  1: Schema drift detected or migration failed
  2: Validation failed (schema doesn't match ORM)
        """,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Detect schema state only (no migration)",
    )

    parser.add_argument(
        "--auto-migrate",
        action="store_true",
        help="Automatically migrate if schema is OLD or MISSING",
    )

    parser.add_argument(
        "--backup",
        action="store_true",
        help="Create database backup before migration (recommended)",
    )

    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate schema matches ORM (exit 0=match, 2=mismatch)",
    )

    parser.add_argument(
        "--strategy",
        choices=["drop_create", "alter_table"],
        default="drop_create",
        help="Migration strategy (default: drop_create for ephemeral checkpoints)",
    )

    parser.add_argument(
        "--database-url",
        type=str,
        help="PostgreSQL connection URL (default: from DATABASE_URL env var)",
    )

    args = parser.parse_args()

    # Ensure at least one mode is specified
    if not (args.dry_run or args.auto_migrate or args.validate):
        parser.error("Must specify one of: --dry-run, --auto-migrate, or --validate")

    # Create migrator
    migrator = CheckpointSchemaMigrator(database_url=args.database_url)

    try:
        if args.dry_run:
            print_banner("Checkpoint Schema Detection (Dry Run)")
            detection = await migrator.detect_schema_state()
            print_schema_state(detection)

            if detection.state != SchemaState.CURRENT:
                print("\n💡 To fix schema issues, run:")
                print("   python scripts/deps/manage_checkpoint_schema.py --auto-migrate --backup")

            sys.exit(0 if detection.state == SchemaState.CURRENT else 1)

        if args.validate:
            print_banner("Checkpoint Schema Validation")
            detection = await migrator.detect_schema_state()
            print_schema_state(detection)

            is_valid = await migrator.validate_schema_matches_orm()

            if is_valid:
                print("\n✅ Schema validation passed!")
                sys.exit(0)
            else:
                print("\n❌ Schema validation failed!")
                print("   Schema does not match ORM definitions")
                sys.exit(2)

        if args.auto_migrate:
            print_banner("Checkpoint Schema Auto-Migration")

            # Detect current state
            detection = await migrator.detect_schema_state()
            print("Current State:")
            print_schema_state(detection)

            if detection.state == SchemaState.CURRENT:
                print("\n✅ Schema already up to date - no migration needed")
                sys.exit(0)

            if detection.state == SchemaState.DRIFT:
                print("\n❌ Cannot auto-migrate with schema drift")
                print("   Manual investigation required")
                sys.exit(1)

            # Determine strategy
            strategy = (
                MigrationStrategy.DROP_CREATE
                if args.strategy == "drop_create"
                else MigrationStrategy.ALTER_TABLE
            )

            print(f"\n📦 Starting migration with strategy: {strategy.value}")
            print(f"   Backup enabled: {args.backup}")

            # Execute migration
            result = await migrator.migrate_to_current(
                backup=args.backup,
                strategy=strategy,
            )

            print(f"\n{'✅' if result.status == 'success' else '❌'} Migration Result:")
            print(f"   Status: {result.status}")
            print(f"   Strategy: {result.strategy.value}")
            print(f"   Duration: {result.duration_seconds:.2f}s")
            print(f"   Message: {result.message}")

            if result.backup_file:
                print(f"   Backup: {result.backup_file}")

            if result.error:
                print(f"\n❌ Error: {result.error}")
                if result.backup_file:
                    print(f"\n⚠️  Restore from backup:")
                    print(f"   docker exec -i postgres psql -U admin -d agentic_orchestrator < {result.backup_file}")
                sys.exit(1)

            # Verify migration
            print("\n🔍 Verifying migration...")
            verification = await migrator.detect_schema_state()

            if verification.state == SchemaState.CURRENT:
                print("✅ Migration verified successfully!")
                print_schema_state(verification)
                sys.exit(0)
            else:
                print("❌ Migration verification failed!")
                print_schema_state(verification)
                sys.exit(1)

    except Exception as e:
        print(f"\n❌ Fatal error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    finally:
        migrator.close()


if __name__ == "__main__":
    asyncio.run(main())
