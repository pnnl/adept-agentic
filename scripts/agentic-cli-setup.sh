#!/bin/bash
set -e

# Agentic Framework CLI Setup & Validation Script
# This script ensures proper host environment setup for external CLI clients

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
HOSTS_FILE="/etc/hosts"
REQUIRED_HOST="api.agentic.local"
NGINX_HEALTH_URL="https://api.agentic.local/health"
AUTH_URL="https://api.agentic.local/auth/.well-known/openid_configuration"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Functions
log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

check_hosts_file() {
    log_info "Checking /etc/hosts file..."
    
    if grep -q "127.0.0.1.*$REQUIRED_HOST" "$HOSTS_FILE" 2>/dev/null; then
        log_success "Host entry found: $REQUIRED_HOST"
        return 0
    else
        log_error "Host entry missing: $REQUIRED_HOST"
        echo
        echo "To fix this, run:"
        echo "  sudo echo '127.0.0.1 $REQUIRED_HOST' >> /etc/hosts"
        echo
        return 1
    fi
}

check_docker_services() {
    log_info "Checking required Docker services..."
    
    local required_services=("nginx_proxy" "keycloak" "agent_gateway")
    local missing_services=()
    
    for service in "${required_services[@]}"; do
        if docker ps --format "table {{.Names}}" | grep -q "^$service$"; then
            log_success "Service running: $service"
        else
            missing_services+=("$service")
            log_error "Service not running: $service"
        fi
    done
    
    if [ ${#missing_services[@]} -gt 0 ]; then
        echo
        echo "Missing services: ${missing_services[*]}"
        echo "To start services, run:"
        echo "  cd $PROJECT_DIR"
        echo "  make start"
        echo
        return 1
    fi
    
    return 0
}

check_nginx_health() {
    log_info "Testing NGINX proxy connectivity..."
    
    if curl -k -s --connect-timeout 5 "$NGINX_HEALTH_URL" | grep -q "nginx-proxy healthy"; then
        log_success "NGINX proxy is accessible"
        return 0
    else
        log_error "NGINX proxy is not accessible at $NGINX_HEALTH_URL"
        echo
        echo "Possible issues:"
        echo "  - NGINX container not running"
        echo "  - SSL certificate issues"
        echo "  - Port conflicts"
        echo
        return 1
    fi
}

check_auth_endpoint() {
    log_info "Testing authentication endpoint..."
    
    local response=$(curl -k -s --connect-timeout 5 "$AUTH_URL")
    
    if echo "$response" | python3 -c "import sys, json; json.load(sys.stdin)" 2>/dev/null; then
        log_success "Authentication endpoint is accessible"
        return 0
    else
        log_error "Authentication endpoint failed"
        echo "Response: $response"
        echo
        echo "This usually indicates:"
        echo "  - Keycloak not running"
        echo "  - Realm configuration issues"
        echo "  - NGINX proxy misconfiguration"
        echo
        return 1
    fi
}

check_python_environment() {
    log_info "Checking Python environment..."
    
    if [ ! -f "$PROJECT_DIR/src/agentic_framework_sdk/cli/main.py" ]; then
        log_error "CLI source not found at expected location"
        return 1
    fi
    
    cd "$PROJECT_DIR"
    export PYTHONPATH="$PROJECT_DIR/src"
    
    if python3 -c "from agentic_framework_sdk.auth import KeycloakAuth" 2>/dev/null; then
        log_success "Python auth modules available"
        return 0
    else
        log_error "Python auth modules not available"
        echo
        echo "To fix this, install dependencies:"
        echo "  cd $PROJECT_DIR"
        echo "  pip install -e src/"
        echo
        return 1
    fi
}

run_cli() {
    log_info "Starting Agentic CLI..."
    
    cd "$PROJECT_DIR"
    export PYTHONPATH="$PROJECT_DIR/src"
    
    log_info "Running CLI with provided arguments..."
    # Use the new Python-based CLI entry script
    exec python3 agentic_cli.py "$@"
}

show_usage() {
    echo "Agentic Framework CLI Setup & Runner"
    echo
    echo "This script validates your environment and runs the CLI with proper setup."
    echo
    echo "Usage:"
    echo "  $0 --check                           # Validate environment only"
    echo "  $0 [CLI_ARGS...]                     # Validate and run CLI"
    echo
    echo "Examples:"
    echo "  $0 --check"
    echo "  $0 auth login --external --username notebook-user"
    echo "  $0 auth test --external" 
    echo "  $0 chat"
    echo
    echo "Environment Requirements:"
    echo "  - Docker services running (nginx_proxy, keycloak, agent_gateway)"
    echo "  - /etc/hosts entry: 127.0.0.1 api.agentic.local"
    echo "  - Python dependencies installed"
    echo
}

main() {
    echo "🚀 Agentic Framework CLI Setup & Validation"
    echo "============================================"
    echo
    
    if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
        show_usage
        exit 0
    fi
    
    local check_only=false
    if [ "$1" = "--check" ]; then
        check_only=true
        shift
    fi
    
    # Run all validation checks
    local checks_passed=true
    
    check_hosts_file || checks_passed=false
    echo
    
    check_docker_services || checks_passed=false
    echo
    
    check_nginx_health || checks_passed=false
    echo
    
    check_auth_endpoint || checks_passed=false
    echo
    
    check_python_environment || checks_passed=false
    echo
    
    if [ "$checks_passed" = false ]; then
        log_error "Environment validation failed. Please fix the above issues."
        echo
        echo "Quick fix commands:"
        echo "  sudo echo '127.0.0.1 api.agentic.local' >> /etc/hosts"
        echo "  cd $PROJECT_DIR && make start"
        echo "  cd $PROJECT_DIR && pip install -e src/"
        echo
        exit 1
    fi
    
    log_success "Environment validation passed!"
    echo
    
    if [ "$check_only" = true ]; then
        echo "✨ Your environment is ready for the Agentic CLI!"
        echo
        echo "Try these commands:"
        echo "  $0 auth test --external"
        echo "  $0 auth login --external --username notebook-user"
        echo "  $0 chat"
        echo
        exit 0
    fi
    
    if [ $# -eq 0 ]; then
        echo "✨ Environment ready! Add CLI arguments to run commands."
        echo
        show_usage
        exit 0
    fi
    
    # Pass remaining arguments to CLI
    log_info "Starting Agentic CLI..."
    echo
    run_cli "$@"
}

# Run main function with all arguments
main "$@"