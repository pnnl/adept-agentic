#!/bin/bash
#
# Deployment Script for Azure AKS
#
set -euo pipefail

# --- Configuration (Defaults can be overridden by environment variables) ---
: "${AZURE_LOCATION:=eastus}"
: "${HELM_RELEASE_NAME:=agentic-framework-azure}"
: "${NAMESPACE:=agentic-framework}"
: "${PULUMI_APP_PATH:=./infra/azure/pulumi}"
: "${HELM_CHART_PATH:=./infra/helm/agentic-framework}"
: "${VALUES_FILE:=./infra/helm/agentic-framework/values-azure.yaml}"

# --- Internal Variables ---
ALL_IMAGES=(
    "agentic-framework-os-base" "agentic-framework-deps-base" "agentic-framework-vector_db_server"
    "agentic-framework-keycloak" "agentic-framework-redis" "agentic-framework-n8n"
    "agentic-framework-openwebui" "agentic-framework-postgres" "agentic-framework-bootstrap"
    "agentic-framework-nginx_proxy" "agentic-framework-agent_gateway" "agentic-framework-mcp_server"
    "agentic-framework-orchestration_service" "agentic-framework-streamlit_app" "agentic-framework-streamlit_app_v2"
    "agentic-framework-hpc_mcp_server" "agentic-framework-sandbox_mcp_server"
    "agentic-framework-agent_gateway_mgmt_ui" "agentic-framework-gateway_registry" "agentic-framework-jupyterlab"
)

# --- Helper Functions ---
log() { echo -e "\033[1;34m[$(date '+%Y-%m-%d %H:%M:%S')]\033[0m $1"; }
error() { echo -e "\033[1;31m[ERROR]\033[0m $1"; exit 1; }
check_command() { command -v "$1" >/dev/null 2>&1 || error "$1 is not installed. Please install it to continue."; }

# --- Script Functions ---

usage() {
    echo "Usage: $0 {deploy|destroy|status}"
    echo "  deploy:   Provisions Azure infrastructure (AKS, ACR), builds/pushes images, and deploys the Helm chart."
    echo "  destroy:  Deletes the Helm release and tears down all Azure infrastructure created by Pulumi."
    echo "  status:   Shows the status of the Pulumi and Helm deployments."
}

check_prerequisites() {
    log "Checking prerequisites..."
    check_command "az"
    check_command "pulumi"
    check_command "docker"
    check_command "helm"
    check_command "kubectl"
    log "Verifying Azure authentication..."
    az account show > /dev/null || error "Azure authentication failed. Please run 'az login'."
    log "✅ Prerequisites met."
}

provision_infrastructure() {
    log "Provisioning Azure infrastructure with Pulumi..."
    log "(This may take 10-15 minutes)"
    (cd "$PULUMI_APP_PATH" && pulumi up --yes)
    log "✅ Azure infrastructure provisioned."
}

build_and_push_images() {
    log "Building and pushing Docker images to ACR..."
    
    log "Building local images..."
    docker compose -f docker-compose.base.yaml -f docker-compose.core.yaml build

    log "Getting ACR login server..."
    local acr_login_server=$(cd "$PULUMI_APP_PATH" && pulumi stack output acrLoginServer)
    [ -n "$acr_login_server" ] || error "Could not retrieve ACR login server from Pulumi outputs."
    log "ACR Login Server: $acr_login_server"

    log "Authenticating Docker to ACR..."
    az acr login --name "$acr_login_server"

    for image in "${ALL_IMAGES[@]}"; do
        local source_image="${image}:latest"
        local target_image="${acr_login_server}/${image}:latest"
        log "Processing image: $image"
        docker tag "$source_image" "$target_image" || error "Failed to tag $source_image"
        docker push "$target_image" || error "Failed to push $target_image"
    done
    log "✅ All images pushed to ACR successfully."
    export ACR_LOGIN_SERVER="${acr_login_server}"
}

deploy_application() {
    log "Deploying application to AKS with Helm..."
    [ -n "$ACR_LOGIN_SERVER" ] || error "ACR_LOGIN_SERVER not set. Cannot deploy application."

    log "Configuring kubectl for AKS cluster..."
    (cd "$PULUMI_APP_PATH" && pulumi stack output kubeconfig --show-secrets > ./kubeconfig.yaml)
    export KUBECONFIG="${PULUMI_APP_PATH}/kubeconfig.yaml"

    log "Deploying Helm chart..."
    helm upgrade --install "$HELM_RELEASE_NAME" "$HELM_CHART_PATH" \
      --namespace "$NAMESPACE" --create-namespace \
      -f "$VALUES_FILE" \
      --set global.image.repositoryPrefix=\"${ACR_LOGIN_SERVER}/\" \
      --atomic --timeout 10m
    log "✅ Helm chart deployed successfully."
}

destroy_all() {
    read -p "Are you sure you want to delete the Helm release AND all Azure infrastructure created by Pulumi? (y/N) " confirm
    if [[ "$confirm" != "y" ]]; then
        log "Deletion cancelled."
        exit 0
    fi

    log "Deleting Helm release '$HELM_RELEASE_NAME'..."
    (cd "$PULUMI_APP_PATH" && pulumi stack output kubeconfig --show-secrets > ./kubeconfig.yaml)
    export KUBECONFIG="${PULUMI_APP_PATH}/kubeconfig.yaml"
    helm uninstall "$HELM_RELEASE_NAME" -n "$NAMESPACE" --wait || log "Helm release not found or already deleted."

    log "Destroying Azure infrastructure with Pulumi..."
    log "(This may take 10-15 minutes)"
    (cd "$PULUMI_APP_PATH" && pulumi destroy --yes)
    rm -f "${PULUMI_APP_PATH}/kubeconfig.yaml"
    log "✅ All Azure resources destroyed."
}

show_status() {
    log "--- Pulumi Stack Status ---"
    (cd "$PULUMI_APP_PATH" && pulumi stack)
    log "--- Helm Release Status ---"
    (cd "$PULUMI_APP_PATH" && pulumi stack output kubeconfig --show-secrets > ./kubeconfig.yaml)
    export KUBECONFIG="${PULUMI_APP_PATH}/kubeconfig.yaml"
    helm status "$HELM_RELEASE_NAME" -n "$NAMESPACE"
    log "--- AKS Pods Status ---"
    kubectl get pods -n "$NAMESPACE"
    rm -f "${PULUMI_APP_PATH}/kubeconfig.yaml"
}

# --- Main Execution ---
if [ $# -eq 0 ]; then
    usage
    exit 1
fi

ACTION=$1
shift

check_prerequisites

case "$ACTION" in
    deploy)
        provision_infrastructure
        build_and_push_images
        deploy_application
        log "🚀 Deployment to Azure AKS is complete."
        ;;
    destroy)
        destroy_all
        ;;
    status)
        show_status
        ;;
    *)
        usage
        ;;
esac
