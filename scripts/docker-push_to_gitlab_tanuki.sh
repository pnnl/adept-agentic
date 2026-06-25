#!/bin/bash
set -e

# Define the target registry
REGISTRY="tanuki-registry.pnnl.gov/cloudhub/agentic-framework"

# List of all buildable service images from docker-compose files
# This list should be kept in sync with the services defined in the compose files.
ALL_IMAGES=(
    "agentic-framework-os-base"
    "agentic-framework-deps-base"
    "agentic-framework-vector_db_server"
    "agentic-framework-keycloak"
    "agentic-framework-redis"
    "agentic-framework-n8n"
    "agentic-framework-openwebui"
    "agentic-framework-postgres"
    "agentic-framework-bootstrap"
    "agentic-framework-nginx_proxy"
    "agentic-framework-agent_gateway"
    "agentic-framework-mcp_server"
    "agentic-framework-orchestration_service"
    "agentic-framework-streamlit_app"
    "agentic-framework-streamlit_app_v2"
    "agentic-framework-hpc_mcp_server"
    "agentic-framework-sandbox_mcp_server"
    "agentic-framework-agent_gateway_mgmt_ui"
    "agentic-framework-gateway_registry"
    "agentic-framework-jupyterlab"
)

# --- Helper Functions ---
info() { echo -e "\033[1;34m[INFO]\033[0m $1"; }
error() { echo -e "\033[1;31m[ERROR]\033[0m $1"; exit 1; }

usage() {
    echo "Usage: $0 {<image_name> | --all}"
    echo "Pushes a locally built Docker image to the PNNL registry."
    echo ""
    echo "Arguments:"
    echo "  <image_name>    The specific local image to push (e.g., agentic_framework-mcp_server)."
    echo "  --all           Push all defined service images to the registry."
    echo ""
    echo "Example:"
    echo "  $0 agentic_framework-hpc_mcp_server"
    echo "  $0 --all"
}

push_image() {
    local image_name=$1
    local source_image="${image_name}:latest"
    local target_image="${REGISTRY}/${image_name}:latest"

    info "--- Processing image: ${image_name} ---"

    if ! docker image inspect "${source_image}" &> /dev/null; then
        error "Local image '${source_image}' not found. Please build it first with 'make' or 'docker compose build'."
    fi

    info "Tagging ${source_image} as ${target_image}"
    docker tag "${source_image}" "${target_image}" || error "Failed to tag image ${source_image}"

    info "Pushing ${target_image}"
    docker push "${target_image}" || error "Failed to push image ${target_image}"

    info "Successfully pushed ${image_name}"
}

# --- Main script execution ---

if [ -z "$1" ]; then
    usage
    exit 1
fi

# Login to the Docker registry first
info "--- Logging in to ${REGISTRY%%/*} ---"
docker login "${REGISTRY%%/*}" || error "Docker login failed. Please check your credentials."

if [ "$1" == "--all" ]; then
    info "--- Pushing all framework images ---"
    for image in "${ALL_IMAGES[@]}"; do
        push_image "$image"
    done
    info "--- All images pushed successfully ---"
else
    push_image "$1"
fi