#!/bin/bash
# Entrypoint script for mcp_server
# Ensures all required data directories exist before starting the app.
#
# Security: This script runs as appuser (non-root). The host-side quick-start
# script (scripts/quick-start-adept-and-subsystems.sh) sets up directory
# permissions (chmod a+rwx) during stack bootstrap. No chown/chmod needed here.

set -e

# Ensure required data directories exist (mkdir -p works on 777 parent dirs)
if [ -d "/app/data" ]; then
    echo "Setting up MCP data directories..."

    for dir in \
        /app/data/rag_indexes \
        /app/data/uploaded_files \
        /app/data/vector_db_persistence \
        /app/data/sql_databases \
        /app/data/persistent_chroma_db
    do
        mkdir -p "$dir" 2>/dev/null || true
    done

    echo "MCP data directories ready"
else
    echo "WARNING: /app/data volume not mounted"
fi

echo "Starting mcp_server as $(whoami) (UID=$(id -u))"
exec "$@"