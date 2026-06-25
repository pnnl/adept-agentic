#!/bin/bash
# register-aws-tools.sh
#
# Registers AWS MCP Server Manager meta-tools as external MCP tools on ADEPT.
#
# Prerequisites:
#   - ADEPT full stack running (Keycloak, Redis, agent_gateway, etc.)
#   - agentic CLI installed (pip install -e src/)
#   - AWS MCP Manager running and reachable from Docker containers
#   - /etc/hosts: 127.0.0.1 keycloak (for JWT issuer match on host-side CLI)
#
# Environment variables:
#   AGENT_GATEWAY_URL   — ADEPT gateway the agentic CLI registers against
#                         Default: http://localhost:8083
#   KEYCLOAK_URL        — Keycloak URL for JWT token acquisition
#                         Default: http://keycloak:8180 (Docker DNS name)
#                         CRITICAL: Must match JWT issuer claim; use service name, not localhost
#   KEYCLOAK_REALM      — Keycloak realm for auth
#                         Default: master
#   AWS_MCP_PROTO       — Protocol: http or https (default: http)
#   AWS_MCP_HOST        — MCP server hostname (default depends on protocol)
#   AWS_MCP_PORT        — MCP server port (default depends on protocol)
#   AWS_MCP_CA_CERT     — CA certificate for HTTPS verification
#   ADMIN_USER          — Admin username (default: admin)
#   ADMIN_PASS          — Admin password (default: admin)
#
# Usage:
#   ./scripts/register-aws-tools.sh              # Register all 6 tools
#   ./scripts/register-aws-tools.sh deregister    # Remove all 6 tools
#   ./scripts/register-aws-tools.sh verify        # Check Redis for tools
#   ./scripts/register-aws-tools.sh help          # Show usage

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# ADEPT gateway URL — where the agentic CLI registers tools.
export AGENT_GATEWAY_URL="${AGENT_GATEWAY_URL:-http://localhost:8083}"

# Keycloak configuration — must use Docker service name for JWT issuer match.
# The agentic CLI acquires a JWT from Keycloak; the gateway validates the issuer
# claim against http://keycloak:8180/realms/master. Using localhost would cause
# issuer mismatch. Requires /etc/hosts: 127.0.0.1 keycloak
export KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak:8180}"
export KEYCLOAK_REALM="${KEYCLOAK_REALM:-master}"

AWS_MCP_PROTO="${AWS_MCP_PROTO:-http}"
AWS_MCP_CA_CERT="${AWS_MCP_CA_CERT:-./certs/ca.crt}"
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASS="${ADMIN_PASS:-admin}"

# MCP endpoint host and port — defaults depend on protocol:
#   HTTP  → direct to MCP server (aws_mcp_manager:8003, same Docker network)
#   HTTPS → through nginx proxy (aws_mcp_nginx_proxy:443, TLS termination)
# For cross-host HTTPS, override AWS_MCP_HOST with the remote host IP.
if [ "$AWS_MCP_PROTO" = "https" ]; then
    AWS_MCP_HOST="${AWS_MCP_HOST:-aws_mcp_nginx_proxy}"
    AWS_MCP_PORT="${AWS_MCP_PORT:-443}"
else
    AWS_MCP_HOST="${AWS_MCP_HOST:-aws_mcp_manager}"
    AWS_MCP_PORT="${AWS_MCP_PORT:-8003}"
fi

MCP_URL="${AWS_MCP_PROTO}://${AWS_MCP_HOST}:${AWS_MCP_PORT}/mcp"
TOOL_PREFIX="aws_mcp"

# Docker ENGINE auto-detection
if [ -z "${ENGINE:-}" ]; then
    if docker info >/dev/null 2>&1; then
        ENGINE="docker"
    else
        echo "WARNING: Cannot connect to Docker. Some checks may fail."
        ENGINE="docker"  # fallback
    fi
fi

# Detect agentic CLI
PROJECT_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
AGENTIC_CLI=""
for candidate in \
    "${PROJECT_ROOT}/.venv311/bin/agentic" \
    "${PROJECT_ROOT}/.venv/bin/agentic" \
    "$(command -v agentic 2>/dev/null || true)"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then
        AGENTIC_CLI="$candidate"
        break
    fi
done

if [ -z "$AGENTIC_CLI" ]; then
    echo "ERROR: agentic CLI not found."
    echo "  Install: cd ${PROJECT_ROOT} && pip install -e src/"
    exit 1
fi

# Clear cached admin token if it has the wrong issuer
CACHE_FILE="${HOME}/.adept-agentic/cache/admin_token.json"
if [ -f "$CACHE_FILE" ]; then
    CACHED_ISSUER=$(python3 -c "
import json, base64, sys
try:
    with open('$CACHE_FILE') as f:
        d = json.load(f)
    parts = d['access_token'].split('.')
    payload = json.loads(base64.urlsafe_b64decode(parts[1] + '=='))
    print(payload.get('iss', ''))
except: pass
" 2>/dev/null || true)
    EXPECTED_ISSUER="${KEYCLOAK_URL}/realms/${KEYCLOAK_REALM}"
    if [ -n "$CACHED_ISSUER" ] && [ "$CACHED_ISSUER" != "$EXPECTED_ISSUER" ]; then
        echo "  Clearing stale cached token (issuer=$CACHED_ISSUER, expected=$EXPECTED_ISSUER)"
        rm -f "$CACHE_FILE"
    fi
fi

echo "Configuration:"
echo "  KEYCLOAK_URL:       ${KEYCLOAK_URL}"
echo "  AGENT_GATEWAY_URL:  ${AGENT_GATEWAY_URL}"
echo "  MCP_URL:            ${MCP_URL}"
echo "  TOOL_PREFIX:        ${TOOL_PREFIX}"
echo "  agentic CLI:        ${AGENTIC_CLI}"
echo ""

# ---------------------------------------------------------------------------
# Tool Definitions (6 meta-tools)
# ---------------------------------------------------------------------------

TOOL_COUNT=6

declare -A TOOL_NAMES
declare -A TOOL_DISPLAYS
declare -A TOOL_DESCS
declare -A TOOL_SCHEMAS

# 1. load_aws_server
TOOL_NAMES[1]="${TOOL_PREFIX}_load_server"
TOOL_DISPLAYS[1]="load_aws_server"
TOOL_DESCS[1]="Hot-load an AWS MCP server subprocess with STS temporary credentials"
TOOL_SCHEMAS[1]='{
    "request": {
        "type": "object",
        "properties": {
            "server_name": {
                "type": "string",
                "description": "Name of the AWS MCP server from the catalog (e.g. s3-tables-mcp-server)"
            }
        },
        "required": ["server_name"]
    }
}'

# 2. unload_aws_server
TOOL_NAMES[2]="${TOOL_PREFIX}_unload_server"
TOOL_DISPLAYS[2]="unload_aws_server"
TOOL_DESCS[2]="Stop an AWS MCP server subprocess and remove its tools"
TOOL_SCHEMAS[2]='{
    "request": {
        "type": "object",
        "properties": {
            "server_name": {
                "type": "string",
                "description": "Name of the server to unload"
            }
        },
        "required": ["server_name"]
    }
}'

# 3. list_available_servers
TOOL_NAMES[3]="${TOOL_PREFIX}_list_servers"
TOOL_DISPLAYS[3]="list_available_servers"
TOOL_DESCS[3]="List all AWS MCP servers in the catalog with their current load state"
TOOL_SCHEMAS[3]='{
    "request": {
        "type": "object",
        "properties": {}
    }
}'

# 4. server_status
TOOL_NAMES[4]="${TOOL_PREFIX}_server_status"
TOOL_DISPLAYS[4]="server_status"
TOOL_DESCS[4]="Get detailed status of a specific AWS MCP server"
TOOL_SCHEMAS[4]='{
    "request": {
        "type": "object",
        "properties": {
            "server_name": {
                "type": "string",
                "description": "Name of the server to query"
            }
        },
        "required": ["server_name"]
    }
}'

# 5. aws_tool_call
TOOL_NAMES[5]="${TOOL_PREFIX}_tool_call"
TOOL_DISPLAYS[5]="aws_tool_call"
TOOL_DESCS[5]="Dispatch a tool call to the correct loaded AWS MCP server subprocess"
TOOL_SCHEMAS[5]='{
    "request": {
        "type": "object",
        "properties": {
            "tool_name": {
                "type": "string",
                "description": "Qualified tool name in prefix.tool_name format (e.g. s3_tables.create_table_bucket)"
            },
            "arguments": {
                "type": "object",
                "description": "Tool arguments as a JSON object",
                "default": {}
            }
        },
        "required": ["tool_name"]
    }
}'

# 6. list_loaded_tools
TOOL_NAMES[6]="${TOOL_PREFIX}_list_tools"
TOOL_DISPLAYS[6]="list_loaded_tools"
TOOL_DESCS[6]="List all tools from all currently loaded AWS MCP servers"
TOOL_SCHEMAS[6]='{
    "request": {
        "type": "object",
        "properties": {}
    }
}'

# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------

register_tools() {
    echo "--> Registering ${TOOL_COUNT} AWS MCP Manager tools at ${MCP_URL}..."

    # Health check
    echo "  Checking health..."
    if $ENGINE exec aws_mcp_manager curl -sf http://localhost:8003/health >/dev/null 2>&1; then
        echo "  AWS MCP Manager is healthy"
    else
        echo "  WARNING: AWS MCP Manager health check failed (may not be running yet)"
    fi

    local pass=0
    local fail=0

    for i in $(seq 1 $TOOL_COUNT); do
        local name="${TOOL_NAMES[$i]}"
        local display="${TOOL_DISPLAYS[$i]}"
        local desc="${TOOL_DESCS[$i]}"
        local schema="${TOOL_SCHEMAS[$i]}"

        echo -n "  Registering ${name} (remote: ${display})... "
        if "${AGENTIC_CLI}" tools register "${name}" \
            -d "${desc}" \
            -p mcp \
            -u "${MCP_URL}" \
            --tool-name "${display}" \
            --args-schema "${schema}" \
            --username "${ADMIN_USER}" \
            --password "${ADMIN_PASS}" >/dev/null 2>&1; then
            echo "OK"
            pass=$((pass + 1))
        else
            echo "FAILED"
            fail=$((fail + 1))
        fi
    done

    echo ""
    echo "Result: ${pass}/${TOOL_COUNT} tools registered successfully"
    [ "$fail" -eq 0 ] || return 1
}

deregister_tools() {
    echo "--> Deregistering ${TOOL_COUNT} AWS MCP Manager tools..."

    local pass=0
    local fail=0
    for i in $(seq 1 $TOOL_COUNT); do
        local name="${TOOL_NAMES[$i]}"
        echo -n "  Deregistering ${name}... "
        if echo "y" | "${AGENTIC_CLI}" tools delete "${name}" \
            --username "${ADMIN_USER}" \
            --password "${ADMIN_PASS}" >/dev/null 2>&1; then
            echo "OK"
            pass=$((pass + 1))
        else
            echo "FAILED (may not exist)"
            fail=$((fail + 1))
        fi
    done

    echo ""
    echo "Result: ${pass}/${TOOL_COUNT} tools deregistered"
}

verify_tools() {
    echo "--> Verifying AWS MCP Manager tool registration in Redis..."

    # Pre-flight: check if ENGINE can reach Redis
    if ! $ENGINE exec redis redis-cli PING >/dev/null 2>&1; then
        echo ""
        echo "  WARNING: Cannot reach Redis via '$ENGINE exec redis'."
        echo "  Ensure your user is in the docker group:"
        echo "    sudo usermod -aG docker \$USER && newgrp docker"
        echo ""
        return 1
    fi

    local found=0
    local missing=0
    local schema_warnings=0

    for i in $(seq 1 $TOOL_COUNT); do
        local name="${TOOL_NAMES[$i]}"
        redis_val=$($ENGINE exec redis redis-cli GET "external_tool:${name}" 2>/dev/null || echo "")

        if [ -n "$redis_val" ] && [ "$redis_val" != "(nil)" ]; then
            if echo "$redis_val" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('args_schema') is not None" 2>/dev/null; then
                echo "  + ${name} found in Redis (with args_schema)"
            else
                echo "  ~ ${name} found in Redis (WARNING: missing args_schema)"
                schema_warnings=$((schema_warnings + 1))
            fi
            found=$((found + 1))
        else
            echo "  - ${name} NOT found in Redis"
            missing=$((missing + 1))
        fi
    done

    echo ""
    echo "Result: ${found}/${TOOL_COUNT} tools verified in Redis"
    if [ "$schema_warnings" -gt 0 ]; then
        echo "WARNING: ${schema_warnings} tool(s) missing args_schema. Re-register with: make register-tools"
    fi
    [ "$missing" -eq 0 ] || return 1
}

show_usage() {
    echo "Usage: $0 [register|deregister|verify|help]"
    echo ""
    echo "Commands:"
    echo "  register    Register all ${TOOL_COUNT} AWS MCP tools with ADEPT (default)"
    echo "  deregister  Remove all ${TOOL_COUNT} AWS MCP tools from ADEPT"
    echo "  verify      Check that tools exist in Redis"
    echo "  help        Show this message"
    echo ""
    echo "Environment:"
    echo "  KEYCLOAK_URL             (default: http://keycloak:8180) MUST use Docker service name"
    echo "  KEYCLOAK_REALM           (default: master) Keycloak realm"
    echo "  AGENT_GATEWAY_URL        (default: http://localhost:8083) Gateway URL"
    echo "  AWS_MCP_PROTO            (default: http) Protocol: http or https"
    echo "  AWS_MCP_HOST             (http default: aws_mcp_manager, https default: aws_mcp_nginx_proxy)"
    echo "  AWS_MCP_PORT             (http default: 8003, https default: 443)"
    echo "  AWS_MCP_CA_CERT          (default: ./certs/ca.crt) CA cert for HTTPS verification"
    echo "  ADMIN_USER               (default: admin) ADEPT admin username"
    echo "  ADMIN_PASS               (default: admin) ADEPT admin password"
    echo "  ENGINE                   (default: docker) Docker engine command"
    echo ""
    echo "IMPORTANT: /etc/hosts must contain:"
    echo "  127.0.0.1 keycloak agent_gateway gateway_registry redis orchestration_service"
    echo ""
    echo "This ensures the agentic CLI can reach Keycloak using the Docker service name,"
    echo "producing JWT tokens with the correct issuer (http://keycloak:8180/realms/master)"
    echo "that the gateway will accept."
    echo ""
    echo "Examples:"
    echo "  $0 register                                                  # HTTP direct to MCP server"
    echo "  AWS_MCP_PROTO=https $0 register                              # HTTPS via nginx proxy"
    echo "  AWS_MCP_PROTO=https AWS_MCP_HOST=10.0.1.50 $0 register       # HTTPS cross-host"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

ACTION="${1:-register}"

case "$ACTION" in
    register)
        register_tools
        echo ""
        verify_tools
        ;;
    deregister)
        deregister_tools
        ;;
    verify)
        verify_tools
        ;;
    help|--help|-h)
        show_usage
        ;;
    *)
        echo "Unknown action: ${ACTION}"
        show_usage
        exit 1
        ;;
esac
