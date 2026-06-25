#!/bin/bash
set -e

# ==============================================================================
# Docker Image Push Script for Agentic Framework
#
# This script builds, tags, and pushes all buildable services defined in the
# docker-compose files to the specified container registry.
# ==============================================================================

# --- Configuration ---
# The target registry server.
# Replace with your actual registry if different.
REGISTRY_SERVER="tanuki-registry.pnnl.gov"
REGISTRY_REPO="cloudhub/agentic-framework"

# --- Helper Functions ---
info() { echo -e "\033[1;34m[INFO]\033[0m $1"; }
error() { echo -e "\033[1;31m[ERROR]\033[0m $1"; exit 1; }
success() { echo -e "\033[1;32m[SUCCESS]\033[0m $1"; }

# --- Main Script Logic ---

# 1. Authenticate with the Docker Registry
info "Please log in to the Docker registry: ${REGISTRY_SERVER}"
if ! docker login "${REGISTRY_SERVER}"; then
    error "Docker login failed. Please check your credentials."
fi
success "Docker login successful."

# 2. Discover all buildable services from docker-compose files
info "Discovering all buildable services from docker-compose files..."
# This command inspects the compose files and lists all services that have a 'build' context.
SERVICES=$(docker compose -f docker-compose.base.yaml -f docker-compose.core.yaml config --services)

if [ -z "$SERVICES" ]; then
    error "No buildable services found in docker-compose files."
fi

info "Found the following services to build and push:"
for SERVICE in $SERVICES; do
    echo "  - ${SERVICE}"
done

# 3. Build, Tag, and Push each service
info "Starting build, tag, and push process..."
for SERVICE in $SERVICES; do
    info "Processing service: ${SERVICE}..."
    
    # Define image names
    LOCAL_IMAGE="agentic-framework-${SERVICE}:latest"
    REMOTE_IMAGE="${REGISTRY_SERVER}/${REGISTRY_REPO}/${LOCAL_IMAGE}"

    # Build the image using docker-compose to ensure consistency
    info "Building ${LOCAL_IMAGE}..."
    if ! docker compose -f docker-compose.base.yaml -f docker-compose.core.yaml build ${SERVICE}; then
        error "Build failed for service: ${SERVICE}"
    fi

    # Tag the image for the remote registry
    info "Tagging ${LOCAL_IMAGE} as ${REMOTE_IMAGE}..."
    if ! docker tag "${LOCAL_IMAGE}" "${REMOTE_IMAGE}"; then
        error "Tagging failed for image: ${LOCAL_IMAGE}"
    fi

    # Push the image
    info "Pushing ${REMOTE_IMAGE}..."
    if ! docker push "${REMOTE_IMAGE}"; then
        error "Push failed for image: ${REMOTE_IMAGE}"
    fi
    
    success "Successfully pushed ${REMOTE_IMAGE}"
    echo "----------------------------------------------------"
done

success "All services have been successfully pushed to the registry."
