#!/bin/bash
#
# ADEPT A2A Workshop - Step 6: Register OpenTrons Capability
#
# Purpose: Register the current gateway with the "Opentrons" capability tag
#          in the Gateway Registry. This is the ephemeral/dynamic registration
#          prework for A2A task delegation.
#
# Usage:   ./06_register_opentrons_capability.sh [OPTIONS]
#
# Exit codes:
#   0 - Capability registered successfully
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
REGISTRY_URL="${GATEWAY_REGISTRY_URL:-http://gateway_registry:8086}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak:8180}"
REALM="${KEYCLOAK_REALM:-master}"
GATEWAY_ALIAS="${AGENT_GATEWAY_ALIAS:-}"
OPENTRONS_URL="http://localhost:9003"

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
            --registry-url)
                REGISTRY_URL="$2"
                shift 2
                ;;
            --keycloak-url)
                KEYCLOAK_URL="$2"
                shift 2
                ;;
            --gateway-alias)
                GATEWAY_ALIAS="$2"
                shift 2
                ;;
            --opentrons-url)
                OPENTRONS_URL="$2"
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
Usage: ./06_register_opentrons_capability.sh [OPTIONS]

Register the current gateway with the "Opentrons" capability tag.

Options:
  --registry-url <url>    Gateway Registry URL (default: http://gateway_registry:8086)
  --keycloak-url <url>    Keycloak URL (default: http://keycloak:8180)
  --gateway-alias <alias> Gateway alias (auto-detected from AGENT_GATEWAY_ALIAS)
  --opentrons-url <url>   OpenTrons server URL for health check (default: http://localhost:9003)
  -h, --help              Show this help message

Examples:
  # Register with auto-detection
  ./06_register_opentrons_capability.sh

  # Register with explicit alias
  ./06_register_opentrons_capability.sh --gateway-alias my-gateway
EOF
}

# Find ADEPT project root
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

# Discover client secret for S2S token
discover_client_secret() {
    # Check env var first
    if [ -n "${GATEWAY_CLIENT_SECRET:-}" ]; then
        echo "$GATEWAY_CLIENT_SECRET"
        return 0
    fi

    local project_root
    project_root=$(find_project_root 2>/dev/null || echo "")

    if [ -n "$project_root" ]; then
        local cred_file="$project_root/deployment/local/docker-compose/.env-keycloak-credentials-dir/GATEWAY_CLIENT_SECRET"
        if [ -f "$cred_file" ]; then
            cat "$cred_file" 2>/dev/null | tr -d '[:space:]'
            return 0
        fi

        cred_file="$project_root/.env-keycloak-credentials-dir/GATEWAY_CLIENT_SECRET"
        if [ -f "$cred_file" ]; then
            cat "$cred_file" 2>/dev/null | tr -d '[:space:]'
            return 0
        fi
    fi

    return 1
}

# Get S2S token from Keycloak
get_s2s_token() {
    local client_id="${GATEWAY_CLIENT_ID:-gateway-client}"
    local client_secret

    client_secret=$(discover_client_secret) || {
        print_error "Cannot discover GATEWAY_CLIENT_SECRET"
        echo "  Set GATEWAY_CLIENT_SECRET env var or check credentials directory" >&2
        return 1
    }

    local token_url="${KEYCLOAK_URL}/realms/${REALM}/protocol/openid-connect/token"

    local response
    response=$(curl -s --max-time 10 \
        -X POST "$token_url" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "grant_type=client_credentials" \
        -d "client_id=${client_id}" \
        -d "client_secret=${client_secret}" \
        2>/dev/null)

    if [ -z "$response" ]; then
        print_error "Empty response from Keycloak"
        return 1
    fi

    local error
    error=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('error',''))" 2>/dev/null || echo "")

    if [ -n "$error" ]; then
        print_error "Token request failed: $error"
        return 1
    fi

    echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null
}

# Get admin ROPC token from Keycloak
# Tool registration endpoints (POST /v1/tools/register, POST /admin/tools/register)
# require the "admin" role, which the gateway-client S2S token does not have.
# This function uses Resource Owner Password Credentials grant with the admin user.
get_admin_token() {
    local admin_user="${ADMIN_USERNAME:-admin}"
    local admin_pass="${ADMIN_PASSWORD:-admin}"
    local token_url="${KEYCLOAK_URL}/realms/${REALM}/protocol/openid-connect/token"

    # Use login-client (public OIDC client with ROPC enabled).
    # Unlike admin-cli, login-client includes user claims (sub, groups,
    # preferred_username) which the agent_gateway requires for auth.
    local response
    response=$(curl -s --max-time 10 -X POST "$token_url" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "grant_type=password" \
        -d "client_id=login-client" \
        -d "username=${admin_user}" \
        -d "password=${admin_pass}" 2>/dev/null)

    if [ -z "$response" ]; then
        return 1
    fi

    local error
    error=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('error',''))" 2>/dev/null || echo "")

    if [ -n "$error" ]; then
        print_dim "  Admin token error: $error"
        return 1
    fi

    echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null
}

# Detect gateway alias
detect_gateway_alias() {
    if [ -n "$GATEWAY_ALIAS" ]; then
        echo "$GATEWAY_ALIAS"
        return 0
    fi

    # Try to read from environment (set by docker-compose)
    if [ -n "${AGENT_GATEWAY_ALIAS:-}" ]; then
        echo "$AGENT_GATEWAY_ALIAS"
        return 0
    fi

    # Try reading from .env file
    local project_root
    project_root=$(find_project_root 2>/dev/null || echo "")

    if [ -n "$project_root" ] && [ -f "$project_root/.env" ]; then
        local alias
        alias=$(grep '^AGENT_GATEWAY_ALIAS=' "$project_root/.env" 2>/dev/null | cut -d= -f2 | tr -d '"' | tr -d "'")
        if [ -n "$alias" ]; then
            echo "$alias"
            return 0
        fi
    fi

    return 1
}

# Verify OpenTrons server is healthy
verify_opentrons_health() {
    print_info "Verifying OpenTrons MCP server health..."

    local status
    status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
        "${OPENTRONS_URL}/health" 2>/dev/null || echo "000")

    if [ "$status" = "200" ]; then
        print_success "OpenTrons MCP server is healthy"
        return 0
    fi

    print_error "OpenTrons MCP server is not healthy (HTTP $status)"
    echo ""
    echo "  Start the server first:"
    echo "    ./05_start_opentrons_server.sh"
    return 1
}

# Get current gateway registration from registry
get_current_registration() {
    local token="$1"
    local alias="$2"

    local response
    response=$(curl -s --max-time 10 \
        -H "Authorization: Bearer $token" \
        -H "Content-Type: application/json" \
        "${REGISTRY_URL}/v1/gateways/${alias}" 2>/dev/null)

    if [ -z "$response" ]; then
        echo ""
        return 1
    fi

    # Check if we got an error (404 = not found)
    local has_alias
    has_alias=$(echo "$response" | python3 -c "
import sys, json
gw = json.load(sys.stdin)
if gw.get('alias'):
    print(json.dumps(gw))
" 2>/dev/null || echo "")

    if [ -n "$has_alias" ]; then
        echo "$has_alias"
    else
        echo ""
    fi
}

# Register or update gateway with Opentrons capability
register_opentrons_capability() {
    local token="$1"
    local alias="$2"

    # Get current registration
    local current
    current=$(get_current_registration "$token" "$alias")

    if [ -z "$current" ]; then
        print_warning "Gateway '$alias' not found in registry"
        echo ""
        echo "  The gateway must be registered first. Registering now..."

        # Detect project root (needed for .env lookups below)
        local project_root
        project_root=$(find_project_root 2>/dev/null || echo "")

        # Detect public URL
        local public_url="${PUBLIC_GATEWAY_URL:-}"
        if [ -z "$public_url" ]; then
            if [ -n "$project_root" ] && [ -f "$project_root/.env" ]; then
                public_url=$(grep '^PUBLIC_GATEWAY_URL=' "$project_root/.env" 2>/dev/null | cut -d= -f2 | tr -d '"' | tr -d "'")
            fi
        fi

        # SSRF fallback: if PUBLIC_GATEWAY_URL contains localhost, the registry
        # will reject it. Fall back to PUBLIC_BASE_URL (the host's external IP/domain).
        if [ -n "$public_url" ] && echo "$public_url" | grep -qi 'localhost'; then
            print_warning "PUBLIC_GATEWAY_URL contains 'localhost' — registry SSRF check will reject it"
            local base_url="${PUBLIC_BASE_URL:-}"
            if [ -z "$base_url" ] && [ -n "$project_root" ] && [ -f "$project_root/.env" ]; then
                base_url=$(grep '^PUBLIC_BASE_URL=' "$project_root/.env" 2>/dev/null | cut -d= -f2 | tr -d '"' | tr -d "'")
            fi
            if [ -n "$base_url" ]; then
                public_url="${base_url%/}/v1"
                print_info "  Falling back to PUBLIC_BASE_URL: $public_url"
            fi
        fi

        if [ -z "$public_url" ]; then
            print_error "Cannot determine PUBLIC_GATEWAY_URL"
            echo "  Set PUBLIC_GATEWAY_URL env var or check .env file"
            return 1
        fi

        local a2a_url="${public_url%/}/a2a"

        # Register with Opentrons capability
        local payload
        payload=$(python3 -c "
import json
print(json.dumps({
    'alias': '$alias',
    'public_url': '$a2a_url',
    'capabilities': ['RAG', 'HPC-BLAST', 'CodeExecution', 'Opentrons']
}))
" 2>/dev/null)

        local response
        response=$(curl -s --max-time 10 \
            -X POST \
            -H "Authorization: Bearer $token" \
            -H "Content-Type: application/json" \
            -d "$payload" \
            "${REGISTRY_URL}/v1/gateways" 2>/dev/null)

        local status_code
        status_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
            -X POST \
            -H "Authorization: Bearer $token" \
            -H "Content-Type: application/json" \
            -d "$payload" \
            "${REGISTRY_URL}/v1/gateways" 2>/dev/null || echo "000")

        if [ "$status_code" = "200" ] || [ "$status_code" = "201" ]; then
            print_success "Gateway registered with Opentrons capability"
            return 0
        fi

        print_error "Failed to register gateway (HTTP $status_code)"
        print_dim "  Response: $response"
        return 1
    fi

    # Gateway exists — check if Opentrons capability already present
    local has_opentrons
    has_opentrons=$(echo "$current" | python3 -c "
import sys, json
gw = json.load(sys.stdin)
caps = gw.get('capabilities', [])
# Check both string capabilities and tagged capabilities
for cap in caps:
    if isinstance(cap, str) and 'Opentrons' in cap:
        print('true')
        sys.exit(0)
    if isinstance(cap, dict) and 'Opentrons' in str(cap):
        print('true')
        sys.exit(0)
print('false')
" 2>/dev/null || echo "false")

    if [ "$has_opentrons" = "true" ]; then
        print_success "Gateway '$alias' already has Opentrons capability"
        return 0
    fi

    # Update registration: re-register with Opentrons added to capabilities
    local public_url
    public_url=$(echo "$current" | python3 -c "import sys,json; print(json.load(sys.stdin).get('public_url',''))" 2>/dev/null)

    local existing_caps
    existing_caps=$(echo "$current" | python3 -c "
import sys, json
gw = json.load(sys.stdin)
caps = gw.get('capabilities', [])
caps.append('Opentrons')
print(json.dumps(caps))
" 2>/dev/null)

    local payload
    payload=$(python3 -c "
import json
print(json.dumps({
    'alias': '$alias',
    'public_url': '$public_url',
    'capabilities': $existing_caps
}))
" 2>/dev/null)

    local response
    response=$(curl -s --max-time 10 \
        -X POST \
        -H "Authorization: Bearer $token" \
        -H "Content-Type: application/json" \
        -d "$payload" \
        "${REGISTRY_URL}/v1/gateways" 2>/dev/null)

    # Check response
    local resp_alias
    resp_alias=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('alias',''))" 2>/dev/null || echo "")

    if [ -n "$resp_alias" ]; then
        print_success "Updated gateway '$alias' with Opentrons capability"
        return 0
    fi

    print_error "Failed to update gateway capabilities"
    print_dim "  Response: $response"
    return 1
}

# Register OpenTrons MCP tool as an external tool in the orchestration service
#
# This makes execute_opentrons_protocol available to the ScientificWorkflowAgent
# so that A2A-delegated tasks can invoke it.
#
# Registration endpoint: POST /v1/tools/register (proxied by agent_gateway)
# NOTE: Requires admin role — S2S gateway-client token is insufficient.
register_opentrons_external_tool() {
    local s2s_token="$1"

    # Tool registration requires admin role — get an admin ROPC token
    local token
    token=$(get_admin_token) || {
        print_warning "Could not get admin token; trying S2S token as fallback"
        token="$s2s_token"
    }

    # The OpenTrons MCP server runs on port 9003 (container network).
    # IMPORTANT: The URL MUST include the /mcp path. FastMCP Client passes the URL
    # directly to StreamableHttpTransport — it does NOT auto-append /mcp.
    # Without /mcp, the client POSTs to "/" which returns 404.
    local opentrons_base="${OPENTRONS_URL:-http://opentrons_mcp_server:9003}"
    local opentrons_tool_url="${opentrons_base%/}/mcp"

    # Build tool registration payload.
    # Uses MCP protocol — FastMCP Client handles initialize + tools/call JSON-RPC.
    #
    # The OpenTrons MCP server uses a Pydantic model (ProtocolSchema) for input
    # validation with Union[ProtocolSchema, dict] type annotation, so FastMCP
    # generates a rich JSON schema (with nested TransferSchema, field constraints,
    # and enums) exposed via tools/list. The args_schema here is a simplified version
    # for the ExternalToolManager's StructuredTool wrapper on the orchestration side.
    local tool_config
    tool_config=$(python3 -c "
import json
config = {
    'name': 'execute_opentrons_protocol',
    'description': 'Execute an OpenTrons liquid handling protocol on a robot or simulator. Validates and executes liquid transfer protocols on OT-2 robots. Supports 96-well and 384-well plates with p10, p20, p300, and p1000 pipettes. Runs in dry-run (validation only) mode by default.',
    'args_schema': {
        'protocol_json': {
            'type': 'object',
            'description': 'Protocol specification with protocol_name (string, required), plate_type (96-well or 384-well, default: 96-well), and transfers array of objects with source_well (A1-H12), dest_well (A1-H12), volume_ul (0.1-1000), tip_type (p10_single|p20_single|p300_single|p1000_single)'
        },
        'dry_run': {
            'type': 'boolean',
            'description': 'If true, validates the protocol without executing on hardware. Default: true',
            'default': True
        }
    },
    'invocation': {
        'protocol': 'mcp',
        'connection': {
            'url': '${opentrons_tool_url}',
            'tool_name': 'execute_opentrons_protocol_tool'
        }
    },
    'acl': {
        'global': True
    }
}
print(json.dumps(config))
" 2>/dev/null)

    if [ -z "$tool_config" ]; then
        print_warning "Failed to construct tool registration payload"
        return 1
    fi

    # Try registering via the agent gateway (port 8083 from host, port 8081 from Docker)
    local gateway_url="${AGENT_GATEWAY_URL:-http://agent_gateway:8081}"

    local response
    response=$(curl -s --max-time 10 \
        -X POST \
        -H "Authorization: Bearer $token" \
        -H "Content-Type: application/json" \
        -d "$tool_config" \
        "${gateway_url}/v1/tools/register" 2>/dev/null)

    local status_code
    status_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
        -X POST \
        -H "Authorization: Bearer $token" \
        -H "Content-Type: application/json" \
        -d "$tool_config" \
        "${gateway_url}/v1/tools/register" 2>/dev/null || echo "000")

    if [ "$status_code" = "200" ] || [ "$status_code" = "201" ]; then
        print_success "OpenTrons tool registered as external MCP tool"
        return 0
    fi

    # If gateway registration fails, try direct to orchestration service
    local orch_url="${ORCHESTRATION_SERVICE_URL:-http://orchestration_service:8084}"

    status_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
        -X POST \
        -H "Authorization: Bearer $token" \
        -H "Content-Type: application/json" \
        -d "$tool_config" \
        "${orch_url}/admin/tools/register" 2>/dev/null || echo "000")

    if [ "$status_code" = "200" ] || [ "$status_code" = "201" ]; then
        print_success "OpenTrons tool registered as external MCP tool (via orchestration service)"
        return 0
    fi

    print_warning "External tool registration returned HTTP $status_code (non-fatal)"
    print_dim "  The tool may still be accessible if the OpenTrons MCP server is connected"
    print_dim "  to the orchestration service's MCP tool discovery."
    return 0  # Non-fatal — the A2A task text approach will still work
}

# Main execution
main() {
    parse_args "$@"

    print_section "Register Opentrons Capability"

    # Step 1: Detect gateway alias
    print_info "Detecting gateway alias..."
    local alias
    alias=$(detect_gateway_alias) || {
        print_error "Cannot detect gateway alias"
        echo ""
        echo "  Set AGENT_GATEWAY_ALIAS or use --gateway-alias flag"
        exit 1
    }
    print_success "Gateway alias: $alias"

    # Step 2: Verify OpenTrons server is healthy
    if ! verify_opentrons_health; then
        exit 1
    fi

    # Step 3: Get S2S token
    print_info "Obtaining S2S authentication token..."
    local token
    token=$(get_s2s_token) || {
        print_error "Failed to get S2S token"
        exit 1
    }
    print_success "S2S token obtained"

    # Step 4: Register capability in gateway registry
    print_info "Registering Opentrons capability in gateway registry..."
    if ! register_opentrons_capability "$token" "$alias"; then
        exit 1
    fi

    # Step 5: Register OpenTrons tool as external MCP tool
    print_info "Registering execute_opentrons_protocol as external tool..."
    register_opentrons_external_tool "$token"

    # Step 6: Verify
    echo ""
    print_info "Verifying registration..."
    local current
    current=$(get_current_registration "$token" "$alias")

    if [ -n "$current" ]; then
        echo ""
        echo "  Gateway Registration:"
        echo "$current" | python3 -m json.tool 2>/dev/null || echo "  $current"
    fi

    echo ""
    print_section "Opentrons Capability Registered"
    echo ""
    print_success "Gateway '$alias' now advertises Opentrons capability"
    print_success "Remote hosts can discover and delegate OpenTrons tasks via A2A"
    echo ""
    echo "  Next step (on the REQUESTING host):"
    echo "    ./07_opentrons_a2a_delegation.sh --peer-alias $alias"
    echo ""
    echo "  Verify tool registration:"
    echo "    curl -s -H 'Authorization: Bearer \$TOKEN' http://localhost:8083/v1/tools/list | python3 -m json.tool"
    echo ""
    echo "  Alternative — register/manage tools via agentic CLI:"
    echo "    agentic tools register execute_opentrons_protocol \\"
    echo "      -d 'Execute an OpenTrons liquid handling protocol...' \\"
    echo "      -p mcp -u http://opentrons_mcp_server:9003/mcp \\"
    echo "      --tool-name execute_opentrons_protocol_tool \\"
    echo "      --args-schema '{...}' --username admin --password admin"
    echo ""
    echo "  SDK CLI (list peers):"
    echo "    agentic a2a list-peers --registry-url http://gateway_registry:8086"
}

# Run main function
main "$@"
