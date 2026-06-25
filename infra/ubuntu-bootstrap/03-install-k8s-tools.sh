#!/bin/bash
#
# 03-install-k8s-tools.sh
# Installs kubectl and helm.
#
set -e

log_sub() { echo -e "  \033[1;32m[K8S-TOOLS]\033[0m $1"; }

# Install kubectl if not already installed
if command -v kubectl &> /dev/null; then
    log_sub "kubectl is already installed. Skipping."
else
    log_sub "Installing kubectl..."
    curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
    sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
    rm kubectl
    log_sub "kubectl installed successfully."
fi

# Install helm if not already installed
if command -v helm &> /dev/null; then
    log_sub "helm is already installed. Skipping."
else
    log_sub "Installing helm..."
    curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
    log_sub "helm installed successfully."
fi
