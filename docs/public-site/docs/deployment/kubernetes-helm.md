# Kubernetes and Helm

## Overview

ADEPT provides a Helm chart for production Kubernetes deployments across AWS EKS, Azure AKS, and GCP GKE. Infrastructure provisioning is managed through provider-specific IaC tools, while the Helm chart abstracts application-layer configuration.

## Helm Chart Structure

The chart is located at `infra/helm/agentic-framework/`:

```
agentic-framework/
├── Chart.yaml              # Chart metadata
├── values.yaml             # Default values
├── values-aws.yaml         # AWS EKS overrides
├── values-azure.yaml       # Azure AKS overrides
├── values-gcp.yaml         # GCP GKE overrides
├── values-local-k8s.yaml   # Local K8s (kind/minikube)
└── templates/              # Deployments, services, ingress, RBAC, secrets, PVCs
```

## AWS EKS Deployment (CDK)

Infrastructure is provisioned using AWS CDK (Python):

```bash
cd infra/aws/cdk
pip install -r requirements.txt
cdk deploy --all
```

**Provisioned resources:**

- EKS cluster with managed node groups
- RDS PostgreSQL (Multi-AZ)
- ElastiCache Redis
- ECR container registry
- ALB Ingress Controller
- IAM roles for service accounts (IRSA)

**Deploy the Helm chart:**

```bash
helm install adept infra/helm/agentic-framework/ \
  -f infra/helm/agentic-framework/values-aws.yaml \
  --namespace adept --create-namespace
```

## Azure AKS Deployment (Pulumi)

Infrastructure is provisioned using Pulumi (Python):

```bash
cd infra/azure/pulumi
pulumi up
```

**Provisioned resources:**

- AKS cluster with system and user node pools
- Azure Database for PostgreSQL Flexible Server
- Azure Cache for Redis
- Azure Container Registry (ACR)
- Azure Application Gateway Ingress
- Managed Identity for workload federation

**Deploy the Helm chart:**

```bash
helm install adept infra/helm/agentic-framework/ \
  -f infra/helm/agentic-framework/values-azure.yaml \
  --namespace adept --create-namespace
```

## GCP GKE Deployment (Terraform)

Infrastructure is provisioned using Terraform:

```bash
cd infra/gcp/terraform
terraform init && terraform apply
```

**Provisioned resources:**

- GKE Autopilot or Standard cluster
- Cloud SQL for PostgreSQL
- Memorystore for Redis
- Artifact Registry
- GKE Ingress with Cloud Load Balancing
- Workload Identity for pod-level IAM

## Configuration

### Secrets Management

Secrets are mounted as files at `/run/secrets/` inside containers. The framework's `SecretsManager` reads from this path with environment variable fallback:

```yaml
# values.yaml (excerpt)
secrets:
  kcAdminCliSecret: ""       # Keycloak admin-cli client secret
  postgresPassword: ""       # Database password
  redisPassword: ""          # Cache password
  llmApiKey: ""              # LLM provider API key
```

!!! tip "External Secrets"
    For production, use the External Secrets Operator to sync from AWS Secrets Manager, Azure Key Vault, or GCP Secret Manager into Kubernetes Secrets.

### Container Images

ADEPT builds internalized images from public bases for supply-chain security. Push to your registry and override in your values file:

```yaml
global:
  imageRegistry: "your-registry.example.com/adept"
  imageTag: "v1.0.20260529"
```
