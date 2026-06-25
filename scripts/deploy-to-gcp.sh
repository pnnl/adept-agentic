#!/bin/bash
#
# Deployment Script for Google Cloud GKE
#
set -euo pipefail

# --- Configuration (Defaults can be overridden by environment variables) ---
: "${GCP_PROJECT:=your-gcp-project-id}" # IMPORTANT: Replace with your GCP Project ID
: "${GCP_REGION:=us-central1}"
: "${HELM_RELEASE_NAME:=agentic-framework-gcp}"
: "${NAMESPACE:=agentic-framework}"
: "${TERRAFORM_APP_PATH:=./infra/gcp/terraform}"
: "${HELM_CHART_PATH:=./infra/helm/agentic-framework}"
: "${VALUES_FILE:=./infra/helm/agentic-framework/values-gcp.yaml}"

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
    echo "  deploy:   Provisions GCP infrastructure (GKE, Artifact Registry), builds/pushes images, and deploys the Helm chart."
    echo "  destroy:  Deletes the Helm release and tears down all GCP infrastructure created by Terraform."
    echo "  status:   Shows the status of the Terraform and Helm deployments."
}

check_prerequisites() {
    log "Checking prerequisites..."
    check_command "gcloud"
    check_command "terraform"
    check_command "docker"
    check_command "helm"
    check_command "kubectl"
    log "Verifying GCP authentication..."
    gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q . || error "GCP authentication failed. Please run 'gcloud auth login'."
    log "✅ Prerequisites met."
}

provision_infrastructure() {
    log "Provisioning GCP infrastructure with Terraform..."
    log "(This may take 10-15 minutes)"
    (cd "$TERRAFORM_APP_PATH" && terraform init && terraform apply -auto-approve -var="gcp_project=$GCP_PROJECT" -var="gcp_region=$GCP_REGION")
    log "✅ GCP infrastructure provisioned."
}

build_and_push_images() {
    log "Building and pushing Docker images to Artifact Registry..."
    
    log "Building local images..."
    docker compose -f docker-compose.base.yaml -f docker-compose.core.yaml build

    log "Getting Artifact Registry URL..."
    local artifact_registry_url=$(cd "$TERRAFORM_APP_PATH" && terraform output -raw artifact_registry_url)
    [ -n "$artifact_registry_url" ] || error "Could not retrieve Artifact Registry URL from Terraform outputs."
    log "Artifact Registry URL: $artifact_registry_url"

    log "Authenticating Docker to Artifact Registry..."
    gcloud auth configure-docker "${artifact_registry_url%%/*}" # Configure for the region

    for image in "${ALL_IMAGES[@]}"; do
        local source_image="${image}:latest"
        local target_image="${artifact_registry_url}/${image}:latest"
        log "Processing image: $image"
        docker tag "$source_image" "$target_image" || error "Failed to tag $source_image"
        docker push "$target_image" || error "Failed to push $target_image"
    done
    log "✅ All images pushed to Artifact Registry successfully."
    export ARTIFACT_REGISTRY_URL="${artifact_registry_url}"
}

deploy_application() {
    log "Deploying application to GKE with Helm..."
    [ -n "$ARTIFACT_REGISTRY_URL" ] || error "ARTIFACT_REGISTRY_URL not set. Cannot deploy application."

    log "Configuring kubectl for GKE cluster..."
    local cluster_name=$(cd "$TERRAFORM_APP_PATH" && terraform output -raw gke_cluster_name)
    [ -n "$cluster_name" ] || error "Could not retrieve GKE cluster name from Terraform outputs."
    gcloud container clusters get-credentials "$cluster_name" --region "$GCP_REGION" --project "$GCP_PROJECT"

    log "Deploying Helm chart..."
    helm upgrade --install "$HELM_RELEASE_NAME" "$HELM_CHART_PATH" \
      --namespace "$NAMESPACE" --create-namespace \
      -f "$VALUES_FILE" \
      --set global.image.repositoryPrefix="${ARTIFACT_REGISTRY_URL}/" \
      --atomic --timeout 10m
    log "✅ Helm chart deployed successfully."
}

destroy_all() {
    read -p "Are you sure you want to delete the Helm release AND all GCP infrastructure created by Terraform? (y/N) " confirm
    if [[ "$confirm" != "y" ]]; then
        log "Deletion cancelled."
        exit 0
    fi

    log "Deleting Helm release '$HELM_RELEASE_NAME'..."
    helm uninstall "$HELM_RELEASE_NAME" -n "$NAMESPACE" --wait || log "Helm release not found or already deleted."

    log "Destroying GCP infrastructure with Terraform..."
    log "(This may take 10-15 minutes)"
    (cd "$TERRAFORM_APP_PATH" && terraform destroy -auto-approve -var="gcp_project=$GCP_PROJECT" -var="gcp_region=$GCP_REGION")
    log "✅ All GCP resources destroyed."
}

show_status() {
    log "--- Terraform State Status ---"
    (cd "$TERRAFORM_APP_PATH" && terraform show)
    log "--- Helm Release Status ---"
    helm status "$HELM_RELEASE_NAME" -n "$NAMESPACE"
    log "--- GKE Pods Status ---"
    kubectl get pods -n "$NAMESPACE"
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
        log "🚀 Deployment to GCP GKE is complete."
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
