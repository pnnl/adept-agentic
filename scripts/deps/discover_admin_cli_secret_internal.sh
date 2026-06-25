#!/bin/bash
# scripts/deps/discover_admin_cli_secret_internal.sh
# Internal script used by keycloak-setup service to discover admin-cli secret
# Reads PostgreSQL credentials from environment variables (no hardcoded passwords)

set -e

# Read PostgreSQL connection details from environment
POSTGRES_HOST="${POSTGRES_HOST:-postgres}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_USER="${POSTGRES_USER:-admin}"
POSTGRES_DB="${POSTGRES_DB:-keycloak}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD}"

# Validate required environment variables
if [ -z "$POSTGRES_PASSWORD" ]; then
  echo "ERROR: POSTGRES_PASSWORD environment variable not set" >&2
  exit 1
fi

# Install postgresql-client if not present (silent, idempotent)
apt-get update -qq > /dev/null 2>&1 || true
apt-get install -y -qq postgresql-client > /dev/null 2>&1 || true

# Query admin-cli secret from Keycloak database
# Use PGPASSWORD environment variable (standard PostgreSQL auth method)
export PGPASSWORD="$POSTGRES_PASSWORD"

KC_ADMIN_CLI_SECRET=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "SELECT secret FROM client WHERE client_id = 'admin-cli' AND realm_id = (SELECT id FROM realm WHERE name = 'master');" \
  -t -A 2>/dev/null | tr -d ' \n')

# Unset PGPASSWORD for security
unset PGPASSWORD

# Validate secret was found
if [ -z "$KC_ADMIN_CLI_SECRET" ]; then
  echo "ERROR: Could not find admin-cli secret in Keycloak database" >&2
  exit 1
fi

# Return the secret (stdout for capture by docker-compose command)
echo "$KC_ADMIN_CLI_SECRET"
