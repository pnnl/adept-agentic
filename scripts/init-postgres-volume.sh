#!/bin/bash

# Initialize PostgreSQL volume with correct permissions for bind mount
# This script sets up the postgres data directory with the subdirectory pattern
# as recommended by PostgreSQL documentation

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Get the script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# PostgreSQL directories
POSTGRES_DIR="${PROJECT_ROOT}/data/postgres_data"
PGDATA_DIR="${PROJECT_ROOT}/data/postgres_data/pgdata"

echo -e "${GREEN}PostgreSQL Volume Initialization${NC}"
echo -e "${GREEN}==================================${NC}"
echo

# Check if running with sufficient permissions
if [ "$EUID" -ne 0 ] && [ -z "$SUDO_USER" ]; then
    echo -e "${YELLOW}Warning: This script may need sudo permissions to set ownership to UID 999 (postgres)${NC}"
    echo "If permission errors occur, please run with: sudo $0"
    echo
fi

# Create directories
echo "Creating PostgreSQL directories..."
mkdir -p "$POSTGRES_DIR"
mkdir -p "$PGDATA_DIR"

# Set ownership
# UID 999 is the postgres user inside the container
echo "Setting ownership to postgres user (UID 999)..."
if command -v sudo >/dev/null 2>&1; then
    sudo chown -R 999:999 "$POSTGRES_DIR"
else
    chown -R 999:999 "$POSTGRES_DIR" 2>/dev/null || {
        echo -e "${YELLOW}Warning: Could not set ownership. You may need to run with sudo.${NC}"
    }
fi

# Set permissions
echo "Setting permissions (700)..."
chmod 700 "$POSTGRES_DIR"
chmod 700 "$PGDATA_DIR"

# Remove any .gitkeep files that might interfere
if [ -f "$POSTGRES_DIR/.gitkeep" ]; then
    echo "Removing .gitkeep file..."
    rm -f "$POSTGRES_DIR/.gitkeep"
fi
if [ -f "$PGDATA_DIR/.gitkeep" ]; then
    rm -f "$PGDATA_DIR/.gitkeep"
fi

# Verify setup
echo
echo "Verification:"
echo "-------------"
ls -la "$POSTGRES_DIR" | head -2
echo "└── pgdata/"
ls -la "$PGDATA_DIR" 2>/dev/null | head -2 || echo "    (empty - ready for PostgreSQL initialization)"

echo
echo -e "${GREEN}✓ PostgreSQL volume initialized successfully${NC}"
echo
echo "The PostgreSQL data directory is now ready for use."
echo "PostgreSQL will initialize its database in: $PGDATA_DIR"
echo
echo "Next steps:"
echo "1. Start the services: make start"
echo "2. PostgreSQL will automatically initialize on first run"
echo "3. Check logs if needed: docker logs postgres"