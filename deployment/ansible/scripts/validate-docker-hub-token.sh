#!/bin/bash
# Validate Docker Hub token freshness by attempting a real manifest fetch.
# Returns structured output: DOCKER_HUB_AUTH_CHECK:<status>
#
# Statuses:
#   200       - Token valid, manifest fetch succeeded
#   401|403   - Token expired or revoked
#   5xx       - Docker Hub gateway issue (transient)
#   TOKEN_FETCH_FAILED - Could not obtain anonymous token from auth.docker.io
#
# Usage:
#   ./scripts/validate-docker-hub-token.sh
#   # Output: DOCKER_HUB_AUTH_CHECK:200

set -o pipefail

CONNECT_TIMEOUT=${CONNECT_TIMEOUT:-5}
MAX_TIME=${MAX_TIME:-10}

TOKEN=$(curl -s \
  "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/ubuntu:pull" \
  --connect-timeout "$CONNECT_TIMEOUT" --max-time "$MAX_TIME" 2>/dev/null \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))" 2>/dev/null)

if [ -n "$TOKEN" ]; then
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $TOKEN" \
    "https://registry-1.docker.io/v2/library/ubuntu/manifests/22.04" \
    --connect-timeout "$CONNECT_TIMEOUT" --max-time "$MAX_TIME" 2>/dev/null)
  echo "DOCKER_HUB_AUTH_CHECK:$HTTP_CODE"
else
  echo "DOCKER_HUB_AUTH_CHECK:TOKEN_FETCH_FAILED"
fi
