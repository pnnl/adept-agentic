#!/bin/bash
#
# Migration Script: LangGraph 1.0.5 Checkpoints Schema Fix
#
# This script fixes the checkpoint schema mismatch caused by incomplete
# LangGraph 0.0.8 → 1.0.5 upgrade. It performs the following:
#
# 1. Backs up the PostgreSQL database
# 2. Drops old checkpoint-related tables
# 3. Rebuilds the orchestration service container
# 4. Verifies the new 7-column JSONB schema
#
# SAFE TO RUN:
# - Checkpoints table typically has 0 rows (ephemeral state)
# - Full database backup created before any changes
# - Can be re-run if verification fails
#
# Usage:
#   ./scripts/migrations/migrate_langgraph_1.0.5_checkpoints_schema.sh [--non-interactive]
#
# Options:
#   --non-interactive    Skip confirmation prompts (for automation)
#
# Prerequisites:
# - Docker and docker-compose installed
# - Services running (postgres, orchestration_service)
# - Git on branch with commit 026b7f1 or later
#

set -e  # Exit on error

# Parse command line arguments
NON_INTERACTIVE=false
for arg in "$@"; do
    case $arg in
        --non-interactive)
            NON_INTERACTIVE=true
            shift
            ;;
        *)
            ;;
    esac
done

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
POSTGRES_CONTAINER="postgres"
POSTGRES_USER="admin"
POSTGRES_DB="agentic_orchestrator"
ORCHESTRATION_CONTAINER="orchestration_service"
BACKUP_DIR="/tmp/adept_migration_backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check if running from project root
    if [[ ! -f "pyproject.toml" ]]; then
        log_error "Must run from project root directory"
        exit 1
    fi

    # Check if postgres container is running
    if ! docker ps --format '{{.Names}}' | grep -q "^${POSTGRES_CONTAINER}$"; then
        log_error "PostgreSQL container '${POSTGRES_CONTAINER}' is not running"
        exit 1
    fi

    # Check if orchestration service container exists
    if ! docker ps -a --format '{{.Names}}' | grep -q "^${ORCHESTRATION_CONTAINER}$"; then
        log_error "Orchestration service container '${ORCHESTRATION_CONTAINER}' not found"
        exit 1
    fi

    # Check if code fix is present
    if grep -q "CREATE TABLE IF NOT EXISTS checkpoints" \
        src/agentic_framework_pkg/orchestration_service/legacy_persistence.py 2>/dev/null; then
        log_error "Code fix not present in legacy_persistence.py"
        log_error "Please pull latest changes from feature-contextwindow-and-sessionmgmt-integration branch"
        log_error "Required commit: 026b7f1 or later"
        exit 1
    fi

    log_success "Prerequisites check passed"
}

create_backup() {
    log_info "Creating database backup..."

    # Create backup directory
    mkdir -p "${BACKUP_DIR}"

    BACKUP_FILE="${BACKUP_DIR}/agentic_orchestrator_backup_${TIMESTAMP}.sql"

    # Backup database
    if docker exec "${POSTGRES_CONTAINER}" pg_dump -U "${POSTGRES_USER}" "${POSTGRES_DB}" > "${BACKUP_FILE}"; then
        log_success "Database backup created: ${BACKUP_FILE}"

        # Get backup size
        BACKUP_SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
        log_info "Backup size: ${BACKUP_SIZE}"

        # Export old schema for reference
        SCHEMA_FILE="${BACKUP_DIR}/checkpoints_schema_old_${TIMESTAMP}.txt"
        docker exec "${POSTGRES_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
            -c "\d+ checkpoints" > "${SCHEMA_FILE}" 2>&1 || true

        if [[ -f "${SCHEMA_FILE}" ]] && grep -q "checkpoint" "${SCHEMA_FILE}"; then
            log_success "Old schema exported: ${SCHEMA_FILE}"
        fi
    else
        log_error "Failed to create database backup"
        exit 1
    fi
}

check_checkpoint_data() {
    log_info "Checking for data in checkpoints table..."

    ROW_COUNT=$(docker exec "${POSTGRES_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
        -t -c "SELECT COUNT(*) FROM checkpoints;" 2>/dev/null | tr -d ' ' || echo "0")

    if [[ "${ROW_COUNT}" -gt 0 ]]; then
        log_warning "Checkpoints table has ${ROW_COUNT} rows (will be lost)"

        if [[ "${NON_INTERACTIVE}" == "true" ]]; then
            log_info "Running in non-interactive mode, proceeding automatically..."
        else
            read -p "Continue? (yes/no): " CONFIRM
            if [[ "${CONFIRM}" != "yes" ]]; then
                log_info "Migration cancelled by user"
                exit 0
            fi
        fi
    else
        log_success "Checkpoints table has 0 rows (no data loss)"
    fi
}

drop_checkpoint_tables() {
    log_info "Dropping old checkpoint tables..."

    # Drop all checkpoint-related tables
    docker exec "${POSTGRES_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" <<EOF
DROP TABLE IF EXISTS checkpoints CASCADE;
DROP TABLE IF EXISTS checkpoint_migrations CASCADE;
DROP TABLE IF EXISTS checkpoint_blobs CASCADE;
DROP TABLE IF EXISTS checkpoint_writes CASCADE;
EOF

    if [[ $? -eq 0 ]]; then
        log_success "Checkpoint tables dropped successfully"
    else
        log_error "Failed to drop checkpoint tables"
        exit 1
    fi

    # Verify tables are gone
    REMAINING=$(docker exec "${POSTGRES_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
        -t -c "\dt" | grep checkpoint | wc -l)

    if [[ "${REMAINING}" -eq 0 ]]; then
        log_success "Verified: All checkpoint tables removed"
    else
        log_warning "Some checkpoint tables may still exist"
    fi
}

rebuild_orchestration_service() {
    log_info "Rebuilding orchestration service container..."

    # Check if Makefile exists
    if [[ -f "Makefile" ]] && grep -q "rebuild-orchestrator" Makefile; then
        log_info "Using Makefile target: rebuild-orchestrator"
        make rebuild-orchestrator 2>&1 | tail -20
    else
        log_info "Using docker-compose rebuild"
        cd deployment/local/docker-compose
        docker-compose -f docker-compose.base.yaml -f docker-compose.core.yaml \
            build --no-cache orchestration_service
        docker-compose -f docker-compose.base.yaml -f docker-compose.core.yaml \
            up -d orchestration_service
        cd ../../..
    fi

    if [[ $? -eq 0 ]]; then
        log_success "Orchestration service rebuilt successfully"
    else
        log_error "Failed to rebuild orchestration service"
        exit 1
    fi
}

wait_for_service_startup() {
    log_info "Waiting for orchestration service to start..."

    MAX_WAIT=60
    ELAPSED=0

    while [[ ${ELAPSED} -lt ${MAX_WAIT} ]]; do
        if docker logs "${ORCHESTRATION_CONTAINER}" 2>&1 | grep -q "Application startup complete"; then
            log_success "Orchestration service started successfully"
            return 0
        fi

        sleep 2
        ELAPSED=$((ELAPSED + 2))
        echo -n "."
    done

    echo ""
    log_warning "Service startup timed out after ${MAX_WAIT}s (may still be starting)"
}

verify_new_schema() {
    log_info "Verifying new checkpoints schema..."

    # Wait a moment for migrations to complete
    sleep 5

    # Check if checkpoints table exists with correct schema
    SCHEMA_OUTPUT=$(docker exec "${POSTGRES_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
        -c "\d checkpoints" 2>&1)

    if echo "${SCHEMA_OUTPUT}" | grep -q "checkpoint_ns"; then
        log_success "✅ New schema verified: checkpoint_ns column exists"

        # Count columns
        COLUMN_COUNT=$(echo "${SCHEMA_OUTPUT}" | grep -E "^\s+(thread_id|checkpoint_ns|checkpoint_id|parent_checkpoint_id|type|checkpoint|metadata)" | wc -l)

        if [[ ${COLUMN_COUNT} -eq 7 ]]; then
            log_success "✅ Correct column count: 7 columns"
        else
            log_warning "⚠️  Expected 7 columns, found ${COLUMN_COUNT}"
        fi

        # Check JSONB types
        if echo "${SCHEMA_OUTPUT}" | grep -q "jsonb"; then
            log_success "✅ JSONB types detected (not BYTEA)"
        else
            log_warning "⚠️  JSONB types not detected"
        fi

        # Check composite primary key
        if echo "${SCHEMA_OUTPUT}" | grep -q "thread_id, checkpoint_ns, checkpoint_id"; then
            log_success "✅ Composite primary key correct"
        else
            log_warning "⚠️  Primary key may not match expected format"
        fi

        # Show full schema
        log_info "Full schema:"
        echo "${SCHEMA_OUTPUT}"

        return 0
    else
        log_error "❌ checkpoint_ns column not found - migration may have failed"
        log_error "Schema output:"
        echo "${SCHEMA_OUTPUT}"
        return 1
    fi
}

verify_service_health() {
    log_info "Checking service health..."

    HEALTH_CHECK=$(docker exec "${ORCHESTRATION_CONTAINER}" curl -s http://localhost:8084/health 2>&1 || echo "error")

    if echo "${HEALTH_CHECK}" | grep -q '"status":"ok"'; then
        log_success "✅ Service health check passed"
        return 0
    else
        log_warning "⚠️  Service health check failed or unavailable"
        log_info "Health response: ${HEALTH_CHECK}"
        return 1
    fi
}

print_summary() {
    echo ""
    echo "=========================================="
    echo "Migration Summary"
    echo "=========================================="
    echo "Timestamp: ${TIMESTAMP}"
    echo "Backup Location: ${BACKUP_DIR}"
    echo "Backup File: agentic_orchestrator_backup_${TIMESTAMP}.sql"
    echo ""
    echo "Changes Applied:"
    echo "  - Dropped old checkpoints table (3-column BYTEA schema)"
    echo "  - Rebuilt orchestration service container"
    echo "  - LangGraph 1.0.5 created new schema (7-column JSONB)"
    echo ""
    echo "Schema Change:"
    echo "  Old: 3 columns (thread_id, checkpoint, metadata) - BYTEA types"
    echo "  New: 7 columns (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata) - JSONB types"
    echo ""

    if verify_new_schema && verify_service_health; then
        log_success "Migration completed successfully! ✅"
        echo ""
        echo "Next Steps:"
        echo "  1. Test orchestration service functionality"
        echo "  2. Monitor logs for any checkpoint-related errors"
        echo "  3. If issues occur, restore from backup:"
        echo "     docker exec -i ${POSTGRES_CONTAINER} psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < ${BACKUP_DIR}/agentic_orchestrator_backup_${TIMESTAMP}.sql"
    else
        log_error "Migration completed with warnings ⚠️"
        echo ""
        echo "Troubleshooting:"
        echo "  1. Check orchestration service logs:"
        echo "     docker logs ${ORCHESTRATION_CONTAINER} --tail 100"
        echo "  2. Verify database connection:"
        echo "     docker exec ${POSTGRES_CONTAINER} psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} -c '\\dt'"
        echo "  3. If needed, restore from backup:"
        echo "     docker exec -i ${POSTGRES_CONTAINER} psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < ${BACKUP_DIR}/agentic_orchestrator_backup_${TIMESTAMP}.sql"
    fi
}

# Main execution
main() {
    echo "=========================================="
    echo "LangGraph 1.0.5 Checkpoints Schema Migration"
    echo "=========================================="
    echo ""

    check_prerequisites
    echo ""

    create_backup
    echo ""

    check_checkpoint_data
    echo ""

    drop_checkpoint_tables
    echo ""

    rebuild_orchestration_service
    echo ""

    wait_for_service_startup
    echo ""

    print_summary
}

# Run main function
main "$@"
