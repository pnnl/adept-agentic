#!/bin/bash

# Volume Migration Script - Migrate from Docker volumes to bind mounts
# This script helps migrate data from Docker-managed volumes to the local data/ directory

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get the script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DATA_DIR="${PROJECT_ROOT}/data"

echo -e "${GREEN}Volume Migration Script${NC}"
echo -e "${GREEN}========================${NC}"
echo "This script will migrate data from Docker-managed volumes to ${DATA_DIR}"
echo

# Function to check if Docker volume exists
volume_exists() {
    docker volume ls -q | grep -q "^$1$"
}

# Function to migrate a volume
migrate_volume() {
    local volume_name=$1
    local target_dir=$2
    local description=$3

    echo -e "${YELLOW}Processing: ${description}${NC}"

    # Check if volume exists
    if ! volume_exists "$volume_name"; then
        echo "  Volume $volume_name does not exist, skipping..."
        return
    fi

    # Create target directory if it doesn't exist
    if [ ! -d "$target_dir" ]; then
        echo "  Creating directory: $target_dir"
        mkdir -p "$target_dir"
    fi

    # Check if target directory already has data
    if [ "$(ls -A "$target_dir" 2>/dev/null | grep -v '.gitkeep')" ]; then
        echo -e "  ${YELLOW}Warning: $target_dir already contains data${NC}"
        read -p "  Overwrite existing data? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "  Skipping migration for $volume_name"
            return
        fi
    fi

    # Create a temporary container to copy data
    echo "  Copying data from volume to $target_dir..."
    docker run --rm \
        -v "$volume_name:/source:ro" \
        -v "$target_dir:/target" \
        alpine sh -c "cp -a /source/. /target/ 2>/dev/null || true"

    echo -e "  ${GREEN}✓ Migration complete for $volume_name${NC}"
}

# Get list of possible project names
echo "Detecting Docker Compose project names..."
POSSIBLE_PROJECTS=$(docker volume ls --format "{{.Name}}" | sed 's/_.*$//' | sort -u)

if [ -z "$POSSIBLE_PROJECTS" ]; then
    echo -e "${RED}No Docker volumes found. Are services running?${NC}"
    exit 1
fi

echo "Found the following project names:"
echo "$POSSIBLE_PROJECTS" | while read -r project; do
    echo "  - $project"
done
echo

# Ask user to select or enter project name
read -p "Enter your Docker Compose project name (or press Enter for 'chapter-06-advanced-multi-agent-orchestration'): " PROJECT_NAME
PROJECT_NAME=${PROJECT_NAME:-chapter-06-advanced-multi-agent-orchestration}

echo
echo "Using project name: $PROJECT_NAME"
echo

# Confirm before proceeding
echo -e "${YELLOW}This script will migrate the following volumes:${NC}"
echo "  - ${PROJECT_NAME}_shared_uploads -> ${DATA_DIR}/uploaded_files"
echo "  - ${PROJECT_NAME}_postgres_data -> ${DATA_DIR}/postgres_data"
echo "  - ${PROJECT_NAME}_nginx_certs -> ${DATA_DIR}/nginx_certs"
echo "  - ${PROJECT_NAME}_n8n_data -> ${DATA_DIR}/n8n_data"
echo "  - ${PROJECT_NAME}_openwebui_data -> ${DATA_DIR}/openwebui_data"
echo "  - ${PROJECT_NAME}_sandbox_workspace -> ${DATA_DIR}/sandbox_workspace"
echo "  - ${PROJECT_NAME}_mgmt_ui_data -> ${DATA_DIR}/mgmt_ui_data"
echo "  - ${PROJECT_NAME}_ragflow_data -> ${DATA_DIR}/ragflow_data"
echo "  - ${PROJECT_NAME}_ragflow_sessions -> ${DATA_DIR}/ragflow_sessions"
echo

read -p "Continue with migration? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Migration cancelled"
    exit 0
fi

echo
echo "Starting migration..."
echo

# Migrate each volume
migrate_volume "${PROJECT_NAME}_shared_uploads" "${DATA_DIR}/uploaded_files" "Shared uploads"
migrate_volume "${PROJECT_NAME}_postgres_data" "${DATA_DIR}/postgres_data/pgdata" "PostgreSQL data"
migrate_volume "${PROJECT_NAME}_nginx_certs" "${DATA_DIR}/nginx_certs" "NGINX certificates"
migrate_volume "${PROJECT_NAME}_n8n_data" "${DATA_DIR}/n8n_data" "n8n data"
migrate_volume "${PROJECT_NAME}_openwebui_data" "${DATA_DIR}/openwebui_data" "OpenWebUI data"
migrate_volume "${PROJECT_NAME}_sandbox_workspace" "${DATA_DIR}/sandbox_workspace" "Sandbox workspace"
migrate_volume "${PROJECT_NAME}_mgmt_ui_data" "${DATA_DIR}/mgmt_ui_data" "Management UI data"
migrate_volume "${PROJECT_NAME}_ragflow_data" "${DATA_DIR}/ragflow_data" "RAGFlow data"
migrate_volume "${PROJECT_NAME}_ragflow_sessions" "${DATA_DIR}/ragflow_sessions" "RAGFlow sessions"

# Fix permissions
echo
echo "Fixing file permissions..."
chown -R $(id -u):$(id -g) "${DATA_DIR}"
find "${DATA_DIR}" -type d -exec chmod 755 {} \;
find "${DATA_DIR}" -type f -exec chmod 644 {} \;

echo
echo -e "${GREEN}Migration complete!${NC}"
echo
echo "Next steps:"
echo "1. Stop all services: make stop"
echo "2. Remove old Docker volumes (optional): docker volume prune"
echo "3. Start services with new volume configuration: make start"
echo
echo -e "${YELLOW}Note: The new volume configuration uses bind mounts to ${DATA_DIR}${NC}"
echo -e "${YELLOW}Make sure to backup this directory regularly!${NC}"