# Alembic Database Migrations

This directory contains Alembic database migration scripts for the ADEPT orchestration service.

## Location Rationale

Alembic is placed in `scripts/migrations/` (not at project root) because:
- It's infrastructure tooling, not business logic
- Consolidates all migration tooling in one location
- `scripts/migrations/` already exists for SQL migrations
- Keeps project root clean and organized

## Purpose

Alembic provides automated schema migration management with SQLAlchemy ORM models as the single source of truth. This prevents the "three sources of truth" problem (manual SQL migrations, ORM models, raw SQL queries).

## Quick Start

### Initial Setup (First Time)

For existing ADEPT deployments, mark your database as current without applying migrations:

```bash
# Inside orchestration_service container (from /app/scripts/migrations/)
cd /app/scripts/migrations
alembic stamp head
```

This tells Alembic your database is already at the latest schema version.

### Creating New Migrations

When you modify ORM models, generate a migration:

```bash
# From scripts/migrations/ directory
cd /app/scripts/migrations

# Auto-generate migration from ORM model changes
alembic revision --autogenerate -m "Add new column to user_sessions"

# Or create empty migration for manual SQL
alembic revision -m "Add custom index"
```

### Applying Migrations

```bash
# From scripts/migrations/ directory
cd /app/scripts/migrations

# Apply all pending migrations
alembic upgrade head

# Apply one migration at a time
alembic upgrade +1

# Rollback one migration
alembic downgrade -1

# View migration history
alembic history

# Check current database version
alembic current
```

### Dry Run (Generate SQL without applying)

```bash
# From scripts/migrations/ directory
cd /app/scripts/migrations
alembic upgrade head --sql > migration.sql
```

## Directory Structure

```
alembic/
├── versions/           # Migration files (auto-generated or manual)
│   └── 20260110_1400_baseline_existing_schema.py
├── env.py             # Alembic environment configuration
├── script.py.mako     # Template for new migrations
└── README.md          # This file
```

## Migration File Naming

Migration files use timestamp-based naming: `YYYYMMDD_HHMM_slug.py`

Example: `20260110_1400_add_retention_column.py`

## Best Practices

1. **Always Review Auto-Generated Migrations**: `--autogenerate` is smart but not perfect
2. **Test Migrations Locally First**: Apply to dev database before production
3. **Write Reversible Migrations**: Always implement `downgrade()` functions
4. **One Logical Change Per Migration**: Makes rollbacks safer
5. **Run Migrations During Deployment**: Include in CI/CD pipeline

## Integration with ADEPT

### Docker Compose

Migrations can be run automatically on service startup or manually:

```yaml
# docker-compose.core.yaml example
orchestration_service:
  command: >
    bash -c "alembic upgrade head && uvicorn ..."
```

### Makefile Integration (Optional)

```makefile
migrate-database:
	@docker exec orchestration_service bash -c "cd /app/scripts/migrations && alembic upgrade head"

migration-status:
	@docker exec orchestration_service bash -c "cd /app/scripts/migrations && alembic current"
```

## Phase 1 Completed

- ✅ Alembic installed and configured
- ✅ `alembic.ini` created with PostgreSQL connection
- ✅ `env.py` configured to use ORM models
- ✅ Baseline migration created
- ⏳ Backfill migration (Phase 3) - pending

## Common Issues

### Issue: "Target database is not up to date"

**Solution**: Run `alembic stamp head` to mark existing schema as current

### Issue: "Can't locate revision identified by 'xyz'"

**Solution**: Check `alembic_version` table in database, may need to `alembic stamp <revision>`

### Issue: "Multiple head revisions"

**Solution**: Create a merge migration: `alembic merge heads -m "merge"`

## Related Documentation

- Alembic Docs: https://alembic.sqlalchemy.org/
- SQLAlchemy Async: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
- ADEPT ORM Models: `src/agentic_framework_pkg/orchestration_service/models/session_models.py`
