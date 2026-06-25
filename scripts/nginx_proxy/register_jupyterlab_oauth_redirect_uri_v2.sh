#!/bin/bash
# Register OAuth2 Redirect URI - Python Wrapper (v2)
#
# This script is a wrapper that runs the Python implementation inside a container
# where the python-keycloak library is available.

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Default hostname if not provided
HOST=${1:-10.16.17.5}

# Run Python script inside orchestration_service container
docker exec orchestration_service python3 /app/scripts/nginx_proxy/manage_redirect_uris.py add "$HOST"
