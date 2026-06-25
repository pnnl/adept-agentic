#!/bin/bash
#
# ADEPT A2A Workshop - Step 5: Start OpenTrons MCP Server
#
# Purpose: Build, start, and health-check the OpenTrons MCP server container.
#          Run this on the host that will provide OpenTrons capability.
#          Ephemeral — designed to be torn down after the workshop.
#
# Usage:   ./05_start_opentrons_server.sh [OPTIONS]
#
# Exit codes:
#   0 - Server started and healthy
#   1 - Error occurred

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
DIM='\033[2m'
NC='\033[0m' # No Color

# Default values
COMPOSE_FILE=""
OPENTRONS_PORT="${OPENTRONS_PORT:-9003}"
HEALTH_TIMEOUT=60
SKIP_BUILD=false

# Function to print colored output
print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_info() {
    echo -e "${CYAN}$1${NC}"
}

print_dim() {
    echo -e "${DIM}$1${NC}"
}

print_section() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "$1"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# Parse command-line arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --compose-file)
                COMPOSE_FILE="$2"
                shift 2
                ;;
            --port)
                OPENTRONS_PORT="$2"
                shift 2
                ;;
            --timeout)
                HEALTH_TIMEOUT="$2"
                shift 2
                ;;
            --skip-build)
                SKIP_BUILD=true
                shift
                ;;
            -h|--help)
                show_usage
                exit 0
                ;;
            *)
                print_error "Unknown argument: $1"
                show_usage
                exit 1
                ;;
        esac
    done
}

show_usage() {
    cat <<'EOF'
Usage: ./05_start_opentrons_server.sh [OPTIONS]

Build, start, and health-check the OpenTrons MCP server container.

Options:
  --compose-file <path>   Path to docker-compose.opentrons.yaml (auto-detected)
  --port <port>           OpenTrons server port (default: 9003)
  --timeout <seconds>     Health check timeout (default: 60)
  --skip-build            Skip Docker image build (use existing image)
  -h, --help              Show this help message

Examples:
  # Start with auto-detection
  ./05_start_opentrons_server.sh

  # Start with explicit compose file
  ./05_start_opentrons_server.sh --compose-file /path/to/docker-compose.opentrons.yaml

  # Start without rebuilding image
  ./05_start_opentrons_server.sh --skip-build
EOF
}

# Find ADEPT project root by walking up from script directory
find_project_root() {
    local dir
    dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    local max_depth=5
    local depth=0
    while [ $depth -lt $max_depth ]; do
        if [ -f "$dir/Makefile" ] && [ -d "$dir/deployment" ]; then
            echo "$dir"
            return 0
        fi
        dir="$(dirname "$dir")"
        depth=$((depth + 1))
    done

    if [ -f "./Makefile" ] && [ -d "./deployment" ]; then
        pwd
        return 0
    fi

    return 1
}

# Find docker-compose.opentrons.yaml
find_compose_file() {
    if [ -n "$COMPOSE_FILE" ]; then
        if [ -f "$COMPOSE_FILE" ]; then
            echo "$COMPOSE_FILE"
            return 0
        fi
        print_error "Specified compose file not found: $COMPOSE_FILE"
        return 1
    fi

    local project_root
    project_root=$(find_project_root 2>/dev/null || echo "")

    if [ -n "$project_root" ]; then
        local compose_path="$project_root/examples/opentrons_mcp_server/docker-compose.opentrons.yaml"
        if [ -f "$compose_path" ]; then
            echo "$compose_path"
            return 0
        fi
    fi

    # Try relative paths
    local paths=(
        "./docker-compose.opentrons.yaml"
        "../opentrons_mcp_server/docker-compose.opentrons.yaml"
        "../../opentrons_mcp_server/docker-compose.opentrons.yaml"
        "../../examples/opentrons_mcp_server/docker-compose.opentrons.yaml"
    )

    for path in "${paths[@]}"; do
        if [ -f "$path" ]; then
            echo "$path"
            return 0
        fi
    done

    return 1
}

# Check prerequisites
check_prerequisites() {
    print_info "Checking prerequisites..."

    # Docker
    if ! command -v docker >/dev/null 2>&1; then
        print_error "Docker is not installed"
        return 1
    fi
    print_success "Docker is available"

    # Docker Compose
    if ! docker compose version >/dev/null 2>&1; then
        print_error "Docker Compose v2 is not available"
        return 1
    fi
    print_success "Docker Compose v2 is available"

    # Check adept_application_network exists
    if ! docker network ls --format '{{.Name}}' | grep -q '^adept_application_network$'; then
        print_error "adept_application_network does not exist"
        echo ""
        echo "  Start the ADEPT stack first:"
        echo "    make start"
        return 1
    fi
    print_success "adept_application_network exists"

    return 0
}

# Start the OpenTrons server
start_server() {
    local compose_file="$1"

    print_section "Starting OpenTrons MCP Server"

    print_dim "  Compose file: $compose_file"
    print_dim "  Port: $OPENTRONS_PORT"
    echo ""

    # Build image
    if [ "$SKIP_BUILD" = false ]; then
        print_info "Building OpenTrons MCP server image..."
        if ! docker compose -f "$compose_file" build 2>&1; then
            print_error "Failed to build OpenTrons MCP server image"
            return 1
        fi
        print_success "Image built successfully"
    else
        print_dim "  Skipping build (--skip-build)"
    fi

    # Start container
    print_info "Starting container..."
    if ! docker compose -f "$compose_file" up -d 2>&1; then
        print_error "Failed to start OpenTrons MCP server"
        return 1
    fi
    print_success "Container started"

    return 0
}

# Wait for health check to pass
wait_for_health() {
    print_info "Waiting for health check (timeout: ${HEALTH_TIMEOUT}s)..."

    local elapsed=0
    local interval=2

    while [ $elapsed -lt $HEALTH_TIMEOUT ]; do
        local status
        status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 \
            "http://localhost:${OPENTRONS_PORT}/health" 2>/dev/null || echo "000")

        if [ "$status" = "200" ]; then
            print_success "Health check passed"

            # Display health info
            local health_data
            health_data=$(curl -s "http://localhost:${OPENTRONS_PORT}/health" 2>/dev/null)
            if [ -n "$health_data" ]; then
                echo ""
                echo "  Health Response:"
                echo "  $health_data" | python3 -m json.tool 2>/dev/null || echo "  $health_data"
            fi
            return 0
        fi

        sleep $interval
        elapsed=$((elapsed + interval))
        printf "  Waiting... (%ds / %ds)\r" "$elapsed" "$HEALTH_TIMEOUT"
    done

    echo ""
    print_error "Health check timed out after ${HEALTH_TIMEOUT}s"
    echo ""
    echo "  Debug:"
    echo "    docker logs opentrons_mcp_server --tail 20"
    echo "    curl -v http://localhost:${OPENTRONS_PORT}/health"
    return 1
}

# Main execution
main() {
    parse_args "$@"

    print_section "OpenTrons MCP Server Setup"

    # Check prerequisites
    if ! check_prerequisites; then
        exit 1
    fi

    # Find compose file
    local compose_file
    compose_file=$(find_compose_file) || {
        print_error "docker-compose.opentrons.yaml not found"
        echo ""
        echo "  Expected location:"
        echo "    examples/opentrons_mcp_server/docker-compose.opentrons.yaml"
        echo ""
        echo "  Specify explicitly:"
        echo "    $0 --compose-file /path/to/docker-compose.opentrons.yaml"
        exit 1
    }

    # Check if already running
    if docker ps --format '{{.Names}}' | grep -q '^opentrons_mcp_server$'; then
        print_warning "OpenTrons MCP server is already running"
        echo ""
        print_info "Checking health..."
        if wait_for_health; then
            echo ""
            print_success "Server is running and healthy at http://localhost:${OPENTRONS_PORT}"
            echo ""
            echo "  To restart: docker compose -f $compose_file restart"
            echo "  To stop:    docker compose -f $compose_file down"
            exit 0
        else
            print_warning "Server is running but unhealthy, restarting..."
            docker compose -f "$compose_file" down 2>/dev/null || true
        fi
    fi

    # Start server
    if ! start_server "$compose_file"; then
        exit 1
    fi

    # Wait for health
    if ! wait_for_health; then
        exit 1
    fi

    echo ""
    print_section "OpenTrons MCP Server Ready"
    echo ""
    print_success "Server URL: http://localhost:${OPENTRONS_PORT}"
    print_success "Health:     http://localhost:${OPENTRONS_PORT}/health"
    print_success "MCP:        http://localhost:${OPENTRONS_PORT}/mcp"
    echo ""
    echo "  Next steps:"
    echo "    1. Register Opentrons capability: ./06_register_opentrons_capability.sh"
    echo "    2. Delegate from remote host:     ./07_opentrons_a2a_delegation.sh"
    echo ""
    echo "  Teardown:"
    echo "    docker compose -f $compose_file down"
}

# Run main function
main "$@"
