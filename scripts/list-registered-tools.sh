#!/bin/bash
# list-registered-tools.sh
#
# Lists all external MCP tools registered with the ADEPT core tool registry.
# Uses validation-runner-client credentials (client_credentials grant) via
# the orchestration_service container to get a token with the correct issuer.
#
# Usage:
#   ./scripts/list-registered-tools.sh            # Table output
#   ./scripts/list-registered-tools.sh --json      # Raw JSON output
#
# Prerequisites:
#   - ADEPT core stack running (keycloak, agent_gateway, orchestration_service)
#   - Credential files in deployment/local/docker-compose/.env-keycloak-credentials-dir/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

CRED_DIR="${PROJECT_ROOT}/deployment/local/docker-compose/.env-keycloak-credentials-dir"
KEYCLOAK_REALM="${KEYCLOAK_REALM:-master}"
KEYCLOAK_INTERNAL_URL="${KEYCLOAK_INTERNAL_URL:-http://keycloak:8180}"
AGENT_GATEWAY_URL="${AGENT_GATEWAY_URL:-http://localhost:8083}"
OUTPUT_FORMAT="${1:-table}"

# ---------------------------------------------------------------------------
# 1. Read credential
# ---------------------------------------------------------------------------
if [ ! -f "${CRED_DIR}/VALIDATION_RUNNER_CLIENT_SECRET" ]; then
    echo "ERROR: Credential file not found: ${CRED_DIR}/VALIDATION_RUNNER_CLIENT_SECRET" >&2
    echo "  Run: make sync-credentials" >&2
    exit 1
fi

VR_SECRET=$(cat "${CRED_DIR}/VALIDATION_RUNNER_CLIENT_SECRET")

# ---------------------------------------------------------------------------
# 2. Get token (via orchestration_service to get correct issuer)
# ---------------------------------------------------------------------------
TOKEN=$(docker exec orchestration_service curl -s -X POST \
    "${KEYCLOAK_INTERNAL_URL}/realms/${KEYCLOAK_REALM}/protocol/openid-connect/token" \
    -d "grant_type=client_credentials" \
    -d "client_id=validation-runner-client" \
    -d "client_secret=${VR_SECRET}" \
    | python3 -c 'import sys,json;d=json.load(sys.stdin);t=d.get("access_token","");print(t)' 2>/dev/null)

if [ -z "${TOKEN}" ]; then
    echo "ERROR: Failed to get Keycloak token." >&2
    echo "  Is the ADEPT core stack running? (make start)" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# 3. Query tool registry
# ---------------------------------------------------------------------------
RESPONSE=$(curl -s -H "Authorization: Bearer ${TOKEN}" "${AGENT_GATEWAY_URL}/v1/tools/list")

# ---------------------------------------------------------------------------
# 4. Format output
# ---------------------------------------------------------------------------
if [ "${OUTPUT_FORMAT}" = "--json" ]; then
    echo "${RESPONSE}" | python3 -m json.tool
else
    echo "${RESPONSE}" | python3 -c "
import sys, json

data = json.load(sys.stdin)

if isinstance(data, dict) and 'detail' in data:
    print(f'ERROR: {data[\"detail\"]}', file=sys.stderr)
    sys.exit(1)

print(f'Registered external MCP tools: {len(data)}')
print('-' * 70)
print(f'{\"#\":>3}  {\"Tool Name\":<45} {\"Description\":<60}')
print('-' * 70)
for i, t in enumerate(data, 1):
    name = t.get('name', '?')
    desc = t.get('description', '')[:60]
    print(f'{i:3d}  {name:<45} {desc}')
print('-' * 70)
"
fi
