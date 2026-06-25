#!/bin/bash
#
# 04-install-cloud-tools.sh
# Installs optional cloud and IaC command-line tools.
#
set -e

log_sub() { echo -e "  \033[1;32m[CLOUD-TOOLS]\033[0m $1"; }

# --- AWS Tools ---
if ! command -v aws &> /dev/null || ! command -v cdk &> /dev/null; then
    log_sub "Installing AWS CLI and CDK..."
    sudo apt-get install -y nodejs npm
    sudo npm install -g aws-cdk
    curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
    unzip -q awscliv2.zip
    sudo ./aws/install
    rm -rf awscliv2.zip ./aws
    log_sub "AWS tools installed. Run 'aws configure' to set up credentials."
else
    log_sub "AWS CLI and CDK already installed. Skipping."
fi

# --- Azure Tools ---
if ! command -v az &> /dev/null || ! command -v pulumi &> /dev/null; then
    log_sub "Installing Azure CLI and Pulumi..."
    curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
    curl -fsSL https://get.pulumi.com | sh
    # Add pulumi to path for the current session
    export PATH=$PATH:$HOME/.pulumi/bin
    log_sub "Azure tools installed. Run 'az login' to set up credentials."
else
    log_sub "Azure CLI and Pulumi already installed. Skipping."
fi

# --- GCP Tools ---
if ! command -v gcloud &> /dev/null || ! command -v terraform &> /dev/null; then
    log_sub "Installing Google Cloud SDK and Terraform..."
    if ! command -v gcloud &> /dev/null; then
      sudo apt-get install -y google-cloud-sdk
    fi
    if ! command -v terraform &> /dev/null; then
      curl -fsSL https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
      echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list > /dev/null
      sudo apt-get update && sudo apt-get install -y terraform
    fi
    log_sub "GCP tools installed. Run 'gcloud auth login' to set up credentials."
else
    log_sub "GCP SDK and Terraform already installed. Skipping."
fi
