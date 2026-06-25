#!/bin/bash
#
# ADEPT A2A Workshop - Step 1: Generate A2A Service Token
#
# Purpose: Generate JWT token for authenticated A2A communication between gateways.
#          Auto-discovers GATEWAY_CLIENT_SECRET from the credentials directory,
#          validates Keycloak accessibility, and generates a token via OAuth2
#          client_credentials flow.
#
# Usage:   ./01_generate_a2a_token.sh [OPTIONS]
#          source <(./01_generate_a2a_token.sh --export)
#
# Exit codes:
#   0 - Token generated successfully
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
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak:8180}"
REALM="${KEYCLOAK_REALM:-master}"
CLIENT_ID="${GATEWAY_CLIENT_ID:-gateway-client}"
CLIENT_SECRET="${GATEWAY_CLIENT_SECRET:-}"
EXPORT_MODE=false
QUIET=false
TEST_PEER=""

# Credential discovery search paths (ordered by priority)
CRED_SEARCH_PATHS=(
    "./deployment/local/docker-compose/.env-keycloak-credentials-dir/GATEWAY_CLIENT_SECRET"
    "./.env-keycloak-credentials-dir/GATEWAY_CLIENT_SECRET"
    "$HOME/.adept-agentic/credentials"
)

# Function to print colored output
print_success() {
    [ "$QUIET" = false ] && echo -e "${GREEN}✅ $1${NC}" >&2
}

print_error() {
    echo -e "${RED}❌ $1${NC}" >&2
}

print_warning() {
    [ "$QUIET" = false ] && echo -e "${YELLOW}⚠️  $1${NC}" >&2
}

print_info() {
    [ "$QUIET" = false ] && echo -e "${CYAN}$1${NC}" >&2
}

print_dim() {
    [ "$QUIET" = false ] && echo -e "${DIM}$1${NC}" >&2
}

print_section() {
    [ "$QUIET" = false ] && {
        echo "" >&2
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" >&2
        echo "$1" >&2
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" >&2
    }
}

# Parse command-line arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --keycloak-url)
                KEYCLOAK_URL="$2"
                shift 2
                ;;
            --realm)
                REALM="$2"
                shift 2
                ;;
            --client-id)
                CLIENT_ID="$2"
                shift 2
                ;;
            --client-secret)
                CLIENT_SECRET="$2"
                shift 2
                ;;
            --export)
                EXPORT_MODE=true
                shift
                ;;
            --quiet|-q)
                QUIET=true
                shift
                ;;
            --test-peer)
                TEST_PEER="$2"
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
}

show_usage() {
    cat <<'EOF'
Usage: ./01_generate_a2a_token.sh [OPTIONS]

Generate JWT token for authenticated A2A communication between ADEPT gateways.
Auto-discovers credentials from the deployment credentials directory.

Options:
  --keycloak-url <url>     Keycloak URL (default: http://keycloak:8180)
  --realm <realm>          Keycloak realm (default: master)
  --client-id <id>         Client ID (default: gateway-client)
  --client-secret <secret> Client secret (overrides auto-discovery)
  --export                 Output shell export command (for sourcing)
  --test-peer <alias>      Run authenticated connectivity test after token generation
  --quiet, -q              Minimal output (token only on stdout)
  -h, --help               Show this help message

Credential Discovery Order:
  1. --client-secret flag (highest priority)
  2. GATEWAY_CLIENT_SECRET environment variable
  3. deployment/local/docker-compose/.env-keycloak-credentials-dir/GATEWAY_CLIENT_SECRET
  4. .env-keycloak-credentials-dir/GATEWAY_CLIENT_SECRET

Examples:
  # Generate token (auto-discovers credentials)
  ./01_generate_a2a_token.sh

  # Export token for use in other scripts
  eval $(./01_generate_a2a_token.sh --export)
  echo $LOCAL_A2A_TOKEN

  # Generate token and run authenticated connectivity test
  ./01_generate_a2a_token.sh --test-peer aws-gateway

  # Quiet mode (just the token, for piping)
  ./01_generate_a2a_token.sh --quiet > /tmp/a2a_token.txt
EOF
}

# Find ADEPT project root by walking up from script directory
find_project_root() {
    local dir
    dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    # Walk up from script dir looking for Makefile
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

    # Fallback: try current working directory
    if [ -f "./Makefile" ] && [ -d "./deployment" ]; then
        pwd
        return 0
    fi

    return 1
}

# Auto-discover GATEWAY_CLIENT_SECRET from credentials directory
discover_client_secret() {
    # Priority 1: Already provided via flag or env var
    if [ -n "$CLIENT_SECRET" ]; then
        print_dim "  Using client secret from: command line / environment"
        return 0
    fi

    # Priority 2: Search credentials directories
    local project_root
    project_root=$(find_project_root 2>/dev/null || echo "")

    if [ -n "$project_root" ]; then
        # Try deployment credentials directory first
        local deploy_creds="$project_root/deployment/local/docker-compose/.env-keycloak-credentials-dir/GATEWAY_CLIENT_SECRET"
        if [ -f "$deploy_creds" ]; then
            CLIENT_SECRET=$(cat "$deploy_creds" 2>/dev/null | tr -d '[:space:]')
            if [ -n "$CLIENT_SECRET" ]; then
                print_dim "  Using client secret from: $deploy_creds"
                return 0
            fi
        fi

        # Try project-root credentials directory
        local root_creds="$project_root/.env-keycloak-credentials-dir/GATEWAY_CLIENT_SECRET"
        if [ -f "$root_creds" ]; then
            CLIENT_SECRET=$(cat "$root_creds" 2>/dev/null | tr -d '[:space:]')
            if [ -n "$CLIENT_SECRET" ]; then
                print_dim "  Using client secret from: $root_creds"
                return 0
            fi
        fi
    fi

    # Priority 3: Try relative paths from current directory
    for cred_path in "${CRED_SEARCH_PATHS[@]}"; do
        if [ -f "$cred_path" ]; then
            CLIENT_SECRET=$(cat "$cred_path" 2>/dev/null | tr -d '[:space:]')
            if [ -n "$CLIENT_SECRET" ]; then
                print_dim "  Using client secret from: $cred_path"
                return 0
            fi
        fi
    done

    return 1
}

# Validate Keycloak is accessible
validate_keycloak() {
    local health_url="${KEYCLOAK_URL}/realms/${REALM}"

    print_info "Validating Keycloak at ${KEYCLOAK_URL}..."

    local status_code
    status_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$health_url" 2>/dev/null || echo "000")

    if [ "$status_code" = "000" ]; then
        print_error "Cannot connect to Keycloak at ${KEYCLOAK_URL}"
        echo "" >&2
        echo "  Check that Keycloak is running:" >&2
        echo "    docker ps | grep keycloak" >&2
        echo "" >&2
        echo "  Verify /etc/hosts has: 127.0.0.1 keycloak" >&2
        return 1
    fi

    if [ "$status_code" != "200" ]; then
        print_error "Keycloak returned HTTP $status_code for realm '$REALM'"
        echo "" >&2
        echo "  Verify realm exists:" >&2
        echo "    curl -s ${KEYCLOAK_URL}/realms/${REALM} | python3 -m json.tool" >&2
        return 1
    fi

    print_success "Keycloak accessible (realm: $REALM)"
    return 0
}

# Generate JWT token via OAuth2 client_credentials flow
generate_token() {
    local token_endpoint="${KEYCLOAK_URL}/realms/${REALM}/protocol/openid-connect/token"

    print_info "Requesting token from ${token_endpoint}..."

    local response
    response=$(curl -s --max-time 10 \
        -X POST "$token_endpoint" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "grant_type=client_credentials" \
        -d "client_id=${CLIENT_ID}" \
        -d "client_secret=${CLIENT_SECRET}" \
        2>/dev/null)

    if [ -z "$response" ]; then
        print_error "Empty response from Keycloak token endpoint"
        return 1
    fi

    # Check for error response
    local error
    error=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('error',''))" 2>/dev/null || echo "")

    if [ -n "$error" ]; then
        local error_desc
        error_desc=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('error_description',''))" 2>/dev/null || echo "")
        print_error "Token generation failed: $error"
        [ -n "$error_desc" ] && echo "  $error_desc" >&2
        echo "" >&2
        echo "  Common causes:" >&2
        echo "    - Invalid client secret (regenerate: make fix-credentials)" >&2
        echo "    - Client '$CLIENT_ID' not configured for client_credentials flow" >&2
        echo "    - Client '$CLIENT_ID' does not exist in realm '$REALM'" >&2
        return 1
    fi

    # Extract token fields
    local access_token expires_in
    access_token=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null || echo "")
    expires_in=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('expires_in',0))" 2>/dev/null || echo "0")

    if [ -z "$access_token" ]; then
        print_error "No access_token in response"
        print_dim "  Response: ${response:0:200}"
        return 1
    fi

    # Decode and validate JWT claims
    local payload groups issuer
    payload=$(echo "$access_token" | cut -d. -f2 | tr '_-' '/+' | python3 -c "
import sys, base64, json
data = sys.stdin.read().strip()
data += '=' * (4 - len(data) % 4)
decoded = json.loads(base64.urlsafe_b64decode(data))
print(json.dumps(decoded))
" 2>/dev/null || echo "{}")

    groups=$(echo "$payload" | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin).get('groups',[])))" 2>/dev/null || echo "[]")
    issuer=$(echo "$payload" | python3 -c "import sys,json; print(json.load(sys.stdin).get('iss',''))" 2>/dev/null || echo "")
    local azp
    azp=$(echo "$payload" | python3 -c "import sys,json; print(json.load(sys.stdin).get('azp',''))" 2>/dev/null || echo "")

    # Calculate expiration
    local expires_min=$((expires_in / 60))
    local expires_at
    expires_at=$(date -d "+${expires_in} seconds" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || \
                 date -v "+${expires_in}S" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || \
                 echo "unknown")

    # Display results
    print_success "Token generated successfully"
    [ "$QUIET" = false ] && {
        echo "" >&2
        echo "  Token Details:" >&2
        echo "    Issuer:     $issuer" >&2
        echo "    Client:     $azp" >&2
        echo "    Groups:     $groups" >&2
        echo "    Expires In: ${expires_in}s (${expires_min} minutes)" >&2
        echo "    Expires At: $expires_at" >&2
        echo "    Length:     ${#access_token} chars" >&2
    }

    # Validate required groups
    if echo "$groups" | python3 -c "import sys,json; groups=json.load(sys.stdin); sys.exit(0 if 'gateway-service' in groups else 1)" 2>/dev/null; then
        print_success "Token has 'gateway-service' group (required for A2A)"
    else
        print_warning "Token missing 'gateway-service' group - A2A operations may be rejected"
    fi

    # Output based on mode
    if [ "$EXPORT_MODE" = true ]; then
        # Output export command (for eval/source)
        echo "export LOCAL_A2A_TOKEN='${access_token}'"
    elif [ "$QUIET" = true ]; then
        # Raw token only
        echo "$access_token"
    else
        # Store in variable for --test-peer
        LOCAL_A2A_TOKEN="$access_token"
        export LOCAL_A2A_TOKEN
    fi

    return 0
}

# Run authenticated connectivity test against a peer
run_authenticated_test() {
    local peer_alias="$1"

    print_section "Authenticated Connectivity Test: $peer_alias"

    if [ -z "${LOCAL_A2A_TOKEN:-}" ]; then
        print_error "LOCAL_A2A_TOKEN not set (token generation may have failed)"
        return 1
    fi

    # Find the connectivity test script
    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    local test_script="$script_dir/03_test_connectivity.sh"

    if [ ! -x "$test_script" ]; then
        print_error "Connectivity test script not found: $test_script"
        return 1
    fi

    # Run with LOCAL_A2A_TOKEN exported
    export LOCAL_A2A_TOKEN
    "$test_script" --peer-alias "$peer_alias" --verbose

    return $?
}

# Main execution
main() {
    parse_args "$@"

    print_section "A2A Token Generation"

    # Step 1: Discover credentials
    print_info "Discovering gateway client credentials..."
    if ! discover_client_secret; then
        print_error "GATEWAY_CLIENT_SECRET not found"
        echo "" >&2
        echo "  Provide the secret via one of:" >&2
        echo "    1. Flag:    --client-secret <secret>" >&2
        echo "    2. Env var: export GATEWAY_CLIENT_SECRET=<secret>" >&2
        echo "    3. File:    deployment/local/docker-compose/.env-keycloak-credentials-dir/GATEWAY_CLIENT_SECRET" >&2
        echo "" >&2
        echo "  To find the secret:" >&2
        echo "    cat deployment/local/docker-compose/.env-keycloak-credentials-dir/GATEWAY_CLIENT_SECRET" >&2
        exit 1
    fi

    # Step 2: Validate Keycloak
    if ! validate_keycloak; then
        exit 1
    fi

    # Step 3: Generate token
    [ "$QUIET" = false ] && {
        echo "" >&2
        echo "  Configuration:" >&2
        echo "    Keycloak URL: $KEYCLOAK_URL" >&2
        echo "    Realm:        $REALM" >&2
        echo "    Client ID:    $CLIENT_ID" >&2
        echo "" >&2
    }

    if ! generate_token; then
        exit 1
    fi

    # Step 4: Optionally run authenticated connectivity test
    if [ -n "$TEST_PEER" ]; then
        run_authenticated_test "$TEST_PEER"
    fi
}

# Run main function
main "$@"
