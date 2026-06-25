#!/bin/bash
# Langfuse CLI Docker Wrapper
# Executes Langfuse management scripts in a containerized environment with proper networking

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
DOCKER_IMAGE="agentic-framework-deps-base"
DOCKER_NETWORK="agentic_framework_network"
WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Function to print colored output
print_color() {
    local color=$1
    shift
    echo -e "${color}$@${NC}"
}

# Function to run Python script in container
run_langfuse_script() {
    local script_name=$1
    shift
    local args="$@"

    print_color "$YELLOW" "🐳 Running $script_name in Docker container..."

    docker run --rm \
        --network "$DOCKER_NETWORK" \
        -v "$WORKSPACE_DIR":/workspace \
        -w /workspace \
        -e LANGFUSE_DB_HOST=langfuse-postgres \
        -e LANGFUSE_POSTGRES_PASSWORD=langfuse_secure_password \
        --user root \
        "$DOCKER_IMAGE" \
        /bin/bash -c "pip install -q psycopg2-binary langfuse && python3 /workspace/scripts/langfuse/$script_name $args"
}

# Main command dispatcher
case "${1:-help}" in
    # Credential Management Commands
    list)
        run_langfuse_script "manage_langfuse_credentials.py" "list"
        ;;

    validate)
        run_langfuse_script "manage_langfuse_credentials.py" "validate"
        ;;

    regenerate)
        shift
        run_langfuse_script "manage_langfuse_credentials.py" "regenerate" "$@"
        ;;

    insert)
        run_langfuse_script "manage_langfuse_credentials.py" "insert"
        ;;

    delete)
        shift
        run_langfuse_script "manage_langfuse_credentials.py" "delete" "$@"
        ;;

    diagnose)
        shift
        run_langfuse_script "manage_langfuse_credentials.py" "diagnose" "$@"
        ;;

    # Testing Commands
    test)
        shift
        # Test in orchestration_service container which already has Langfuse
        print_color "$YELLOW" "🧪 Testing Langfuse in orchestration_service container..."
        docker cp "$WORKSPACE_DIR/scripts/langfuse/test_langfuse_in_container.py" orchestration_service:/tmp/test_langfuse.py
        if docker exec orchestration_service python3 /tmp/test_langfuse.py; then
            print_color "$GREEN" "✅ Langfuse test passed!"
        else
            print_color "$RED" "❌ Langfuse test failed"
            exit 1
        fi
        ;;

    test-standalone)
        shift
        # Original test using standalone container with deps installation
        run_langfuse_script "test_langfuse_telemetry.py" "$@"
        ;;

    # Bootstrap Commands
    bootstrap)
        print_color "$GREEN" "🔑 Bootstrapping Langfuse credentials..."
        run_langfuse_script "bootstrap_langfuse_credentials.py"
        ;;

    init-headless)
        print_color "$GREEN" "🚀 Running headless Langfuse initialization..."
        run_langfuse_script "headless_init_langfuse.py"
        ;;

    # Complete Fix Workflow
    fix-auth)
        print_color "$YELLOW" "🔧 Running complete Langfuse authentication fix..."

        # Step 1: Clear existing users
        print_color "$YELLOW" "Step 1: Clearing existing users..."
        docker exec langfuse-postgres psql -U langfuse -d langfuse -c "DELETE FROM users;" || true

        # Step 2: Delete existing API keys
        print_color "$YELLOW" "Step 2: Clearing existing API keys..."
        docker exec langfuse-postgres psql -U langfuse -d langfuse -c "DELETE FROM api_keys;" || true

        # Step 3: Run headless init (will create user)
        print_color "$YELLOW" "Step 3: Running headless initialization..."
        run_langfuse_script "headless_init_langfuse.py"

        # Step 4: Insert API keys from .env
        print_color "$YELLOW" "Step 4: Inserting API keys from .env..."
        run_langfuse_script "manage_langfuse_credentials.py" "insert"

        # Step 5: Restart services
        print_color "$YELLOW" "Step 5: Restarting services..."
        docker compose -f "$WORKSPACE_DIR/deployment/local/docker-compose/docker-compose.langfuse.yaml" restart
        docker compose -f "$WORKSPACE_DIR/deployment/local/docker-compose/docker-compose.core.yaml" restart orchestration_service

        # Step 6: Wait for services
        print_color "$YELLOW" "Step 6: Waiting for services to stabilize..."
        sleep 10

        # Step 7: Validate
        print_color "$YELLOW" "Step 7: Running validation..."
        run_langfuse_script "test_langfuse_telemetry.py"

        print_color "$GREEN" "✅ Langfuse authentication fix complete!"
        ;;

    # Quick Database Queries
    check-db)
        print_color "$YELLOW" "📊 Checking Langfuse database..."
        echo "API Keys:"
        docker exec langfuse-postgres psql -U langfuse -d langfuse -c "SELECT public_key, project_id FROM api_keys;"
        echo ""
        echo "Users:"
        docker exec langfuse-postgres psql -U langfuse -d langfuse -c "SELECT email, name FROM users;"
        echo ""
        echo "Projects:"
        docker exec langfuse-postgres psql -U langfuse -d langfuse -c "SELECT id, name FROM projects;"
        ;;

    # Help
    help|--help|-h)
        cat << EOF
Langfuse CLI - Docker-based Management Tool
============================================

Usage: $0 <command> [options]

Credential Management:
  list                    Show current credential status
  validate                Check credential consistency
  regenerate [--force]    Generate new credentials
  insert                  Insert credentials into database
  delete [--confirm]      Remove credentials from database
  diagnose [-v]          Run comprehensive diagnostics

Testing:
  test                   Test Langfuse in orchestration container
  test-standalone [-v]   Test with standalone container (installs deps)

Bootstrap & Init:
  bootstrap              Generate new Langfuse credentials
  init-headless         Run headless initialization
  fix-auth              Complete fix for authentication issues

Database:
  check-db              Quick database status check

Options:
  -v, --verbose         Enable verbose output
  --force              Skip confirmation prompts
  --confirm            Auto-confirm dangerous operations

Examples:
  $0 list               # Show current credentials
  $0 validate           # Check if everything is configured
  $0 fix-auth          # Fix 401 authentication errors
  $0 test -v           # Test with verbose output
  $0 diagnose          # Run full diagnostics

Environment:
  This script runs Python scripts in the $DOCKER_IMAGE container
  with network connectivity to Langfuse PostgreSQL database.

EOF
        ;;

    *)
        print_color "$RED" "Unknown command: $1"
        echo "Run '$0 help' for usage information"
        exit 1
        ;;
esac