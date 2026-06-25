#!/bin/bash
#
# ADEPT A2A Workshop - Step 7: OpenTrons A2A Delegation
#
# Purpose: From the REQUESTING host (no OpenTrons), delegate a protocol
#          execution request to a peer gateway that has the "Opentrons"
#          capability. Demonstrates real multi-host A2A task delegation.
#
# Usage:   ./07_opentrons_a2a_delegation.sh [OPTIONS]
#
# Exit codes:
#   0 - Delegation succeeded
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
PEER_ALIAS=""
DRY_RUN=true

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
            --peer-alias)
                PEER_ALIAS="$2"
                shift 2
                ;;
            --registry-url)
                REGISTRY_URL="$2"
                shift 2
                ;;
            --keycloak-url)
                KEYCLOAK_URL="$2"
                shift 2
                ;;
            --execute)
                DRY_RUN=false
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
Usage: ./07_opentrons_a2a_delegation.sh [OPTIONS]

Delegate OpenTrons protocol execution to a peer gateway via A2A.

Options:
  --peer-alias <alias>    Peer gateway alias (auto-discovered if not specified)
  --registry-url <url>    Gateway Registry URL (default: http://gateway_registry:8086)
  --keycloak-url <url>    Keycloak URL (default: http://keycloak:8180)
  --execute               Execute protocol (default: dry-run/validation only)
  -h, --help              Show this help message

Examples:
  # Auto-discover peer with Opentrons capability and delegate (dry run)
  ./07_opentrons_a2a_delegation.sh

  # Delegate to specific peer
  ./07_opentrons_a2a_delegation.sh --peer-alias azure-gateway

  # Execute protocol (not just validate)
  ./07_opentrons_a2a_delegation.sh --peer-alias azure-gateway --execute
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
        return 1
    fi

    local error
    error=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('error',''))" 2>/dev/null || echo "")

    if [ -n "$error" ]; then
        return 1
    fi

    echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null
}

# Get user token (notebook-user) for delegation
get_user_token() {
    local token_url="${KEYCLOAK_URL}/realms/${REALM}/protocol/openid-connect/token"

    local response
    response=$(curl -s --max-time 10 \
        -X POST "$token_url" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "grant_type=password" \
        -d "client_id=login-client" \
        -d "username=notebook-user" \
        -d "password=notebook-password" \
        -d "scope=openid profile email" \
        2>/dev/null)

    if [ -z "$response" ]; then
        return 1
    fi

    local error
    error=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('error',''))" 2>/dev/null || echo "")

    if [ -n "$error" ]; then
        return 1
    fi

    echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null
}

# Query gateway registry for peers with Opentrons capability
find_opentrons_peer() {
    local token="$1"

    local response
    response=$(curl -s --max-time 10 \
        -H "Authorization: Bearer $token" \
        -H "Content-Type: application/json" \
        "${REGISTRY_URL}/v1/gateways/" 2>/dev/null)

    if [ -z "$response" ]; then
        return 1
    fi

    # Find gateway with Opentrons capability (pipe via stdin to avoid quoting issues)
    echo "$response" | python3 -c "
import sys, json
gateways = json.load(sys.stdin)
for gw in gateways:
    caps = gw.get('capabilities', [])
    for cap in caps:
        if isinstance(cap, str) and 'Opentrons' in cap:
            print(json.dumps(gw))
            sys.exit(0)
        if isinstance(cap, dict) and 'Opentrons' in str(cap):
            print(json.dumps(gw))
            sys.exit(0)
sys.exit(1)
" 2>/dev/null
}

# Find specific peer by alias (uses specific endpoint GET /v1/gateways/{alias})
find_peer_by_alias() {
    local token="$1"
    local alias="$2"

    local response
    response=$(curl -s --max-time 10 \
        -H "Authorization: Bearer $token" \
        -H "Content-Type: application/json" \
        "${REGISTRY_URL}/v1/gateways/${alias}" 2>/dev/null)

    if [ -z "$response" ]; then
        return 1
    fi

    # Verify the response contains an alias field (not an error)
    echo "$response" | python3 -c "
import sys, json
gw = json.load(sys.stdin)
if gw.get('alias'):
    print(json.dumps(gw))
    sys.exit(0)
sys.exit(1)
" 2>/dev/null
}

# Construct sample OpenTrons protocol
build_sample_protocol() {
    python3 -c "
import json
protocol = {
    'protocol_name': 'A2A Workshop - Cross-Host Transfer Protocol',
    'protocol_version': '1.0',
    'plate_type': '96-well',
    'transfers': [
        {
            'source_well': 'A1',
            'dest_well': 'B1',
            'volume_ul': 50.0,
            'tip_type': 'p300_single'
        },
        {
            'source_well': 'A2',
            'dest_well': 'B2',
            'volume_ul': 100.0,
            'tip_type': 'p300_single'
        },
        {
            'source_well': 'A3',
            'dest_well': 'B3',
            'volume_ul': 75.0,
            'tip_type': 'p300_single'
        }
    ]
}
print(json.dumps(protocol))
" 2>/dev/null
}

# Perform A2A delegation via SendMessage
#
# The A2AExecutor (a2a_executor.py:87-98) expects a data part with:
#   {task: <str>, user_token: <JWT>, multi_gateway_session_id: <uuid>}
#
# The executor forwards the "task" text to the orchestration service's
# Response API (/v1/responses/completions), where the ScientificWorkflowAgent
# processes it using its available tools (built-in + dynamically registered).
#
# The peer_url from the registry is the gateway's public_url (e.g.
# "https://10.16.17.5/v1"). The A2A endpoint is at /a2a/ on the gateway,
# so we must strip /v1 and append /a2a/.
perform_delegation() {
    local peer_url="$1"
    local s2s_token="$2"
    local user_token="$3"
    local protocol_json="$4"
    local dry_run="$5"

    # Derive the A2A endpoint from the peer's public_url
    # Strip trailing /v1 or /v1/ if present, then append /a2a/
    local a2a_endpoint
    a2a_endpoint=$(echo "$peer_url" | sed 's|/v1/*$||')
    a2a_endpoint="${a2a_endpoint%/}/a2a/"

    # Generate a multi-gateway session ID for cross-gateway correlation
    local mg_session_id
    mg_session_id="mg-$(python3 -c 'import uuid; print(uuid.uuid4().hex[:16])')"

    # Build task text: natural language instruction with embedded protocol JSON
    local mode_label
    if [ "$dry_run" = true ]; then
        mode_label="dry-run (validation only)"
    else
        mode_label="simulation"
    fi

    # Build A2A SendMessage request with the format A2AExecutor expects
    local message_payload
    message_payload=$(python3 -c "
import json, sys, uuid

protocol = json.loads(sys.stdin.read())

# Compose natural-language task with embedded protocol JSON
task_text = (
    'Execute the following OpenTrons liquid handling protocol in $mode_label mode. '
    'Use the execute_opentrons_protocol tool with the protocol JSON below '
    'and dry_run=$([ \"$dry_run\" = true ] && echo \"true\" || echo \"false\").\n\n'
    'Protocol JSON:\n'
    '\`\`\`json\n'
    + json.dumps(protocol, indent=2)
    + '\n\`\`\`'
)

send_message = {
    'jsonrpc': '2.0',
    'method': 'message/send',
    'id': str(uuid.uuid4()),
    'params': {
        'message': {
            'messageId': str(uuid.uuid4()),
            'role': 'user',
            'parts': [
                {
                    'kind': 'data',
                    'data': {
                        'task': task_text,
                        'user_token': '$user_token',
                        'multi_gateway_session_id': '$mg_session_id'
                    }
                }
            ]
        }
    }
}
print(json.dumps(send_message))
" <<< "$protocol_json" 2>/dev/null)

    if [ -z "$message_payload" ]; then
        print_error "Failed to construct A2A message"
        return 1
    fi

    print_dim "  A2A endpoint: $a2a_endpoint"
    print_dim "  Session ID:   $mg_session_id"
    print_dim "  Dry run:      $dry_run"
    echo ""

    # Send A2A request
    # Authorization: S2S gateway-client token (authenticates calling gateway)
    local response
    response=$(curl -s --max-time 60 -k \
        -X POST "$a2a_endpoint" \
        -H "Authorization: Bearer $s2s_token" \
        -H "Content-Type: application/json" \
        -d "$message_payload" \
        2>/dev/null)

    if [ -z "$response" ]; then
        print_error "Empty response from peer gateway"
        return 1
    fi

    # Check for JSON-RPC error
    local rpc_error
    rpc_error=$(echo "$response" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if 'error' in data:
        print(json.dumps(data['error']))
    else:
        print('')
except:
    print('')
" 2>/dev/null || echo "")

    if [ -n "$rpc_error" ]; then
        print_error "A2A delegation returned error"
        echo "  Error: $rpc_error"
        return 1
    fi

    echo "$response"
    return 0
}

# Main execution
main() {
    parse_args "$@"

    print_section "A2A OpenTrons Protocol Delegation"

    # Step 1: Get S2S token
    print_info "Obtaining S2S authentication token..."
    local s2s_token
    s2s_token=$(get_s2s_token) || {
        print_error "Failed to get S2S token"
        echo ""
        echo "  Check GATEWAY_CLIENT_SECRET is available"
        exit 1
    }
    print_success "S2S token obtained"

    # Step 2: Find peer with Opentrons capability
    local peer_info=""
    local peer_url=""
    local peer_alias_found=""

    if [ -n "$PEER_ALIAS" ]; then
        print_info "Looking up peer: $PEER_ALIAS..."
        peer_info=$(find_peer_by_alias "$s2s_token" "$PEER_ALIAS") || {
            print_error "Peer '$PEER_ALIAS' not found in registry"
            echo ""
            echo "  List registered peers:"
            echo "    curl -H 'Authorization: Bearer \$TOKEN' ${REGISTRY_URL}/v1/gateways | python3 -m json.tool"
            exit 1
        }
        peer_alias_found="$PEER_ALIAS"
    else
        print_info "Discovering peer with Opentrons capability..."
        peer_info=$(find_opentrons_peer "$s2s_token") || {
            print_error "No peer with Opentrons capability found in registry"
            echo ""
            echo "  On the OpenTrons host, run:"
            echo "    ./06_register_opentrons_capability.sh"
            echo ""
            echo "  Or specify peer explicitly:"
            echo "    $0 --peer-alias <alias>"
            exit 1
        }
        peer_alias_found=$(echo "$peer_info" | python3 -c "import sys,json; print(json.load(sys.stdin).get('alias','unknown'))" 2>/dev/null)
    fi

    peer_url=$(echo "$peer_info" | python3 -c "import sys,json; print(json.load(sys.stdin).get('public_url',''))" 2>/dev/null)

    if [ -z "$peer_url" ]; then
        print_error "Could not determine peer URL"
        exit 1
    fi

    print_success "Found peer: $peer_alias_found"
    print_dim "  URL: $peer_url"

    # Display peer capabilities
    local caps
    caps=$(echo "$peer_info" | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin).get('capabilities',[]), indent=2))" 2>/dev/null || echo "[]")
    print_dim "  Capabilities: $caps"

    # Step 3: Get user token for delegation
    print_info "Obtaining user token (notebook-user)..."
    local user_token
    user_token=$(get_user_token) || {
        print_error "Failed to get user token"
        exit 1
    }
    print_success "User token obtained"

    # Step 4: Build sample protocol
    print_info "Building sample OpenTrons protocol..."
    local protocol_json
    protocol_json=$(build_sample_protocol)
    echo ""
    echo "  Protocol: A2A Workshop - Cross-Host Transfer Protocol"
    echo "  Transfers: 3 (A1→B1 50μL, A2→B2 100μL, A3→B3 75μL)"
    echo "  Mode: $([ "$DRY_RUN" = true ] && echo "Dry Run (validation only)" || echo "Execute (simulation)")"

    # Step 5: Perform A2A delegation
    echo ""
    print_section "Delegating to Peer: $peer_alias_found"

    local response
    response=$(perform_delegation "$peer_url" "$s2s_token" "$user_token" "$protocol_json" "$DRY_RUN") || {
        print_error "A2A delegation failed"
        echo ""
        echo "  Troubleshooting:"
        echo "    - Verify peer is reachable: curl -k $peer_url"
        echo "    - Check SSRF ALLOWED_PEER_CIDRS includes peer IP"
        echo "    - Verify OpenTrons server on peer: curl http://<peer_ip>:9003/health"
        exit 1
    }

    # Step 6: Display results
    print_section "Delegation Result"
    echo ""

    echo "$response" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(json.dumps(data, indent=2))
except:
    print(sys.stdin.read())
" 2>/dev/null || echo "$response"

    echo ""
    print_success "A2A OpenTrons delegation completed successfully"
    echo ""
    echo "  Summary:"
    echo "    Peer:      $peer_alias_found ($peer_url)"
    echo "    Protocol:  A2A Workshop - Cross-Host Transfer Protocol"
    echo "    Mode:      $([ "$DRY_RUN" = true ] && echo "Dry Run" || echo "Execute")"
    echo "    Transfers: 3"
    echo ""

    if [ "$DRY_RUN" = true ]; then
        echo "  To execute the protocol (simulation mode):"
        echo "    $0 --peer-alias $peer_alias_found --execute"
    fi

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Alternative: SDK CLI & Streamlit UI Prompts"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "  SDK CLI (from inside Docker network):"
    echo "    agentic a2a list-peers --registry-url http://gateway_registry:8086"
    echo "    agentic a2a test-connection $peer_alias_found --registry-url http://gateway_registry:8086"
    echo ""
    echo "  Streamlit UI Prompt (paste into chat):"
    echo "    \"I need to run an OpenTrons liquid handling protocol on the remote"
    echo "     lab gateway ($peer_alias_found). The protocol should transfer 50μL"
    echo "     from A1→B1, 100μL from A2→B2, and 75μL from A3→B3 using p300_single"
    echo "     tips on a 96-well plate. Please run it in dry-run mode first.\""
    echo ""
    echo "  Advanced Streamlit Prompt (with explicit protocol JSON):"
    cat <<'PROMPT'
    "Execute this OpenTrons protocol via A2A delegation:
    {
      "protocol_name": "Cross-Host Transfer Protocol",
      "plate_type": "96-well",
      "transfers": [
        {"source_well": "A1", "dest_well": "B1", "volume_ul": 50.0, "tip_type": "p300_single"},
        {"source_well": "A2", "dest_well": "B2", "volume_ul": 100.0, "tip_type": "p300_single"},
        {"source_well": "A3", "dest_well": "B3", "volume_ul": 75.0, "tip_type": "p300_single"}
      ]
    }"
PROMPT
}

# Run main function
main "$@"
