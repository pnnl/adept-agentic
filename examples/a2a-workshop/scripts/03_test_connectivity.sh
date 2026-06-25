#!/bin/bash
#
# ADEPT A2A Workshop - Step 3: Test A2A Connectivity
#
# Purpose: Verify A2A communication works with registered peer gateway
# Usage:   ./03_test_connectivity.sh --peer-alias <alias> [OPTIONS]
#
# Exit codes:
#   0 - All connectivity tests passed
#   1 - One or more tests failed

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values
PEER_ALIAS=""
REGISTRY_URL="http://gateway_registry:8086"
VERBOSE=false
QUIET=false

# Function to print colored output
print_success() {
    [ "$QUIET" = false ] && echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}" >&2
}

print_warning() {
    [ "$QUIET" = false ] && echo -e "${YELLOW}⚠️  $1${NC}"
}

print_section() {
    [ "$QUIET" = false ] && {
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "$1"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    }
}

# Parse command-line arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --peer-alias)
                PEER_ALIAS="$2"
                shift 2
                ;;
            --registry-url)
                REGISTRY_URL="$2"
                shift 2
                ;;
            --verbose)
                VERBOSE=true
                shift
                ;;
            --quiet)
                QUIET=true
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

    # Validate required arguments
    if [ -z "$PEER_ALIAS" ]; then
        print_error "Peer alias is required"
        show_usage
        exit 1
    fi
}

show_usage() {
    cat <<EOF
Usage: $0 --peer-alias <alias> [OPTIONS]

Test A2A connectivity to registered peer gateway.

Required arguments:
  --peer-alias <alias>      Peer alias (e.g., aws-gateway)

Optional arguments:
  --registry-url <url>      Gateway Registry URL (default: http://localhost:8086)
  --verbose                 Show detailed output
  --quiet                   Minimal output (for automation)
  -h, --help                Show this help message

Examples:
  # Test connection to AWS gateway
  $0 --peer-alias aws-gateway

  # Test with verbose output
  $0 --peer-alias aws-gateway --verbose

  # Quiet mode (for cron jobs)
  $0 --peer-alias aws-gateway --quiet
EOF
}

# Detect local IP address
detect_local_ip() {
    local ip=""

    if command -v hostname >/dev/null 2>&1; then
        ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    fi

    if [ -z "$ip" ] && command -v ip >/dev/null 2>&1; then
        ip=$(ip route get 1.1.1.1 2>/dev/null | awk '{print $7; exit}')
    fi

    if [ -z "$ip" ] && command -v ifconfig >/dev/null 2>&1; then
        ip=$(ifconfig | grep "inet " | grep -v 127.0.0.1 | awk '{print $2}' | head -1)
    fi

    if [ -z "$ip" ] && [ -n "${LOCAL_IP:-}" ]; then
        ip="$LOCAL_IP"
    fi

    echo "$ip"
}

# Get peer URL from Gateway Registry
get_peer_url() {
    local alias="$1"

    # Use agentic CLI to list peers and extract URL
    if ! command -v agentic >/dev/null 2>&1; then
        print_error "agentic CLI not found"
        return 1
    fi

    local peer_url
    peer_url=$(agentic a2a list-peers --format json --registry-url "$REGISTRY_URL" 2>/dev/null | \
               jq -r ".[] | select(.alias == \"$alias\") | .public_url" 2>/dev/null || echo "")

    if [ -z "$peer_url" ] || [ "$peer_url" = "null" ]; then
        print_error "Peer '$alias' not found in registry"
        echo ""
        echo "Available peers:"
        agentic a2a list-peers --registry-url "$REGISTRY_URL" 2>/dev/null || echo "  (none)"
        return 1
    fi

    echo "$peer_url"
}

# Test basic HTTP connectivity
test_http_connectivity() {
    local peer_url="$1"
    local peer_ip
    peer_ip=$(echo "$peer_url" | sed -E 's|https?://([^:/]+).*|\1|')

    [ "$VERBOSE" = true ] && echo "Testing basic HTTP connectivity to $peer_ip..."

    # Extract domain/IP and test connectivity
    local start_time
    start_time=$(date +%s%3N)

    local status_code
    status_code=$(curl -k -s -o /dev/null -w "%{http_code}" --max-time 10 "$peer_url" 2>/dev/null || echo "000")

    local end_time
    end_time=$(date +%s%3N)
    local response_time=$((end_time - start_time))

    if [ "$status_code" = "000" ]; then
        print_error "HTTP connection failed"
        echo "  Peer URL: $peer_url"
        echo "  Check network connectivity and firewall rules"
        return 1
    fi

    print_success "HTTP connection successful"
    [ "$VERBOSE" = true ] && echo "  Response time: ${response_time}ms"
    [ "$VERBOSE" = true ] && echo "  Status code: $status_code"

    return 0
}

# Test Agent Gateway API
test_agent_gateway_api() {
    local peer_url="$1"

    [ "$VERBOSE" = true ] && echo "Testing Agent Gateway API..."

    # Append /models to peer_url if not already present
    local api_url="${peer_url%/}/models"

    local status_code
    status_code=$(curl -k -s -o /dev/null -w "%{http_code}" --max-time 10 "$api_url" 2>/dev/null || echo "000")

    # Accept 401 (auth required) or 200 (accessible) as success
    if [ "$status_code" = "401" ] || [ "$status_code" = "200" ]; then
        print_success "Agent Gateway API accessible"
        [ "$VERBOSE" = true ] && echo "  Response code: $status_code (expected - auth may be required)"
        return 0
    fi

    print_error "Agent Gateway API not accessible"
    echo "  Expected: 200 or 401, Got: $status_code"
    return 1
}

# Test authenticated request (if service token available)
test_authenticated_request() {
    local peer_url="$1"

    # Skip if no service token available
    if [ -z "${LOCAL_A2A_TOKEN:-}" ]; then
        print_warning "Skipping authenticated test (no LOCAL_A2A_TOKEN set)"
        return 0
    fi

    [ "$VERBOSE" = true ] && echo "Testing authenticated request..."

    local api_url="${peer_url%/}/models"

    local status_code
    status_code=$(curl -k -s -o /dev/null -w "%{http_code}" --max-time 10 \
                  -H "Authorization: Bearer $LOCAL_A2A_TOKEN" \
                  "$api_url" 2>/dev/null || echo "000")

    if [ "$status_code" = "200" ]; then
        print_success "Authenticated request successful"
        [ "$VERBOSE" = true ] && echo "  Response code: $status_code"
        return 0
    else
        print_warning "Authenticated request failed (token may not be accepted by peer)"
        [ "$VERBOSE" = true ] && echo "  Response code: $status_code"
        return 0  # Non-critical
    fi
}

# Run all connectivity tests
run_connectivity_tests() {
    print_section "Testing A2A Connectivity"

    LOCAL_IP=$(detect_local_ip)
    [ "$QUIET" = false ] && echo "Local Gateway: ${LOCAL_IP:-unknown}"
    [ "$QUIET" = false ] && echo "Peer Gateway: $PEER_ALIAS"
    [ "$QUIET" = false ] && echo ""

    # Get peer URL
    PEER_URL=$(get_peer_url "$PEER_ALIAS")
    if [ -z "$PEER_URL" ]; then
        return 1
    fi

    [ "$QUIET" = false ] && echo "Peer URL: $PEER_URL"
    [ "$QUIET" = false ] && echo ""

    # Run tests
    local failed=0

    test_http_connectivity "$PEER_URL" || failed=1
    test_agent_gateway_api "$PEER_URL" || failed=1
    test_authenticated_request "$PEER_URL" || failed=1

    # Summary
    [ "$QUIET" = false ] && echo ""
    [ "$QUIET" = false ] && print_section "Summary"

    if [ $failed -eq 0 ]; then
        print_success "Connectivity Status: ✅ READY FOR A2A TASK DELEGATION"
        return 0
    else
        print_error "Connectivity Status: ❌ ISSUES DETECTED"
        [ "$QUIET" = false ] && {
            echo ""
            echo "Troubleshooting:"
            echo "  - Check firewall rules between hosts"
            echo "  - Verify peer gateway is running: ssh <peer_host> 'docker ps'"
            echo "  - Test manual connection: curl -k https://$PEER_IP/v1/models"
        }
        return 1
    fi
}

# Main execution
main() {
    parse_args "$@"
    run_connectivity_tests
}

# Run main function
main "$@"
