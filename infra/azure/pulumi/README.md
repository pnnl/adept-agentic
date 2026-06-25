# Agentic Framework - Azure Pulumi Deployment

This directory contains the Pulumi application for deploying the Agentic Framework's infrastructure to Microsoft Azure.

## Architecture

This Pulumi program provisions the following Azure resources:

1.  **Azure Resource Group**: A logical container for all project resources.
2.  **Azure Container Registry (ACR)**: A private registry to store the application's Docker images.
3.  **Azure Kubernetes Service (AKS) Cluster**: A managed Kubernetes cluster to run the application.
    *   It is configured with a system-assigned managed identity.
    *   This identity is granted the `AcrPull` role to allow the cluster to securely pull images from the ACR without needing explicit credentials.
4.  **Default Storage**: The AKS cluster is provisioned with default `StorageClass` options that will dynamically create Azure Files shares to satisfy the `PersistentVolumeClaim`s defined in the Helm chart.

## Prerequisites

To deploy this framework, you will need the following tools installed and configured on your local machine.

1.  **Git**: For cloning the source code repository.
2.  **Azure CLI**: Authenticated to your target Azure subscription.
    *   Install from Microsoft's documentation.
    *   Login by running `az login`.
3.  **Pulumi CLI**: The command-line tool for Pulumi.
    *   Install from the Pulumi website.
4.  **Python**: Version 3.11 or higher, with `pip` available.
5.  **Docker Desktop**: Must be running, as it's required for building and pushing container images.

## Deployment Steps

### 1. Setup Python Virtual Environment

From the project root directory, set up a Python virtual environment for the Pulumi project.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r infra/azure/pulumi/requirements.txt
```

### 2. Initialize and Configure Pulumi

Navigate to the Pulumi project directory and initialize a new stack. A stack is an isolated instance of your infrastructure (e.g., `dev`, `staging`, `prod`).

```bash
cd infra/azure/pulumi

# Initialize a new stack, e.g., 'dev'
pulumi stack init dev

# Set the Azure region for your deployment
# Example: 'eastus', 'westus2', 'westeurope'
pulumi config set azure-native:location eastus
```

### 3. Deploy the Infrastructure

Run `pulumi up` to preview and deploy the Azure resources. Pulumi will show you a summary of the resources to be created and ask for confirmation.

```bash
pulumi up
```

After you confirm, Pulumi will provision the Resource Group, ACR, and AKS cluster. This process can take 10-15 minutes.

### 4. Build and Push Docker Images

Once the infrastructure is up, you need to build your application's Docker images and push them to the newly created Azure Container Registry (ACR).

```bash
# Navigate back to the project root
cd ../../..

# Get the ACR login server name from Pulumi's stack outputs
ACR_LOGIN_SERVER=$(pulumi stack output --cwd infra/azure/pulumi acrLoginServer)

# Login to ACR
az acr login --name $ACR_LOGIN_SERVER

# Build and push each service image
for SERVICE in mcp_server streamlit_app hpc_mcp_server sandbox_mcp_server agent_gateway agent_gateway_mgmt_ui jupyterlab
do
  IMAGE_NAME="agentic_framework-${SERVICE}"
  docker compose build $SERVICE
  docker tag "${IMAGE_NAME}:latest" "${ACR_LOGIN_SERVER}/${IMAGE_NAME}:latest"
  docker push "${ACR_LOGIN_SERVER}/${IMAGE_NAME}:latest"
done
```

### 5. Deploy the Helm Chart to AKS

Now, deploy your application using the Helm chart.

```bash
# Get the AKS kubeconfig from Pulumi's stack outputs and set it for kubectl
pulumi stack output --cwd infra/azure/pulumi kubeconfig --show-secrets > kubeconfig.yaml
export KUBECONFIG=$(pwd)/kubeconfig.yaml

# Deploy using Helm, overriding values for the Azure environment
helm upgrade --install my-agentic-release ./infra/helm/agentic-framework/ \
  --namespace agentic-framework --create-namespace \
  --values ./infra/helm/agentic-framework/values-azure.yaml \
  --set-string global.image.repositoryPrefix="${ACR_LOGIN_SERVER}/"
```

### 6. Cleaning Up

To remove all resources created by Pulumi, run the destroy command from the `infra/azure/pulumi` directory.

```bash
pulumi destroy
```