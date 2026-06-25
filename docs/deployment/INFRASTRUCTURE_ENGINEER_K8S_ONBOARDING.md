# Infrastructure Engineer K8s Onboarding Guide

## Welcome Infrastructure Engineers! 👋

This guide helps infrastructure engineers deploy and manage the ADEPT Scientific Workbench on Kubernetes clusters, from local development to production environments.

## Table of Contents
1. [Overview](#overview)
2. [Local Kubernetes Setup](#local-kubernetes-setup)
3. [ADEPT Architecture on K8s](#adept-architecture-on-k8s)
4. [Migration from Docker Compose](#migration-from-docker-compose)
5. [Deployment Workflow](#deployment-workflow)
6. [Production Considerations](#production-considerations)
7. [Troubleshooting Guide](#troubleshooting-guide)
8. [Security Best Practices](#security-best-practices)

---

## Overview

ADEPT is a three-tier distributed system that orchestrates AI agents for scientific computing. The Kubernetes deployment uses Helm charts to manage:

- **20+ microservices** across 3 architectural tiers
- **4 database systems** (PostgreSQL, Redis, ChromaDB, Keycloak)
- **Persistent storage** for user data and model artifacts
- **Service mesh** for inter-service communication
- **Authentication/Authorization** via Keycloak

### Key Differences from Docker Compose

| Aspect | Docker Compose | Kubernetes |
|--------|---------------|------------|
| **Networking** | Bridge networks | Service discovery via DNS |
| **Storage** | Bind mounts/volumes | PersistentVolumeClaims |
| **Secrets** | .env files | Secret resources |
| **Scaling** | Manual | HorizontalPodAutoscaler |
| **Health** | depends_on | Liveness/Readiness probes |
| **Init** | Scripts | Init containers/Jobs |

---

## Local Kubernetes Setup

### Platform Comparison

| Platform | Best For | Pros | Cons |
|----------|----------|------|------|
| **k3d** | Development | Fast, lightweight, LoadBalancer support | Limited features |
| **minikube** | Testing | Full K8s features, addons | Resource heavy |
| **kind** | CI/CD | Docker-in-Docker, scriptable | No LoadBalancer |

### Recommended: k3d Setup

```bash
# Install k3d
curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash

# Create cluster with proper port mappings
k3d cluster create adept-local \
  --servers 1 \
  --agents 2 \
  --port "8503:80@loadbalancer" \    # Streamlit v2 UI
  --port "8081:8081@loadbalancer" \  # API Gateway
  --port "8080:8080@loadbalancer" \  # Keycloak Admin
  --volume "$(pwd)/data:/data" \     # Shared data
  --k3s-arg "--disable=traefik@server:*" # Disable default ingress

# Verify cluster
kubectl cluster-info
kubectl get nodes
```

### Docker Image Management

Since local K8s clusters can't directly access your local Docker daemon:

```bash
# Build images locally
make build

# Import to k3d cluster
for image in $(docker images --format "{{.Repository}}:{{.Tag}}" | grep agentic-framework); do
  k3d image import $image -c adept-local
done

# Verify images are available
docker exec k3d-adept-local-agent-0 crictl images | grep agentic-framework
```

---

## ADEPT Architecture on K8s

### Service Tiers

```yaml
# Tier 1: Gateway Layer (Public-facing)
- agent-gateway     # JWT auth, API routing
- nginx             # Reverse proxy, SSL termination
- streamlit-v2      # Web UI (port 8503)
- gateway-registry  # Service discovery

# Tier 2: Orchestration (Business Logic)
- orchestration-service  # OpenAI-compatible API, agent orchestration

# Tier 3: Tool Servers (Stateless Executors)
- mcp-server         # General scientific tools
- sandbox-mcp-server # Secure code execution (privileged)
- hpc-mcp-server     # HPC/Nextflow pipelines

# Data Layer (Stateful Services)
- postgresql  # Conversation state, metadata
- redis       # Session cache, rate limiting
- chromadb    # Vector database for RAG
- keycloak    # Identity management
```

### Network Architecture

```
Internet
    │
    ▼
LoadBalancer/Ingress (nginx)
    │
    ├─► Agent Gateway (:8081)
    │      │
    │      ├─► Orchestration Service (:8084)
    │      │      │
    │      │      ├─► MCP Server (:8088)
    │      │      ├─► Sandbox MCP (:8089) [privileged]
    │      │      └─► HPC MCP (:8090)
    │      │
    │      └─► Gateway Registry (:8086)
    │
    └─► Streamlit v2 (:8503)
           │
           └─► Agent Gateway (internal)
```

### Storage Architecture

```yaml
PersistentVolumes:
  postgresql-data:     10Gi  # Database storage
  redis-data:          1Gi   # Cache persistence
  chromadb-data:       5Gi   # Vector embeddings
  uploaded-files:      10Gi  # User file uploads
  keycloak-data:       5Gi   # Identity data
```

---

## Migration from Docker Compose

### Step 1: Analyze Docker Compose Files

```bash
# Current Docker Compose structure
deployment/local/docker-compose/
├── docker-compose.base.yaml     # Infrastructure
├── docker-compose.core.yaml     # Application services
└── docker-compose.langfuse.yaml # Observability (optional)
```

### Step 2: Map to Kubernetes Resources

| Docker Compose | Kubernetes Resource | Location |
|----------------|-------------------|----------|
| `services:` | Deployment + Service | `templates/*-deployment.yaml` |
| `volumes:` | PersistentVolumeClaim | Within deployment templates |
| `networks:` | Service (ClusterIP) | Automatic via DNS |
| `environment:` | ConfigMap | `templates/configmap.yaml` |
| `secrets:` | Secret | `templates/secrets.yaml` |
| `depends_on:` | Init containers | Within deployment specs |
| `ports:` | Service ports | Service definitions |

### Step 3: Handle Init Logic

Docker Compose init scripts → Kubernetes Jobs:

```yaml
# templates/init-jobs.yaml
- postgres-init: Creates databases
- keycloak-init: Configures realm, users, clients
- chromadb-init: Creates default collections
```

### Step 4: Environment Variables

```bash
# Extract from .env → ConfigMap + Secrets
grep -v '^#' .env | grep -v '^$' > env.clean

# Separate secrets
grep -E 'PASSWORD|SECRET|KEY|TOKEN' env.clean > secrets.env
grep -vE 'PASSWORD|SECRET|KEY|TOKEN' env.clean > config.env

# Create K8s resources
kubectl create configmap adept-config --from-env-file=config.env -n adept
kubectl create secret generic adept-secrets --from-env-file=secrets.env -n adept
```

---

## Deployment Workflow

### 1. Pre-deployment Checklist

```bash
# ✓ Cluster ready
kubectl cluster-info

# ✓ Required tools
helm version  # v3+
kubectl version

# ✓ Namespace created
kubectl create namespace adept

# ✓ Storage class available
kubectl get storageclass

# ✓ Images available (local or registry)
docker images | grep agentic-framework
```

### 2. Configure Values

```bash
cd infra/helm/adept-local

# Create custom values
cp values.yaml values.custom.yaml

# Edit key sections:
# - Resource limits (based on cluster capacity)
# - LLM provider credentials
# - Persistence settings
# - Replica counts
```

### 3. Deploy with Helm

```bash
# Dry run first
helm install adept . \
  --namespace adept \
  --values values.custom.yaml \
  --dry-run --debug

# Actual deployment
helm install adept . \
  --namespace adept \
  --values values.custom.yaml \
  --wait --timeout 10m

# Monitor deployment
watch kubectl get pods,pvc,svc -n adept
```

### 4. Verify Deployment

```bash
# Check pod status
kubectl get pods -n adept
# All should be Running/Completed

# Check init jobs
kubectl get jobs -n adept
# All should be Complete

# Check services
kubectl get svc -n adept
# All should have endpoints

# Test internal DNS
kubectl run -it --rm debug \
  --image=busybox \
  --restart=Never \
  -n adept \
  -- nslookup adept-agent-gateway
```

### 5. Access Application

```bash
# Port forwarding (development)
kubectl port-forward -n adept svc/adept-streamlit-v2 8503:8503 &
kubectl port-forward -n adept svc/adept-agent-gateway 8081:8081 &

# Access points
# Streamlit UI: http://localhost:8503
# API Gateway: http://localhost:8081/v1
# Default login: notebook-user / notebook-password
```

---

## Production Considerations

### High Availability

```yaml
# values.yaml adjustments for HA
agentGateway:
  replicaCount: 3
  affinity:
    podAntiAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
      - topologyKey: kubernetes.io/hostname

nginx:
  replicaCount: 2

postgresql:
  replication:
    enabled: true
    slaveReplicas: 2
```

### Resource Management

```yaml
# Production resource limits
resources:
  orchestrationService:
    limits:
      cpu: 4000m
      memory: 8Gi
    requests:
      cpu: 2000m
      memory: 4Gi

  mcpServers:
    limits:
      cpu: 2000m
      memory: 4Gi
    requests:
      cpu: 1000m
      memory: 2Gi
```

### Autoscaling

```yaml
# HorizontalPodAutoscaler example
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: agent-gateway-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: adept-agent-gateway
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

### Monitoring Stack

```bash
# Deploy Prometheus + Grafana
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace

# ServiceMonitor for ADEPT
kubectl apply -f - <<EOF
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: adept-metrics
  namespace: adept
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: adept-local
  endpoints:
  - port: metrics
    interval: 30s
EOF
```

---

## Troubleshooting Guide

### Common Issues and Solutions

#### 1. Pods Stuck in Pending

```bash
# Check events
kubectl describe pod <pod-name> -n adept

# Common causes:
# - Insufficient resources
kubectl top nodes

# - PVC not bound
kubectl get pvc -n adept

# - Image pull errors
kubectl get events -n adept --sort-by='.lastTimestamp'
```

#### 2. Init Jobs Failing

```bash
# Check job logs
kubectl logs job/adept-postgres-init -n adept

# Restart job
kubectl delete job adept-postgres-init -n adept
kubectl create job adept-postgres-init --from=cronjob/postgres-init -n adept
```

#### 3. Service Connectivity Issues

```bash
# Test DNS resolution
kubectl exec -it <pod> -n adept -- nslookup adept-orchestration

# Check endpoints
kubectl get endpoints -n adept

# Verify network policies (if enabled)
kubectl get networkpolicy -n adept
```

#### 4. Persistent Volume Issues

```bash
# Check PV/PVC status
kubectl get pv,pvc -n adept

# For local development - check host path
kubectl get pv <pv-name> -o yaml | grep path

# Reclaim policy issues
kubectl patch pv <pv-name> -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'
```

### Debug Commands

```bash
# Full diagnostic dump
kubectl cluster-info dump --namespace adept --output-directory=/tmp/adept-debug

# Resource usage
kubectl top pods -n adept --containers

# Recent events
kubectl get events -n adept --sort-by='.lastTimestamp' | head -20

# Exec into pod for debugging
kubectl exec -it <pod-name> -n adept -- /bin/bash

# Copy files from pod
kubectl cp adept/<pod-name>:/path/to/file ./local-file
```

---

## Security Best Practices

### 1. RBAC Configuration

```yaml
# ServiceAccount with minimal permissions
apiVersion: v1
kind: ServiceAccount
metadata:
  name: adept-sa
  namespace: adept
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: adept-role
  namespace: adept
rules:
- apiGroups: [""]
  resources: ["pods", "services"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["batch"]
  resources: ["jobs"]
  verbs: ["create", "get", "list"]
```

### 2. Network Policies

```yaml
# Restrict pod-to-pod communication
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: adept-network-policy
  namespace: adept
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: adept-local
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: adept
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          name: adept
```

### 3. Secret Management

```bash
# Use Sealed Secrets for GitOps
kubectl apply -f https://github.com/bitnami-labs/sealed-secrets/releases/download/v0.18.0/controller.yaml

# Encrypt secrets
echo -n "mypassword" | kubectl create secret generic mysecret \
  --dry-run=client \
  --from-file=password=/dev/stdin \
  -o yaml | kubeseal -o yaml > sealed-secret.yaml
```

### 4. Pod Security Standards

```yaml
# Enforce security contexts
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  fsGroup: 1000
  capabilities:
    drop:
    - ALL
  readOnlyRootFilesystem: true
```

### 5. Image Scanning

```bash
# Scan images before deployment
trivy image agentic-framework-orchestration-service:latest

# Admission webhook for runtime scanning
kubectl apply -f https://raw.githubusercontent.com/aquasecurity/trivy-operator/main/deploy/static/trivy-operator.yaml
```

---

## Backup and Recovery

### Database Backups

```bash
# PostgreSQL backup
kubectl exec -it adept-postgresql-0 -n adept -- \
  pg_dumpall -U postgres > backup-$(date +%Y%m%d).sql

# Restore
kubectl exec -i adept-postgresql-0 -n adept -- \
  psql -U postgres < backup-20240101.sql
```

### Volume Snapshots

```yaml
# VolumeSnapshot (requires CSI driver)
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: adept-data-snapshot
spec:
  volumeSnapshotClassName: csi-snapclass
  source:
    persistentVolumeClaimName: adept-postgresql-pvc
```

---

## Performance Tuning

### JVM Services (if applicable)

```yaml
env:
- name: JAVA_OPTS
  value: "-Xmx2g -Xms1g -XX:+UseG1GC"
```

### Database Optimization

```yaml
postgresql:
  postgresqlConfiguration:
    max_connections: "200"
    shared_buffers: "256MB"
    effective_cache_size: "1GB"
```

### Redis Tuning

```yaml
redis:
  master:
    extraFlags:
    - "--maxmemory 512mb"
    - "--maxmemory-policy allkeys-lru"
```

---

## Useful Scripts

### Quick Deployment Script

```bash
#!/bin/bash
# deploy-adept.sh

set -e

NAMESPACE="adept"
RELEASE="adept"
CHART_PATH="./infra/helm/adept-local"

echo "🚀 Deploying ADEPT to Kubernetes..."

# Create namespace
kubectl create namespace $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -

# Deploy
helm upgrade --install $RELEASE $CHART_PATH \
  --namespace $NAMESPACE \
  --values $CHART_PATH/values.yaml \
  --wait --timeout 10m

# Show status
kubectl get pods -n $NAMESPACE
echo "✅ Deployment complete!"
echo "Access UI at: http://localhost:8503 (after port-forward)"
```

### Health Check Script

```bash
#!/bin/bash
# health-check.sh

NAMESPACE="adept"

echo "Checking ADEPT health..."

# Check pods
PODS_NOT_READY=$(kubectl get pods -n $NAMESPACE -o json | jq '.items[] | select(.status.phase != "Running" and .status.phase != "Succeeded") | .metadata.name' | wc -l)

if [ "$PODS_NOT_READY" -gt 0 ]; then
  echo "❌ Some pods are not ready:"
  kubectl get pods -n $NAMESPACE | grep -v "Running\|Completed"
else
  echo "✅ All pods healthy"
fi

# Check services
kubectl get svc -n $NAMESPACE

# Check recent events
echo "Recent events:"
kubectl get events -n $NAMESPACE --sort-by='.lastTimestamp' | head -5
```

---

## Next Steps

1. **Review** [ADEPT Platform Engineering Guide](./PLATFORM_AI_ENGINEER_ONBOARDING.md)
2. **Review** [ASOPB CI Configuration Reference](../ci/ASOPB_CI_CONFIGURATION.md) for GitHub Actions workflow triggers, conditional ML scanning, and CI troubleshooting
3. **Explore** the Helm chart templates in `infra/helm/adept-local/templates/`
4. **Test** deployment on your local K8s cluster
5. **Customize** values.yaml for your environment
6. **Join** the ADEPT community for support

---

## Support

For infrastructure-specific questions:
- Review this guide and [infra/helm/README.md](../infra/helm/README.md)
- Check Kubernetes events and logs
- Open an issue with infrastructure tag

Remember: Infrastructure is code - version control everything! 🚀