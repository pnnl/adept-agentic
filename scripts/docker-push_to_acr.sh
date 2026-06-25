#!/bin/bash

# Script to tag and push a Docker image to Azure Container Registry (ACR)
# Example usage:
# ./scripts/docker-push_to_acr.sh agentic_framework-streamlit_app latest aqeldrd-gbhafngagebycmdm
# ./scripts/docker-push_to_acr.sh agentic_framework-mcp_server latest aqeldrd-gbhafngagebycmdm


# Exit immediately if a command exits with a non-zero status.
set -e

# Check if the correct number of arguments are provided
if [ "$#" -ne 3 ]; then
    echo "Usage: $0 <local_image_name> <tag> <acr_name>"
    echo "Example: $0 myapp latest mycontainerregistry"
    exit 1
fi

LOCAL_IMAGE_NAME="$1"
TAG="$2"
ACR_NAME="$3"

# Define the full local image identifier
LOCAL_IMAGE_ID="${LOCAL_IMAGE_NAME}:${TAG}"

# Define the ACR image identifier
# Using the local image name as the repository name in ACR by default
ACR_IMAGE_REPO_NAME="${LOCAL_IMAGE_NAME}"
ACR_LOGIN_SERVER="${ACR_NAME}.azurecr.io"
ACR_IMAGE_ID="${ACR_LOGIN_SERVER}/${ACR_IMAGE_REPO_NAME}:${TAG}"

echo "Attempting to log in to ACR: ${ACR_NAME}..."
az acr login --name "${ACR_NAME}"

echo "Tagging local image ${LOCAL_IMAGE_ID} as ${ACR_IMAGE_ID}..."
docker tag "${LOCAL_IMAGE_ID}" "${ACR_IMAGE_ID}"

echo "Pushing image ${ACR_IMAGE_ID} to ACR..."
docker push "${ACR_IMAGE_ID}"

echo "Successfully pushed ${ACR_IMAGE_ID} to ${ACR_NAME}."

