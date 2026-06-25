#!/usr/bin/env bash
# =============================================================================
# bootstrap-jwt.sh — Extract HMAC key from Slurm cluster + generate service JWT
#
# This script:
#   1. Waits for slurmctld to be healthy
#   2. Extracts the base64-encoded HMAC key from slurmdbd
#   3. Generates a service JWT token via slurmctld
#   4. Auto-detects the API version from slurmrestd
#   5. Writes SLURM_JWT_KEY, SLURM_SERVICE_JWT, SLURM_API_VERSION to .env
#
# Usage:
#   ./scripts/bootstrap-jwt.sh
#   # or: make bootstrap-jwt
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${PROJECT_DIR}/.env"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}=== Slurm JWT Bootstrap ===${NC}"

# --- Step 1: Wait for slurmctld health ---
echo -e "${YELLOW}[1/5] Waiting for slurmctld to be healthy...${NC}"
MAX_WAIT=120
WAITED=0
while ! docker exec slurmctld scontrol ping 2>/dev/null | grep -q "UP"; do
    if [ "$WAITED" -ge "$MAX_WAIT" ]; then
        echo -e "${RED}ERROR: slurmctld did not become healthy within ${MAX_WAIT}s${NC}"
        exit 1
    fi
    sleep 2
    WAITED=$((WAITED + 2))
done
echo "  slurmctld is healthy (waited ${WAITED}s)"

# --- Step 2: Extract HMAC key from slurmdbd ---
echo -e "${YELLOW}[2/5] Extracting HMAC key from slurmdbd...${NC}"
JWT_KEY=$(docker exec slurmdbd base64 -w 0 /etc/slurm/jwt_hs256.key 2>/dev/null)
if [ -z "$JWT_KEY" ]; then
    echo -e "${RED}ERROR: Failed to extract JWT key from slurmdbd${NC}"
    echo "  Ensure slurmdbd has created /etc/slurm/jwt_hs256.key"
    exit 1
fi
echo "  HMAC key extracted (${#JWT_KEY} chars, base64-encoded)"

# --- Step 3: Generate service JWT ---
echo -e "${YELLOW}[3/5] Generating service JWT token...${NC}"
SERVICE_JWT=$(docker exec slurmctld scontrol token lifespan=86400 2>/dev/null | grep -oP 'SLURM_JWT=\K.*')
if [ -z "$SERVICE_JWT" ]; then
    echo -e "${YELLOW}  WARNING: Could not generate service JWT (will rely on HMAC key)${NC}"
    SERVICE_JWT=""
else
    echo "  Service JWT generated (24h lifespan, ${#SERVICE_JWT} chars)"
fi

# --- Step 4: Auto-detect API version ---
echo -e "${YELLOW}[4/5] Detecting slurmrestd API version...${NC}"
API_VERSION=""
# Try common versions
for ver in "v0.0.41" "v0.0.40" "v0.0.39"; do
    if docker exec slurmrestd curl -sf "http://localhost:6820/slurm/${ver}/ping" >/dev/null 2>&1; then
        API_VERSION="${ver}"
        break
    fi
done
if [ -z "$API_VERSION" ]; then
    API_VERSION="v0.0.41"
    echo -e "${YELLOW}  Could not auto-detect, defaulting to ${API_VERSION}${NC}"
else
    echo "  Detected API version: ${API_VERSION}"
fi

# --- Step 5: Write to .env ---
echo -e "${YELLOW}[5/5] Writing credentials to .env...${NC}"

# Create .env if it doesn't exist
touch "$ENV_FILE"

# Function to update or add a key in .env
update_env() {
    local key="$1"
    local value="$2"
    if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
        # Update existing
        sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
    else
        # Add new
        echo "${key}=${value}" >> "$ENV_FILE"
    fi
}

update_env "SLURM_JWT_KEY" "$JWT_KEY"
update_env "SLURM_SERVICE_JWT" "$SERVICE_JWT"
update_env "SLURM_API_VERSION" "$API_VERSION"

echo ""
echo -e "${GREEN}=== Bootstrap Complete ===${NC}"
echo "  SLURM_JWT_KEY    = ${JWT_KEY:0:20}... (${#JWT_KEY} chars)"
if [ -n "$SERVICE_JWT" ]; then
    echo "  SLURM_SERVICE_JWT = ${SERVICE_JWT:0:20}... (${#SERVICE_JWT} chars)"
else
    echo "  SLURM_SERVICE_JWT = (not set, using HMAC key)"
fi
echo "  SLURM_API_VERSION = ${API_VERSION}"
echo ""
echo "  Written to: ${ENV_FILE}"
echo "  Next: run 'make restart-mcp' to apply credentials"
