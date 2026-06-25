# Agentic Framework Infrastructure and Deployment Guide

This document provides a comprehensive guide to deploying the Agentic Framework to its various target Kubernetes (K8s) environments. It covers the setup, credential configuration, and deployment process for local development, on-premises clusters, and major cloud providers.

The deployment strategy is standardized around two core technologies:
1.  **Infrastructure as Code (IaC):** The underlying cloud infrastructure (EKS, AKS, GKE) is managed via code using tools like AWS CDK, Pulumi, and Terraform. All IaC is located within this `infra/` directory.
2.  **Helm:** The application itself is packaged as a universal Helm chart located in `infra/helm/agentic-framework`, which is deployed onto the provisioned Kubernetes cluster.

---

## 1. Local Development Environments

There are two primary methods for running the framework locally, each serving a different purpose.

### 1.1. Docker Compose (Quickest Start)

-   **Purpose:** Best for rapid, iterative development, especially when working on a single service.
-   **How to Run:** Use the `Makefile` targets (`make start`, `make stop`, etc.) or the `start-chapter-resources.sh` script.
-   **Caveat:** This method has significant differences from production environments (the "parity gap"), especially in networking and the sandbox execution backend. It is not recommended for integration testing.

### 1.2. Local Kubernetes (High-Fidelity Development)

-   **Purpose:** The **recommended** approach for most development work. It runs the entire stack on a local K8s cluster (like Docker Desktop K8s, Minikube, or k3d), providing an environment that almost perfectly mirrors production.
-   **Detailed Guide:** For a complete walkthrough, see **[docs/LOCAL_K8S_DEVELOPMENT.md](../docs/LOCAL_K8S_DEVELOPMENT.md)**.
-   **Quick Start:**
    ```bash
    # Build images, load them into your local K8s, and deploy with Helm
    make local-k8s-start

    # Clean up the deployment
    make local-k8s-stop
    ```

---

## 2. On-Premises Kubernetes Deployment (EMSL)

This workflow is tailored for deploying to the specific, managed Kubernetes environment at the EMSL computing facility.

-   **Deployment Script:** `../scripts/deploy-to-emsl.sh`
-   **Workflow:** This is a multi-step process:
    1.  **Build:** Container images are built locally.
    2.  **Push:** Images are pushed to the on-premises container registry (`your-registry.example.com`).
    3.  **Deploy:** The script uses Helm to deploy the application, which the cluster then pulls from the registry.

### Setup and Credentials

1.  **Client Bundle:** You must have the EMSL-provided Kubernetes client bundle placed in `scripts/deps/emsl-helm/`.
2.  **Docker Login:** You must be authenticated to the `your-registry.example.com` registry. The script will prompt for credentials if you are not already logged in via the Docker CLI.

### Usage

```bash
# To build, push all images, and deploy/upgrade the application:
./scripts/deploy-to-emsl.sh deploy --push

# To check the status of the deployment:
./scripts/deploy-to-emsl.sh status

# To delete the deployment from the cluster:
./scripts/deploy-to-emsl.sh delete
```

---

## 3. Cloud Kubernetes Deployments

Each cloud provider has a dedicated subdirectory containing its IaC configuration and a corresponding deployment script in the `scripts/` directory. These scripts automate the entire lifecycle from infrastructure provisioning to application deployment.

### 3.1. AWS (EKS)

-   **IaC Tool:** AWS CDK (`infra/aws/cdk/`)
-   **Deployment Script:** `../scripts/deploy-to-aws.sh`
-   **Credentials Setup:** You must have the `aws` CLI installed and configured with credentials for your target account. Run `aws configure` or set the standard `AWS_` environment variables.

**Usage:**
```bash
# Deploy the entire stack to AWS
./scripts/deploy-to-aws.sh deploy

# Destroy all created AWS resources
./scripts/deploy-to-aws.sh destroy
```

### 3.2. Azure (AKS)

-   **IaC Tool:** Pulumi (`infra/azure/pulumi/`)
-   **Deployment Script:** `../scripts/deploy-to-azure.sh`
-   **Credentials Setup:** You must have the `az` CLI installed and be logged into your target subscription (`az login`).

**Usage:**
```bash
# Deploy the entire stack to Azure
./scripts/deploy-to-azure.sh deploy

# Destroy all created Azure resources
./scripts/deploy-to-azure.sh destroy
```

### 3.3. GCP (GKE)

-   **IaC Tool:** Terraform (`infra/gcp/terraform/`)
-   **Deployment Script:** `../scripts/deploy-to-gcp.sh`
-   **Credentials Setup:** You must have the `gcloud` CLI installed and authenticated (`gcloud auth login` and `gcloud auth application-default login`). You must also set the `GCP_PROJECT` environment variable or edit the script.

**Usage:**
```bash
# Set your project ID
export GCP_PROJECT="your-gcp-project-id"

# Deploy the entire stack to GCP
./scripts/deploy-to-gcp.sh deploy

# Destroy all created GCP resources
./scripts/deploy-to-gcp.sh destroy
```
