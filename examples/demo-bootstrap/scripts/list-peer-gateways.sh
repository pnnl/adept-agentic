#!/bin/bash
# Wrapper for A2A peer gateway listing

set -e

if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    echo "Usage: $0"
    echo ""
    echo "List all registered gateway peers in the A2A mesh."
    echo ""
    echo "Environment Variables:"
    echo "  PUBLIC_HOSTNAME - Gateway hostname (default: api.agentic.local)"
    echo "  GATEWAY_REGISTRY_URL - Registry URL (default: https://\${PUBLIC_HOSTNAME}/internal/registry)"
    echo "  VALIDATION_RUNNER_CLIENT_ID - Service client ID (auto-discovered from credentials dir)"
    echo "  VALIDATION_RUNNER_CLIENT_SECRET - Service client secret (auto-discovered from credentials dir)"
    echo ""
    echo "Credential auto-discovery searches:"
    echo "  1. Environment variables"
    echo "  2. deployment/local/docker-compose/.env-keycloak-credentials-dir/"
    echo "  3. .env-keycloak-credentials-dir/"
    echo "  4. /app/credentials/ (inside Docker)"
    echo ""
    echo "Examples:"
    echo "  $0"
    echo "  GATEWAY_REGISTRY_URL=http://gateway_registry:8086 $0"
    echo "  PUBLIC_HOSTNAME=vm1.api.agentic.local $0"
    exit 0
fi

# Resolve bootstrap_main.py relative to this script's location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOOTSTRAP_MAIN="${SCRIPT_DIR}/../bootstrap_main.py"

# Fallback to /app path (inside Docker container)
if [ ! -f "$BOOTSTRAP_MAIN" ]; then
    BOOTSTRAP_MAIN="/app/examples/demo-bootstrap/bootstrap_main.py"
fi

# Auto-discover credentials from files if not in environment
_discover_cred() {
    local name="$1"
    local current_val="${!name}"
    if [ -n "$current_val" ]; then
        return 0
    fi

    # Find project root
    local project_root=""
    local dir="$SCRIPT_DIR"
    for i in 1 2 3 4 5; do
        dir="$(dirname "$dir")"
        if [ -f "$dir/Makefile" ] && [ -d "$dir/deployment" ]; then
            project_root="$dir"
            break
        fi
    done

    # Search credential files
    local search_paths=(
        "${project_root}/deployment/local/docker-compose/.env-keycloak-credentials-dir/${name}"
        "${project_root}/.env-keycloak-credentials-dir/${name}"
        "/app/credentials/${name}"
    )

    for path in "${search_paths[@]}"; do
        if [ -f "$path" ]; then
            local val
            val=$(cat "$path" 2>/dev/null | tr -d '[:space:]')
            if [ -n "$val" ]; then
                export "$name"="$val"
                return 0
            fi
        fi
    done
    return 1
}

_discover_cred "VALIDATION_RUNNER_CLIENT_ID" || true
_discover_cred "VALIDATION_RUNNER_CLIENT_SECRET" || true

# Allow GATEWAY_REGISTRY_URL and PUBLIC_HOSTNAME environment variable overrides
# If neither set, A2ARegistrar will use api.agentic.local (requires /etc/hosts)
python3 "$BOOTSTRAP_MAIN" a2a-list \
    ${GATEWAY_REGISTRY_URL:+--registry-url "$GATEWAY_REGISTRY_URL"}
