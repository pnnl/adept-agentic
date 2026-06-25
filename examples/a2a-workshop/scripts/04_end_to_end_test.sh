#!/bin/bash
#
# ADEPT A2A Workshop - Step 4: End-to-End Validation
#
# Purpose: Comprehensive A2A workflow validation from setup to task delegation
# Usage:   ./04_end_to_end_test.sh --peer-ip <ip> --peer-alias <alias>
#
# Exit codes:
#   0 - All tests passed
#   1 - One or more tests failed

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
PEER_IP=""
PEER_ALIAS=""
SKIP_TOKEN_GENERATION=false
SKIP_REGISTRATION=false

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
    echo -e "${BLUE}ℹ️  $1${NC}"
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
            --skip-token-generation)
                SKIP_TOKEN_GENERATION=true
                shift
                ;;
            --skip-registration)
                SKIP_REGISTRATION=true
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

Comprehensive A2A workflow validation including:
  - Environment verification
  - Service token generation
  - Peer registration
  - Connectivity testing
  - (Optional) Task delegation

Required arguments:
  --peer-ip <ip>               Peer gateway IP address
  --peer-alias <alias>         Unique alias for peer

Optional arguments:
  --skip-token-generation      Skip service token generation step
  --skip-registration          Skip peer registration step
  -h, --help                   Show this help message

Examples:
  # Full E2E test
  $0 --peer-ip 10.0.0.1 --peer-alias aws-gateway

  # Skip token generation (if already generated)
  $0 --peer-ip 10.0.0.1 --peer-alias aws-gateway --skip-token-generation

  # Skip registration (if already registered)
  $0 --peer-ip 10.0.0.1 --peer-alias aws-gateway --skip-registration
EOF
}

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Run test with counter
run_test() {
    local test_num="$1"
    local test_name="$2"
    local test_command="$3"
    shift 3

    print_info "Test $test_num: $test_name..."

    if eval "$test_command" "$@"; then
        print_success "Test $test_num: $test_name - PASSED"
        return 0
    else
        print_error "Test $test_num: $test_name - FAILED"
        return 1
    fi
}

# Main test execution
run_e2e_tests() {
    print_section "A2A End-to-End Validation"

    echo "Peer IP: $PEER_IP"
    echo "Peer Alias: $PEER_ALIAS"
    echo ""

    local failed=0
    local test_count=0

    # Test 1: Environment verification
    test_count=$((test_count + 1))
    if ! run_test "$test_count" "Environment verification" "$SCRIPT_DIR/00_verify_environment.sh"; then
        failed=$((failed + 1))
        print_error "Environment is not ready. Please fix issues and try again."
        return 1
    fi

    # Test 2: Service token generation (optional)
    if [ "$SKIP_TOKEN_GENERATION" = false ]; then
        test_count=$((test_count + 1))
        TOKEN_NAME="a2a-e2e-test-$(date +%s)"
        if ! run_test "$test_count" "Service token generation" "$SCRIPT_DIR/01_generate_a2a_token.sh" --name "$TOKEN_NAME"; then
            failed=$((failed + 1))
            print_warning "Token generation failed, but continuing..."
        else
            print_info "Token generated: $TOKEN_NAME"
            print_info "Set LOCAL_A2A_TOKEN environment variable for authenticated tests"
        fi
    else
        print_info "Skipping token generation (--skip-token-generation)"
    fi

    # Test 3: Peer registration (optional)
    if [ "$SKIP_REGISTRATION" = false ]; then
        test_count=$((test_count + 1))
        if ! run_test "$test_count" "Peer registration" "$SCRIPT_DIR/02_register_peer.sh" \
            --peer-ip "$PEER_IP" \
            --peer-alias "$PEER_ALIAS" \
            --description "E2E Test Peer" \
            --tags "test,e2e"; then
            failed=$((failed + 1))
            print_warning "Registration failed, but continuing to test connectivity..."
        fi
    else
        print_info "Skipping peer registration (--skip-registration)"
    fi

    # Test 4: Connectivity test
    test_count=$((test_count + 1))
    if ! run_test "$test_count" "Connectivity test" "$SCRIPT_DIR/03_test_connectivity.sh" \
        --peer-alias "$PEER_ALIAS" \
        --verbose; then
        failed=$((failed + 1))
    fi

    # Test 5: Task delegation (placeholder - Phase 2B feature)
    # Commented out until Phase 2B is implemented
    # test_count=$((test_count + 1))
    # if ! run_test "$test_count" "Task delegation" test_task_delegation; then
    #     failed=$((failed + 1))
    # fi

    # Summary
    echo ""
    print_section "Summary"

    echo "Total tests: $test_count"
    echo "Passed: $((test_count - failed))"
    echo "Failed: $failed"
    echo ""

    if [ $failed -eq 0 ]; then
        print_success "All tests passed! A2A setup is complete."
        echo ""
        echo "Next steps:"
        echo "  - View registered peers: agentic a2a list-peers"
        echo "  - Test connection manually: agentic a2a test-connection $PEER_ALIAS"
        echo "  - Monitor peer health: watch -n 60 '$SCRIPT_DIR/03_test_connectivity.sh --peer-alias $PEER_ALIAS --quiet'"
        return 0
    else
        print_error "$failed test(s) failed. Please review errors above."
        echo ""
        echo "Troubleshooting:"
        echo "  - Check logs for detailed error messages"
        echo "  - Verify network connectivity: curl -k https://$PEER_IP/v1/models"
        echo "  - Review workshop README: examples/a2a-workshop/README.md"
        return 1
    fi
}

# Main execution
main() {
    parse_args "$@"
    run_e2e_tests
}

# Run main function
main "$@"
