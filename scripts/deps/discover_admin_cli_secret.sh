#!/bin/bash
# scripts/deps/discover_admin_cli_secret.sh
# Discovers the admin-cli client secret from Keycloak's PostgreSQL database
# This secret is required for bootstrap_keycloak.py to authenticate with Keycloak
#
# Usage: Run from project root with proper .env file present

set -e

# Color output for better visibility
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}==> Discovering admin-cli client secret from Keycloak database...${NC}"

# Check if postgres container is running
if ! docker ps --format '{{.Names}}' | grep -q "^postgres$"; then
  echo -e "${RED}ERROR: PostgreSQL container is not running${NC}"
  echo "Please start the stack first: make start"
  exit 1
fi

# Load PostgreSQL credentials from .env
if [ -f .env ]; then
  export $(grep -v '^#' .env | grep 'POSTGRES_' | xargs)
fi

# Set defaults if not in .env
POSTGRES_USER="${POSTGRES_USER:-admin}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-password}"

# Query the admin-cli secret from the database
# Use environment variables instead of hardcoded credentials
ADMIN_CLI_SECRET=$(docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" postgres \
  psql -U "$POSTGRES_USER" -d keycloak \
  -c "SELECT secret FROM client WHERE client_id = 'admin-cli' AND realm_id = (SELECT id FROM realm WHERE name = 'master');" \
  -t -A 2>/dev/null | tr -d ' \n')

# Check if secret was found
if [ -z "$ADMIN_CLI_SECRET" ]; then
  echo -e "${RED}ERROR: Could not find admin-cli secret in Keycloak database${NC}"
  echo ""
  echo "Possible causes:"
  echo "1. Keycloak has not been initialized yet"
  echo "2. Database schema is incorrect"
  echo "3. PostgreSQL connection failed"
  echo "4. POSTGRES_USER or POSTGRES_PASSWORD incorrect in .env"
  echo ""
  echo "Try running: make start"
  exit 1
fi

echo -e "${GREEN}✅ Successfully discovered admin-cli secret${NC}"
echo ""
echo -e "${YELLOW}Add this line to your .env file:${NC}"
echo "KC_ADMIN_CLI_SECRET=${ADMIN_CLI_SECRET}"
echo ""
echo -e "${YELLOW}Or append it automatically:${NC}"
echo "echo 'KC_ADMIN_CLI_SECRET=${ADMIN_CLI_SECRET}' >> .env"

# Return the secret for programmatic use
echo ""
echo "KC_ADMIN_CLI_SECRET=${ADMIN_CLI_SECRET}"
