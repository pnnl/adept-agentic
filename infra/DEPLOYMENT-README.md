# Agentic Framework Kubernetes Deployment Guide

This document provides a comprehensive guide to deploying the Agentic Framework to various Kubernetes (K8s) environments, from local development clusters to on-premises and cloud-based production environments.

The deployment strategy is standardized around two core technologies:
1.  **Infrastructure as Code (IaC):** The underlying cloud infrastructure (EKS, AKS, GKE) is managed via code using tools like CDK, Pulumi, and Terraform. All IaC is located within this `infra/` directory.
2.  **Helm:** The application itself is packaged as a universal Helm chart located in `infra/helm/agentic-framework`, which is deployed onto the provisioned Kubernetes cluster.

---

## 1. Ubuntu 22.04 Development & Deployment Environment Setup

This section details how to configure an Ubuntu 22.04.5 LTS machine to serve as both a local development environment and a "jump box" for deploying to other environments (on-prem, cloud).

### Step 1: System Update and Core Dependencies

First, update your package lists and install essential utilities.

```bash
sudo apt-get update
sudo apt-get install -y apt-transport-https ca-certificates curl gnupg git wget
```

### Step 2: Docker Installation

Install the Docker engine, which is required for building container images and for the local Kubernetes cluster.

```bash
# Add Docker's official GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add the Docker repository to Apt sources
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update

# Install Docker packages
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Add your user to the 'docker' group to run docker commands without sudo
sudo usermod -aG docker $USER

# Apply the group changes
newgrp docker
```

### Step 3: Local Kubernetes Setup (k3d)

For a lightweight, Docker-based local Kubernetes cluster, `k3d` is an excellent choice. It runs a minimal K3s cluster inside Docker containers.

```bash
# Install k3d
wget -q -O - https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash

# Create a local Kubernetes cluster named 'agentic-dev'
# This command also exposes the default Kubernetes API port to the host.
k3d cluster create agentic-dev -p "8081:80@loadbalancer" --agents 2

# Set the new cluster as the current context for kubectl
kubectl config use-context k3d-agentic-dev
```

### Step 4: `kubectl` Installation

Install the Kubernetes command-line tool.

```bash
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
```

### Step 5: `helm` Installation

Install the Helm package manager for Kubernetes.

```bash
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

### Step 6: Cloud & IaC Tooling (Optional)

If this machine will be used to deploy to cloud environments, install the necessary CLIs.

**For AWS:**
```bash
sudo apt-get install -y nodejs npm
npm install -g aws-cdk
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install
# Now configure with: aws configure
```

**For Azure:**
```bash
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
curl -fsSL https://get.pulumi.com | sh
# Now configure with: az login
```

**For GCP:**
```bash
sudo apt-get install -y google-cloud-sdk
curl -fsSL https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt-get update && sudo apt-get install terraform
# Now configure with: gcloud auth login
```

### Step 7: Final Verification

Your Ubuntu environment is now fully configured. You can clone the project repository and start the local Kubernetes development workflow:

```bash
# Clone the project (if you haven't already)
git clone <your-repo-url>
cd agentic_framework

# Verify the setup by starting the local K8s deployment
make local-k8s-start
```

---

## 2. Local Kubernetes Development

This is the recommended workflow for day-to-day development and testing. It provides the highest fidelity to production environments by running the entire stack on a local K8s cluster, which solves the parity gaps (especially for the sandbox execution environment) inherent in the Docker Compose setup.

**For a detailed step-by-step guide, please refer to [docs/LOCAL_K8S_DEVELOPMENT.md](./docs/LOCAL_K8S_DEVELOPMENT.md).**

### Quick Start

1.  **Prerequisites:** Ensure you have Docker, `kubectl`, `helm`, and a local Kubernetes cluster (like Docker Desktop K8s, Minikube, or k3d) installed and running.

2.  **Start the Framework:**
    ```bash
    # This command builds local images, loads them into your K8s cluster, and deploys the Helm chart.
    make local-k8s-start
    ```

3.  **Stop the Framework:**
    ```bash
    # This command deletes the Helm release and all associated Kubernetes resources.
    make local-k8s-stop
    ```

4.  **View Logs:**
    ```bash
    # Stream logs from all running pods.
    make local-k8s-logs
    ```

## 3. On-Premises Deployment (EMSL Example)

This workflow is tailored for deploying to a specific, managed Kubernetes environment like the EMSL computer lab. It assumes a private container registry is used.

### Workflow

The process involves three main stages:
1.  **Build:** Create the Docker images on your local machine.
2.  **Push:** Push the images to your container registry (e.g., `your-registry.example.com`).
3.  **Deploy:** Use the dedicated script to deploy the Helm chart, which instructs the K8s cluster to pull the newly pushed images.

### Usage

The `scripts/deploy-to-emsl.sh` script manages this lifecycle.

1.  **Deploy or Upgrade the Application:**
    The `--push` flag is recommended on the first deployment or when you have local image changes to push.
    ```bash
    # Build local images, push them to the registry, and then deploy/upgrade the Helm release.
    ./scripts/deploy-to-emsl.sh deploy --push
    ```

2.  **Check Deployment Status:**
    ```bash
    ./scripts/deploy-to-emsl.sh status
    ```

3.  **Delete the Deployment:**
    ```bash
    ./scripts/deploy-to-emsl.sh delete
    ```

## 4. Cloud Deployment (AWS, Azure, GCP)

Deployment to each cloud provider is automated with a dedicated script that mirrors the logic in the CI/CD workflows. These scripts handle the entire lifecycle, from provisioning the cloud infrastructure to deploying the application.

### A. AWS EKS Deployment

*   **Technology:** AWS CDK for infrastructure, Helm for the application.
*   **Prerequisites:** `aws` CLI (authenticated), `cdk`, `docker`, `helm`, `kubectl`.
*   **Script:** `scripts/deploy-to-aws.sh`

**Usage:**
```bash
# Deploy the entire stack to AWS
./scripts/deploy-to-aws.sh deploy

# Check the status of the deployment
./scripts/deploy-to-aws.sh status

# Destroy all created AWS resources and the Helm deployment
./scripts/deploy-to-aws.sh destroy
```

### B. Azure AKS Deployment

*   **Technology:** Pulumi for infrastructure, Helm for the application.
*   **Prerequisites:** `az` CLI (authenticated), `pulumi`, `docker`, `helm`, `kubectl`.
*   **Script:** `scripts/deploy-to-azure.sh`

**Usage:**
```bash
# Deploy the entire stack to Azure
./scripts/deploy-to-azure.sh deploy

# Check the status of the deployment
./scripts/deploy-to-azure.sh status

# Destroy all created Azure resources and the Helm deployment
./scripts/deploy-to-azure.sh destroy
```

### C. GCP GKE Deployment

*   **Technology:** Terraform for infrastructure, Helm for the application.
*   **Prerequisites:** `gcloud` CLI (authenticated), `terraform`, `docker`, `helm`, `kubectl`.
*   **Script:** `scripts/deploy-to-gcp.sh`

**Usage:**
```bash
# Deploy the entire stack to GCP
# Note: You must set the GCP_PROJECT environment variable or edit the script.
export GCP_PROJECT="your-gcp-project-id"
./scripts/deploy-to-gcp.sh deploy

# Check the status of the deployment
./scripts/deploy-to-gcp.sh status

# Destroy all created GCP resources and the Helm deployment
./scripts/deploy-to-gcp.sh destroy
```