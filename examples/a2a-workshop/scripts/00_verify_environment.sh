#!/bin/bash
#
# ADEPT A2A Workshop - Step 0: Environment Verification
#
# Purpose: Verify ADEPT services are running and healthy before A2A registration
# Usage:   ./00_verify_environment.sh
#
# Exit codes:
#   0 - All checks passed
#   1 - One or more checks failed

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

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

print_section() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "$1"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# Detect local IP address
detect_local_ip() {
    # Try multiple methods to detect local IP
    local ip=""

    # Method 1: hostname -I (Linux)
    if command -v hostname >/dev/null 2>&1; then
        ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    fi

    # Method 2: ip route (Linux)
    if [ -z "$ip" ] && command -v ip >/dev/null 2>&1; then
        ip=$(ip route get 1.1.1.1 2>/dev/null | awk '{print $7; exit}')
    fi

    # Method 3: ifconfig (macOS/BSD)
    if [ -z "$ip" ] && command -v ifconfig >/dev/null 2>&1; then
        ip=$(ifconfig | grep "inet " | grep -v 127.0.0.1 | awk '{print $2}' | head -1)
    fi

    # Method 4: Use LOCAL_IP environment variable if set
    if [ -z "$ip" ] && [ -n "${LOCAL_IP:-}" ]; then
        ip="$LOCAL_IP"
    fi

    echo "$ip"
}

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check if Docker is running
check_docker() {
    if ! command_exists docker; then
        print_error "Docker is not installed"
        return 1
    fi

    if ! docker ps >/dev/null 2>&1; then
        print_error "Docker is not running"
        return 1
    fi

    print_success "Docker is running"
    return 0
}

# Check if ADEPT container is running
check_container() {
    local container_name="$1"

    if docker ps --format '{{.Names}}' | grep -q "^${container_name}$"; then
        print_success "$container_name is running"
        return 0
    else
        print_error "$container_name is not running"
        return 1
    fi
}

# Check Agent Gateway API accessibility
check_agent_gateway_api() {
    # Try HTTPS first (via nginx_proxy)
    if curl -k -s -f --max-time 5 https://localhost/v1/models >/dev/null 2>&1 || \
       [ "$(curl -k -s -o /dev/null -w "%{http_code}" --max-time 5 https://localhost/v1/models)" = "401" ]; then
        print_success "Agent Gateway API is accessible (HTTPS)"
        return 0
    fi

    # Try HTTP direct access
    if curl -s -f --max-time 5 http://localhost:8083/v1/models >/dev/null 2>&1 || \
       [ "$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://localhost:8083/v1/models)" = "401" ]; then
        print_success "Agent Gateway API is accessible (HTTP)"
        return 0
    fi

    print_error "Agent Gateway API is not accessible"
    return 1
}

# Check Gateway Registry health
check_gateway_registry() {
    # Check if container is accessible
    if docker exec gateway_registry curl -s -f http://localhost:8086/health >/dev/null 2>&1; then
        print_success "Gateway Registry health check passed"
        return 0
    else
        print_warning "Gateway Registry health endpoint not accessible (may not have health endpoint yet)"
        return 0  # Non-critical for A2A
    fi
}

# Main execution
main() {
    print_section "ADEPT Environment Verification"

    # Detect and display local IP
    LOCAL_IP=$(detect_local_ip)
    if [ -n "$LOCAL_IP" ]; then
        echo "Detected Local IP: $LOCAL_IP"
    else
        print_warning "Could not auto-detect local IP address"
        echo "Set LOCAL_IP environment variable manually: export LOCAL_IP=\"10.16.17.5\""
    fi
    echo ""

    # Run checks
    FAILED=0

    check_docker || FAILED=1
    check_container "agent_gateway" || FAILED=1
    check_container "orchestration_service" || FAILED=1
    check_container "gateway_registry" || FAILED=1
    check_container "keycloak" || FAILED=1
    check_agent_gateway_api || FAILED=1
    check_gateway_registry || FAILED=1

    # Summary
    echo ""
    print_section "Summary"

    if [ $FAILED -eq 0 ]; then
        print_success "Environment Status: ✅ READY FOR A2A REGISTRATION"
        echo ""
        echo "Next steps:"
        echo "  1. Generate A2A service token: ./01_generate_a2a_token.sh --name a2a-my-gateway"
        echo "  2. Register peer gateway: ./02_register_peer.sh --peer-ip <remote_ip> --peer-alias <alias>"
        echo "  3. Test connectivity: ./03_test_connectivity.sh --peer-alias <alias>"
        return 0
    else
        print_error "Environment Status: ❌ NOT READY"
        echo ""
        echo "Troubleshooting:"
        echo "  - Check if ADEPT is running: cd /path/to/adept && docker ps"
        echo "  - Start ADEPT if needed: make start"
        echo "  - Wait for services to be ready (30-60 seconds)"
        echo "  - Re-run verification: ./00_verify_environment.sh"
        return 1
    fi
}

# Run main function
main "$@"
