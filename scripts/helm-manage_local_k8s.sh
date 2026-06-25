#!/bin/bash

# A simplified management script for deploying the Agentic Framework
# to a local Kubernetes cluster (like the one in Docker Desktop).

# For safety, exit on error.
set -euo pipefail

# --- Configuration Variables ---
# Ensure this script is run from the root of the agentic_framework project.
if [ ! -f "./infra/helm/agentic-framework/Chart.yaml" ]; then
    echo "ERROR: This script must be run from the root of the agentic_framework project."
    exit 1
fi

HELM_CHART_PATH="./infra/helm/agentic-framework/"
# We'll use a dedicated values file for local deployment
VALUES_FILE="./infra/helm/agentic-framework/values-local.yaml"
RELEASE_NAME="my-agentic-release"
NAMESPACE="agentic-framework"

# --- .env Secret Configuration ---
ENV_FILE="./.env"
APP_SECRET_NAME="my-app-env-secret" # Must match 'secrets.existingSecretName' in values-local.yaml

# --- Helper Functions ---

# Prints the script usage instructions
print_usage() {
    echo "Usage: $0 {spin-up|tear-down|status|logs}"
    echo "  spin-up:   Builds local Docker images and deploys/upgrades the Helm chart."
    echo "  tear-down: Deletes the Helm release and its associated resources."
    echo "  status:    Shows the status of the Kubernetes resources for the release."
    echo "  logs [pod-name-substring]: Shows logs for a specific service pod or all pods."
}

# Checks for the existence of necessary binaries.
check_prerequisites() {
    echo "--- Checking prerequisites (docker, kubectl, helm) ---"
    if ! command -v docker &> /dev/null; then
        echo "ERROR: 'docker' command not found. Please ensure Docker Desktop is running."
        exit 1
    fi
    if ! command -v kubectl &> /dev/null; then
        echo "ERROR: 'kubectl' command not found. Please ensure it's installed and in your PATH."
        exit 1
    fi
    if ! command -v helm &> /dev/null; then
        echo "ERROR: 'helm' command not found. Please ensure it's installed and in your PATH."
        exit 1
    fi
    if [ ! -f "${VALUES_FILE}" ]; then
        echo "ERROR: Local values file not found at ${VALUES_FILE}"
        echo "Please ensure you have created a 'values-local.yaml' for local deployment."
        exit 1
    fi
    echo "Prerequisites checked successfully."
}

# Creates or recreates a generic Kubernetes secret from a .env file.
create_app_env_secret() {
    echo "--- Creating/Updating application secret from ${ENV_FILE} ---"

    if [ ! -f "${ENV_FILE}" ]; then
        echo "WARN: .env file not found at ${ENV_FILE}. The application may not function correctly without it."
        echo "You can copy '.env.example' to '.env' and fill in your secrets."
        # Don't exit, allow deployment to proceed without secrets if user wants.
        return 0
    fi

    # Check if secret already exists and delete if so, to ensure it's up-to-date
    if kubectl get secret "${APP_SECRET_NAME}" -n "${NAMESPACE}" &> /dev/null; then
        echo "Secret '${APP_SECRET_NAME}' already exists. Deleting to recreate."
        kubectl delete secret "${APP_SECRET_NAME}" -n "${NAMESPACE}"
    fi

    # Create the secret from the .env file
    kubectl create secret generic "${APP_SECRET_NAME}" \
        --from-env-file="${ENV_FILE}" \
        --namespace "${NAMESPACE}"
    echo "Application secret '${APP_SECRET_NAME}' created successfully in namespace '${NAMESPACE}'."
}

# Main function to spin up the application
spin_up() {
    echo "--- Spinning up Agentic Framework on local Kubernetes ---"
    check_prerequisites

    echo "--- Step 1: Building local Docker images with Docker Compose ---"
    # This ensures Kubernetes (with pullPolicy: Never) can find the images
    docker compose build
    echo "Docker images built successfully."

    echo "--- Step 2: Ensuring Kubernetes namespace '${NAMESPACE}' exists ---"
    kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

    echo "--- Step 3: Creating application secret from .env file ---"
    create_app_env_secret

    echo "--- Step 4: Deploying/Upgrading Helm chart '${RELEASE_NAME}' ---"
    helm upgrade --install "${RELEASE_NAME}" "${HELM_CHART_PATH}" \
        --namespace "${NAMESPACE}" \
        -f "${VALUES_FILE}" \
        --atomic --timeout 10m
    
    echo "--- Deployment complete! ---"
    echo ""
    helm status "${RELEASE_NAME}" -n "${NAMESPACE}"
    echo ""
    echo "To access the Streamlit UI, run this command in a separate terminal:"
    echo "kubectl port-forward --namespace ${NAMESPACE} svc/${RELEASE_NAME}-agentic-framework-streamlit-app 8501:8501"
    echo "Then open http://localhost:8501 in your browser."
}

# Main function to tear down the application
tear_down() {
    echo "--- Tearing down Agentic Framework from local Kubernetes ---"
    check_prerequisites

    read -p "Are you sure you want to uninstall Helm release '${RELEASE_NAME}' and delete the '${APP_SECRET_NAME}' secret? (y/n): " confirm
    if [[ "$confirm" != "y" ]]; then
        echo "Aborted."
        exit 0
    fi

    echo "--- Uninstalling Helm release '${RELEASE_NAME}' ---"
    # Use helm uninstall, ignore not-found errors
    helm uninstall "${RELEASE_NAME}" --namespace "${NAMESPACE}" || true

    echo "--- Deleting application secret '${APP_SECRET_NAME}' ---"
    kubectl delete secret "${APP_SECRET_NAME}" -n "${NAMESPACE}" --ignore-not-found=true

    echo "Tear-down complete. Note: The namespace '${NAMESPACE}' and PVCs might still exist."
    echo "To delete PVCs, run: kubectl delete pvc -n ${NAMESPACE} -l app.kubernetes.io/instance=${RELEASE_NAME}"
    echo "To delete the namespace, run: kubectl delete namespace ${NAMESPACE}"
}

# Main function to check status
status_check() {
    echo "--- Status for release '${RELEASE_NAME}' in namespace '${NAMESPACE}' ---"
    check_prerequisites
    
    echo "--- Helm Status ---"
    helm status "${RELEASE_NAME}" -n "${NAMESPACE}"
    
    echo ""
    echo "--- Kubernetes Resources (Pods, Services, PVCs) ---"
    kubectl get pods,svc,pvc -n "${NAMESPACE}" -l app.kubernetes.io/instance="${RELEASE_NAME}"
}

# Main function to show logs
show_logs() {
    check_prerequisites
    local pod_substring="${1:-}"

    if [ -z "${pod_substring}" ]; then
        echo "Usage: $0 logs <pod-name-substring>"
        echo "Example: $0 logs streamlit"
        echo "--- Available pods ---"
        kubectl get pods -n "${NAMESPACE}" -l app.kubernetes.io/instance="${RELEASE_NAME}"
        exit 1
    fi

    # Find the pod name
    local pod_name
    pod_name=$(kubectl get pods -n "${NAMESPACE}" -l app.kubernetes.io/instance="${RELEASE_NAME}" -o jsonpath="{.items[?(@.metadata.name contains('${pod_substring}'))].metadata.name}")

    if [ -z "${pod_name}" ]; then
        echo "ERROR: No pod found with substring '${pod_substring}'."
        exit 1
    fi

    echo "--- Tailing logs for pod: ${pod_name} (Press Ctrl+C to stop) ---"
    kubectl logs -f "${pod_name}" -n "${NAMESPACE}"
}


# --- Main Script Logic ---
if [ -z "$1" ]; then
    print_usage
    exit 1
fi

case "$1" in
    spin-up)
        spin_up
        ;;
    tear-down)
        tear_down
        ;;
    status)
        status_check
        ;;
    logs)
        # Pass the second argument to the logs function
        show_logs "${2:-}"
        ;;
    *)
        echo "ERROR: Invalid command '$1'."
        print_usage
        exit 1
        ;;
esac