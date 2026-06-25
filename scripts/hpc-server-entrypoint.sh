#!/bin/bash
# Entrypoint script for hpc_mcp_server
# Handles runtime permissions for HPC workspace directory
# Ensures Nextflow pipelines can write temporary files and results

set -e

# Function to setup directory with proper permissions
setup_directory() {
    local dir="$1"
    local name="$2"

    if [ ! -d "$dir" ]; then
        echo "🔧 Creating $name directory at $dir..."
        mkdir -p "$dir"
    fi

    echo "🔧 Setting permissions for $name..."
    chown -R appuser:appgroup "$dir"
    chmod -R 777 "$dir"
    echo "✅ $name directory configured"
}

# Fix permissions for HPC workspace directory
if [ -d "/app/data/hpc_workspace" ]; then
    echo "🔧 Setting up HPC workspace..."
    setup_directory "/app/data/hpc_workspace" "HPC workspace"
    echo "✅ HPC workspace configured"
else
    echo "⚠️ /app/data/hpc_workspace not mounted - Nextflow will use temp directories only"
fi

# Debug: Show user context and directory permissions
echo "📊 Debug: Current user context"
echo "   - UID: $(id -u)"
echo "   - GID: $(id -g)"
echo "   - User: $(whoami)"

if [ -d "/app/data/hpc_workspace" ]; then
    echo "📊 Debug: HPC workspace permissions"
    ls -la /app/data/hpc_workspace/ | head -5
fi

# Drop privileges and run the main application as appuser
echo "🚀 Starting hpc_mcp_server as appuser..."
exec gosu appuser "$@"
