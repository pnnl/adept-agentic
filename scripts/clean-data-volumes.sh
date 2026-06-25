#!/bin/bash
# Clean Data Volumes Script
# Safely removes all data from data/ directory while preserving .gitkeep files and directory structure

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DATA_DIR="$PROJECT_ROOT/data"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}================================${NC}"
echo -e "${YELLOW}Data Volumes Cleanup Script${NC}"
echo -e "${YELLOW}================================${NC}"
echo

# Safety check - ensure we're in the right directory
if [ ! -d "$DATA_DIR" ]; then
    echo -e "${RED}ERROR: data/ directory not found at $DATA_DIR${NC}"
    exit 1
fi

if [ ! -f "$PROJECT_ROOT/docker-compose.base.yaml" ]; then
    echo -e "${RED}ERROR: Not in project root (docker-compose.base.yaml not found)${NC}"
    exit 1
fi

echo -e "${YELLOW}This script will:${NC}"
echo "  1. Remove ALL files and subdirectories in data/"
echo "  2. Preserve .gitkeep files and directory structure"
echo "  3. Reset file permissions to host user ownership"
echo
echo -e "${YELLOW}Data directory: $DATA_DIR${NC}"
echo

# List what will be cleaned
echo -e "${YELLOW}Directories that will be cleaned:${NC}"
find "$DATA_DIR" -mindepth 1 -maxdepth 1 -type d | while read -r dir; do
    file_count=$(find "$dir" -type f ! -name '.gitkeep' 2>/dev/null | wc -l)
    dir_count=$(find "$dir" -mindepth 1 -type d 2>/dev/null | wc -l)
    echo "  - $(basename "$dir"): $file_count files, $dir_count subdirectories"
done
echo

# Confirmation prompt
read -p "$(echo -e ${YELLOW}Are you sure you want to clean all data? This cannot be undone! [y/N]: ${NC})" -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${GREEN}Cleanup cancelled.${NC}"
    exit 0
fi

echo
echo -e "${GREEN}Starting cleanup...${NC}"

# Function to clean a directory
clean_directory() {
    local dir="$1"
    local dir_name=$(basename "$dir")

    if [ ! -d "$dir" ]; then
        echo -e "  ${YELLOW}⚠ Directory not found: $dir_name${NC}"
        return
    fi

    echo -e "  ${GREEN}→${NC} Cleaning $dir_name..."

    # Count files before
    local before_files=$(find "$dir" -type f ! -name '.gitkeep' 2>/dev/null | wc -l)
    local before_dirs=$(find "$dir" -mindepth 1 -type d 2>/dev/null | wc -l)

    # Remove all files except .gitkeep
    find "$dir" -type f ! -name '.gitkeep' -delete 2>/dev/null || true

    # Remove all directories (this will leave parent dirs with .gitkeep)
    find "$dir" -mindepth 1 -type d -empty -delete 2>/dev/null || true

    # Count files after
    local after_files=$(find "$dir" -type f ! -name '.gitkeep' 2>/dev/null | wc -l)
    local gitkeep_count=$(find "$dir" -type f -name '.gitkeep' 2>/dev/null | wc -l)

    echo -e "    Removed: $before_files files, $before_dirs directories"
    echo -e "    Preserved: $gitkeep_count .gitkeep files"
}

# Clean specific data directories
echo
echo -e "${GREEN}Cleaning data directories...${NC}"

# Core data directories
clean_directory "$DATA_DIR/uploaded_files"
clean_directory "$DATA_DIR/rag_indexes"
clean_directory "$DATA_DIR/vector_db_persistence"
clean_directory "$DATA_DIR/persistent_chroma_db"
clean_directory "$DATA_DIR/sql_databases"

# RAGFlow directories
clean_directory "$DATA_DIR/ragflow_data"
clean_directory "$DATA_DIR/ragflow_sessions"
clean_directory "$DATA_DIR/ragflow_models"
clean_directory "$DATA_DIR/ragflow_embeddings"

# MCP workspace directories
clean_directory "$DATA_DIR/sandbox_workspace"
clean_directory "$DATA_DIR/hpc_workspace"

# Clean any other top-level directories in data/
for dir in "$DATA_DIR"/*; do
    if [ -d "$dir" ]; then
        dir_name=$(basename "$dir")
        case "$dir_name" in
            uploaded_files|rag_indexes|vector_db_persistence|persistent_chroma_db|sql_databases|ragflow_data|ragflow_sessions|ragflow_models|ragflow_embeddings|sandbox_workspace|hpc_workspace)
                # Already cleaned above
                ;;
            *)
                # Clean any other directories
                clean_directory "$dir"
                ;;
        esac
    fi
done

echo
echo -e "${GREEN}Fixing permissions...${NC}"

# Fix ownership to host user
if [ "$(id -u)" != "0" ]; then
    # Running as non-root, just chmod
    chmod -R 755 "$DATA_DIR" 2>/dev/null || true
    echo -e "  ${GREEN}✓${NC} Set directory permissions to 755"
else
    # Running as root, chown to user 1000 (standard non-root user)
    chown -R 1000:1000 "$DATA_DIR" 2>/dev/null || true
    chmod -R 755 "$DATA_DIR" 2>/dev/null || true
    echo -e "  ${GREEN}✓${NC} Set ownership to UID 1000 and permissions to 755"
fi

# Verify cleanup
echo
echo -e "${GREEN}Cleanup Summary:${NC}"
remaining_files=$(find "$DATA_DIR" -type f ! -name '.gitkeep' 2>/dev/null | wc -l)
gitkeep_files=$(find "$DATA_DIR" -type f -name '.gitkeep' 2>/dev/null | wc -l)
directories=$(find "$DATA_DIR" -type d 2>/dev/null | wc -l)

echo "  - Remaining data files: $remaining_files"
echo "  - Preserved .gitkeep files: $gitkeep_files"
echo "  - Total directories: $directories"

if [ "$remaining_files" -gt 0 ]; then
    echo
    echo -e "${YELLOW}Warning: Some files could not be removed:${NC}"
    find "$DATA_DIR" -type f ! -name '.gitkeep' 2>/dev/null | head -10
    if [ "$remaining_files" -gt 10 ]; then
        echo "  ... and $((remaining_files - 10)) more files"
    fi
fi

echo
echo -e "${GREEN}✓ Data cleanup complete!${NC}"
echo
echo -e "${YELLOW}Next steps:${NC}"
echo "  1. Restart services: make restart"
echo "  2. Or rebuild from scratch: make erase && make start"
echo "  3. All checkpoint data has been cleared"
echo
