#!/bin/bash
#
# 02-install-k3d.sh
# Installs k3d and creates a local Kubernetes cluster.
#
set -e

log_sub() { echo -e "  \033[1;32m[K3D]\033[0m $1"; }

# Install k3d if not already installed
if command -v k3d &> /dev/null; then
    log_sub "k3d is already installed. Skipping installation."
else
    log_sub "Installing k3d..."
    wget -q -O - https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash
    log_sub "k3d installed successfully."
fi

# Create k3d cluster if it doesn't exist
CLUSTER_NAME="agentic-dev"
if k3d cluster get "$CLUSTER_NAME" &> /dev/null; then
    log_sub "k3d cluster '$CLUSTER_NAME' already exists."
else
    log_sub "Creating k3d cluster '$CLUSTER_NAME'..."
    k3d cluster create "$CLUSTER_NAME" -p "8081:80@loadbalancer" --agents 2
    log_sub "k3d cluster created successfully."
fi

log_sub "Setting kubectl context to '$CLUSTER_NAME'..."
kubectl config use-context "k3d-$CLUSTER_NAME"
