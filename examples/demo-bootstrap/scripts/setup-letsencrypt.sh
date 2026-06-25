#!/bin/bash
# Wrapper for Let's Encrypt certificate generation

set -e

HOSTNAME="${1}"
EMAIL="${2:-admin@example.com}"
CHALLENGE="${3:-dns}"

if [ -z "$HOSTNAME" ]; then
    echo "Usage: $0 <hostname> [email] [dns|http]"
    echo ""
    echo "Examples:"
    echo "  $0 vm1.api.agentic.local admin@example.com dns"
    echo "  $0 vm2.api.agentic.local admin@example.com http"
    exit 1
fi

# Resolve bootstrap_main.py relative to this script's location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOOTSTRAP_MAIN="${SCRIPT_DIR}/../bootstrap_main.py"

# Fallback to /app path (inside Docker container)
if [ ! -f "$BOOTSTRAP_MAIN" ]; then
    BOOTSTRAP_MAIN="/app/examples/demo-bootstrap/bootstrap_main.py"
fi

python3 "$BOOTSTRAP_MAIN" letsencrypt \
    --hostname "$HOSTNAME" \
    --email "$EMAIL" \
    --challenge "$CHALLENGE"
