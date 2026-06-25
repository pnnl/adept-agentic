#!/bin/bash
#
# Deployment Script for AWS EKS
#
set -euo pipefail

# --- Configuration (Defaults can be overridden by environment variables) ---
: "${AWS_REGION:=us-west-2}"
: "${HELM_RELEASE_NAME:=agentic-framework-aws}"
: "${NAMESPACE:=agentic-framework}"
: "${CDK_APP_PATH:=./infra/aws/cdk}"
: "${HELM_CHART_PATH:=./infra/helm/agentic-framework}"
: "${VALUES_FILE:=./infra/helm/agentic-framework/values-aws.yaml}"

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
    echo "  deploy:   Provisions AWS infrastructure (EKS, ECR), builds/pushes images, and deploys the Helm chart."
    echo "  destroy:  Deletes the Helm release and tears down all AWS infrastructure created by the CDK."
    echo "  status:   Shows the status of the CDK and Helm deployments."
}

check_prerequisites() {
    log "Checking prerequisites..."
    check_command "aws"
    check_command "cdk"
    check_command "docker"
    check_command "helm"
    check_command "kubectl"
    log "Verifying AWS authentication..."
    aws sts get-caller-identity > /dev/null || error "AWS authentication failed. Please configure your AWS credentials."
    log "✅ Prerequisites met."
}

provision_infrastructure() {
    log "Provisioning AWS infrastructure with CDK..."
    log "(This may take 15-20 minutes)"
    (cd "$CDK_APP_PATH" && cdk deploy --all --require-approval never)
    log "✅ AWS infrastructure provisioned."
}

build_and_push_images() {
    log "Building and pushing Docker images to ECR..."
    
    log "Building local images..."
    docker compose -f docker-compose.base.yaml -f docker-compose.core.yaml build

    log "Getting ECR repository URI..."
    # Query CDK for one of the repo URIs to get the registry prefix
    local one_repo_uri=$(cd "$CDK_APP_PATH" && cdk output -j | jq -r 'values | .[] | to_entries[] | select(.key | endswith("EcrRepoUri")) | .value' | head -n 1)
    [ -n "$one_repo_uri" ] || error "Could not retrieve ECR repository URI from CDK outputs."
    local ecr_registry=$(echo "$one_repo_uri" | cut -d'/' -f1)
    log "ECR Registry: $ecr_registry"

    log "Authenticating Docker to ECR..."
    aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ecr_registry"

    for image in "${ALL_IMAGES[@]}"; do
        local source_image="${image}:latest"
        local target_image="${ecr_registry}/${image}:latest"
        log "Processing image: $image"
        docker tag "$source_image" "$target_image" || error "Failed to tag $source_image"
        docker push "$target_image" || error "Failed to push $target_image"
    done
    log "✅ All images pushed to ECR successfully."
    # Export for deploy_application
    export ECR_REGISTRY_PREFIX="${ecr_registry}/"
}

deploy_application() {
    log "Deploying application to EKS with Helm..."
    [ -n "$ECR_REGISTRY_PREFIX" ] || error "ECR_REGISTRY_PREFIX not set. Cannot deploy application."

    log "Configuring kubectl for EKS cluster..."
    local cluster_name=$(cd "$CDK_APP_PATH" && cdk output -j | jq -r 'values | .[] | to_entries[] | select(.key | endswith("EksClusterName")) | .value' | head -n 1)
    [ -n "$cluster_name" ] || error "Could not retrieve EKS cluster name from CDK outputs."
    aws eks update-kubeconfig --name "$cluster_name" --region "$AWS_REGION"

    log "Deploying Helm chart..."
    helm upgrade --install "$HELM_RELEASE_NAME" "$HELM_CHART_PATH" \
      --namespace "$NAMESPACE" --create-namespace \
      -f "$VALUES_FILE" \
      --set global.image.repositoryPrefix="$ECR_REGISTRY_PREFIX" \
      --atomic --timeout 10m
    log "✅ Helm chart deployed successfully."
}

destroy_all() {
    read -p "Are you sure you want to delete the Helm release AND all AWS infrastructure created by CDK? (y/N) " confirm
    if [[ "$confirm" != "y" ]]; then
        log "Deletion cancelled."
        exit 0
    fi

    log "Deleting Helm release '$HELM_RELEASE_NAME'..."
    helm uninstall "$HELM_RELEASE_NAME" -n "$NAMESPACE" --wait || log "Helm release not found or already deleted."

    log "Destroying AWS infrastructure with CDK..."
    log "(This may take 15-20 minutes)"
    (cd "$CDK_APP_PATH" && cdk destroy --all --force)
    log "✅ All AWS resources destroyed."
}

show_status() {
    log "--- AWS CDK Stack Status ---"
    (cd "$CDK_APP_PATH" && cdk status)
    log "--- Helm Release Status ---"
    helm status "$HELM_RELEASE_NAME" -n "$NAMESPACE"
    log "--- EKS Pods Status ---"
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
        log "🚀 Deployment to AWS EKS is complete."
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
