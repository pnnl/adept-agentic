#!/bin/bash
# Initialize shared volume permissions for Docker-in-Docker compatibility
# This script ensures the shared volume always has proper permissions
# Works on both AWS (ubuntu user) and Azure (azureuser) environments

set -e

# Detect the current user and their primary group
CURRENT_USER="${USER:-$(whoami)}"
CURRENT_GROUP="$(id -g)"
CURRENT_UID="$(id -u)"
CURRENT_GID="$(id -g)"

# Get the project name from the current directory name
PROJECT_DIR="$(pwd)"
PROJECT_NAME="$(basename "$PROJECT_DIR")"

# Construct the shared volume path based on the project name
# Docker Compose uses the project directory name as the project prefix
SHARED_VOLUME_PATH="/var/lib/docker/volumes/${PROJECT_NAME}_shared_uploads/_data"

echo "🔧 Initializing shared volume permissions..."
echo "📋 Environment Details:"
echo "   User: ${CURRENT_USER} (UID: ${CURRENT_UID})"
echo "   Group: ${CURRENT_GROUP} (GID: ${CURRENT_GID})"
echo "   Project: ${PROJECT_NAME}"
echo "   Volume Path: ${SHARED_VOLUME_PATH}"

# Create required data directories for Docker bind mounts
echo "📁 Creating required data directories for bind mounts..."
mkdir -p "${PROJECT_DIR}/data/postgres_data" \
         "${PROJECT_DIR}/data/postgres_rag_data" \
         "${PROJECT_DIR}/data/redis_data" \
         "${PROJECT_DIR}/data/nginx_certs" \
         "${PROJECT_DIR}/data/n8n_data" \
         "${PROJECT_DIR}/data/openwebui_data" \
         "${PROJECT_DIR}/data/mgmt_ui_data" \
         "${PROJECT_DIR}/data/uploaded_files" \
         "${PROJECT_DIR}/data/sandbox_workspace" \
         "${PROJECT_DIR}/data/ragflow" \
         "${PROJECT_DIR}/data/ragflow_data" \
         "${PROJECT_DIR}/data/ragflow_sessions" \
         "${PROJECT_DIR}/data/hpc_workspace" \
         "${PROJECT_DIR}/data/langfuse" \
         "${PROJECT_DIR}/data/vector_db_persistence"
echo "   ✅ Created local bind mount directories"

# Fix permissions on bind mount subdirectories (created with restrictive umask)
echo "🔐 Setting bind mount subdirectory permissions..."
chmod a+rwx "${PROJECT_DIR}/data/postgres_data" \
            "${PROJECT_DIR}/data/postgres_rag_data" \
            "${PROJECT_DIR}/data/redis_data" \
            "${PROJECT_DIR}/data/nginx_certs" \
            "${PROJECT_DIR}/data/n8n_data" \
            "${PROJECT_DIR}/data/openwebui_data" \
            "${PROJECT_DIR}/data/mgmt_ui_data" \
            "${PROJECT_DIR}/data/uploaded_files" \
            "${PROJECT_DIR}/data/sandbox_workspace" \
            "${PROJECT_DIR}/data/ragflow" \
            "${PROJECT_DIR}/data/ragflow_data" \
            "${PROJECT_DIR}/data/ragflow_sessions" \
            "${PROJECT_DIR}/data/hpc_workspace" \
            "${PROJECT_DIR}/data/langfuse" \
            "${PROJECT_DIR}/data/vector_db_persistence" 2>/dev/null || {
    echo "  ⚠️  Could not fix bind mount subdirectory permissions"
}
echo "   ✅ Fixed bind mount subdirectory permissions"

# Fix data/ directory permissions for Docker container access
echo "🔐 Setting data/ directory permissions for container access..."
if chmod a+rwx "${PROJECT_DIR}/data" 2>/dev/null; then
    echo "   ✅ Fixed data/ directory permissions"
else
    echo "  ℹ️  Some data/ subdirectories owned by containers (normal after first run)"
    echo "  ℹ️  Containers will continue to use existing directories"
fi

# Check if directory exists, create if not
if [ ! -d "$SHARED_VOLUME_PATH" ]; then
    echo "📁 Creating shared volume directory: $SHARED_VOLUME_PATH"
    sudo mkdir -p "$SHARED_VOLUME_PATH"
fi

# Set ownership to current user and group
echo "👤 Setting ownership to ${CURRENT_USER}:${CURRENT_GROUP} (${CURRENT_UID}:${CURRENT_GID})"
sudo chown -R "${CURRENT_USER}:${CURRENT_GROUP}" "$SHARED_VOLUME_PATH"

# Set permissions: a+wrsx (all can read/write/execute, sticky bit set)
echo "🔐 Setting permissions: a+rwx,+t (0777 + sticky bit)"
sudo chmod -R a+rwx "$SHARED_VOLUME_PATH"
sudo chmod +t "$SHARED_VOLUME_PATH"  # Sticky bit for directory

# Verify permissions
echo "✅ Final permissions:"
sudo ls -la "$SHARED_VOLUME_PATH"

echo "🎉 Shared volume permissions initialized successfully!"