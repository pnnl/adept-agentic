#!/bin/bash
#
# ADEPT A2A Workshop - Step 2: Register Peer Gateway
#
# Purpose: Register remote ADEPT instance as peer for task delegation
# Usage:   ./02_register_peer.sh --peer-ip <ip> --peer-alias <alias> [OPTIONS]
#
# Exit codes:
#   0 - Peer registered successfully
#   1 - Error occurred

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values
PEER_IP=""
PEER_ALIAS=""
DESCRIPTION=""
TAGS=""
REGISTRY_URL="http://gateway_registry:8086"

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

# Parse command-line arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --peer-ip)
                PEER_IP="$2"
                shift 2
                ;;
            --peer-alias)
                PEER_ALIAS="$2"
                shift 2
                ;;
            --description)
                DESCRIPTION="$2"
                shift 2
                ;;
            --tags)
                TAGS="$2"
                shift 2
                ;;
            --registry-url)
                REGISTRY_URL="$2"
                shift 2
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
    if [ -z "$PEER_IP" ]; then
        print_error "Peer IP is required"
        show_usage
        exit 1
    fi

    if [ -z "$PEER_ALIAS" ]; then
        print_error "Peer alias is required"
        show_usage
        exit 1
    fi
}

show_usage() {
    cat <<EOF
Usage: $0 --peer-ip <ip> --peer-alias <alias> [OPTIONS]

Register remote ADEPT instance as peer gateway.

Required arguments:
  --peer-ip <ip>            Peer gateway IP address or hostname
  --peer-alias <alias>      Unique alias for peer (e.g., aws-gateway)

Optional arguments:
  --description <text>      Description of peer gateway
  --tags <tags>             Comma-separated tags (e.g., "aws,ec2,production")
  --registry-url <url>      Gateway Registry URL (default: http://localhost:8086)
  -h, --help                Show this help message

Examples:
  # Register AWS gateway
  $0 --peer-ip 10.0.0.1 --peer-alias aws-gateway

  # Register with description and tags
  $0 --peer-ip 10.0.0.1 --peer-alias aws-gateway \\
     --description "AWS EC2 Production Gateway" \\
     --tags "aws,ec2,us-east-1,production"
EOF
}

# Detect local IP address
detect_local_ip() {
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

# Check if agentic CLI is available
check_agentic_cli() {
    if ! command -v agentic >/dev/null 2>&1; then
        print_error "agentic CLI not found"
        echo ""
        echo "Install agentic CLI:"
        echo "  pip install -e src/agentic_framework_sdk/"
        echo ""
        echo "Or add to PATH:"
        echo "  export PATH=\"\$PATH:\$PWD/src/agentic_framework_sdk\""
        return 1
    fi
    return 0
}

# Register peer gateway
register_peer() {
    print_section "Registering Peer Gateway"

    LOCAL_IP=$(detect_local_ip)
    echo "Local Gateway: ${LOCAL_IP:-unknown}"
    echo "Peer Gateway: $PEER_IP ($PEER_ALIAS)"
    echo "Registry URL: $REGISTRY_URL"
    echo ""

    # Check agentic CLI
    if ! check_agentic_cli; then
        return 1
    fi

    # Build registration command
    local cmd="agentic a2a register-peer $PEER_ALIAS https://$PEER_IP/a2a"

    # Add optional arguments
    if [ -n "$DESCRIPTION" ]; then
        cmd="$cmd --description \"$DESCRIPTION\""
    fi

    if [ -n "$TAGS" ]; then
        cmd="$cmd --tags \"$TAGS\""
    fi

    cmd="$cmd --registry-url $REGISTRY_URL"

    # Execute registration
    echo "Executing: $cmd"
    echo ""

    if ! eval "$cmd"; then
        print_error "Failed to register peer gateway"
        echo ""
        echo "Troubleshooting:"
        echo "  - Check Gateway Registry is running: docker ps | grep gateway_registry"
        echo "  - Verify credentials exist: ls -la deployment/local/docker-compose/.env-keycloak-credentials-dir/ | grep VALIDATION_RUNNER"
        echo "  - Test peer connectivity: curl -k https://$PEER_IP/v1/models"
        return 1
    fi

    echo ""
    print_success "Peer gateway registered successfully"
    echo ""

    # List all registered peers
    echo "Registered Peers:"
    agentic a2a list-peers --registry-url "$REGISTRY_URL" || true

    return 0
}

# Main execution
main() {
    parse_args "$@"
    register_peer
}

# Run main function
main "$@"
