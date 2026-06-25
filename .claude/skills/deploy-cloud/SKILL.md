---
name: deploy-cloud
description: Guided workflow to deploy ADEPT on cloud infrastructure (AWS, Azure, or GCP) as a single VM or A2A mesh pair. Covers provisioning, OS prep, stack deployment, and optional A2A federation between two independently-deployed stacks.
disable-model-invocation: true
allowed-tools: Bash(git *) Bash(make *) Bash(aws *) Bash(az *) Bash(gcloud *) Bash(pulumi *) Bash(grep *) Bash(find *) Bash(ls *) Bash(cat *) Bash(ssh *) Bash(curl *) Read Write Edit
argument-hint: [optional: aws | azure | gcp] [optional: single | mesh]
---

You are guiding an ADEPT developer through deploying one or two cloud VMs and optionally establishing A2A (Agent-to-Agent) federation between them.

Do not use emojis in any output.
Do not run any destructive or long-running commands without explicit developer confirmation.
Pause for developer confirmation at each phase gate before proceeding.

---

## Cloud and Track Selection

If `$ARGUMENTS` provides cloud and/or track, use them. Otherwise ask both:

**"Which cloud provider?"**
- `aws` — AWS EC2 via CDK
- `azure` — Azure VM via Pulumi + AKS
- `gcp` — GCP Compute Engine via Terraform

**"Which deployment track?"**
- `single` — Deploy one ADEPT development environment
- `mesh` — Deploy two ADEPT instances and establish bidirectional A2A federation

| Track | Phases |
|-------|--------|
| single | 1, 2, 3, 4, 5, 6 |
| mesh | 1, 2, 3, 4, 5, 6, 7, 8, 9 |

---

## Cloud Provider Comparison

| Property | AWS | Azure | GCP |
|----------|-----|-------|-----|
| IaC Tool | CDK (Python) | Pulumi (Python) | Terraform (HCL) |
| VM Type | EC2 (t3.2xlarge) | Standard_D8s_v3 | n2-standard-8 |
| K8s Option | EKS + Helm | AKS + Helm | GKE + Helm |
| Provisioning Dir | `devtools/skypilot/` | `infra/azure/pulumi/` | `infra/gcp/` (planned) |

---

## Deployment Target Matrix

| Target | Use Case | Infrastructure |
|--------|----------|---------------|
| Single Dev VM | Day-to-day development, testing, demos | 1x VM (8 vCPU, 32 GB) |
| A2A Mesh Pair | Cross-gateway delegation, multi-site federation testing | 2x VM (8 vCPU, 32 GB) |
| Preproduction | Staging validation before public release | 2x VM (larger) + LB |

---

## Phase 1: Prerequisites

Verify the developer has the required tools and credentials for their chosen cloud.

### Checks by Cloud

**AWS:**
```bash
aws sts get-caller-identity          # AWS credentials
cd devtools/skypilot && make cdk-list # CDK installed
ansible --version                     # Ansible available
```

**Azure:**
```bash
az account show                       # Azure CLI authenticated
az aks list -o table                  # Can list AKS clusters
cd infra/azure/pulumi && pulumi stack ls  # Pulumi configured
ansible --version
```

**GCP:**
```bash
gcloud auth list                      # GCP authenticated
gcloud compute instances list         # Can list instances
terraform --version                   # Terraform installed
ansible --version
```

### Required Information

Ask the developer for:
1. **Cloud region**: e.g., `us-west-2` (AWS), `eastus` (Azure), `us-central1` (GCP)
2. **Instance type**: Default varies by cloud (see provider comparison above). GPU needed?
3. **Deploy context name**: Used for state isolation (e.g., `aws-<account-id>-dev`)
4. **User label**: Identifies their stack (default: `$USER`)

For **mesh** track, also ask:
5. **Second user label**: e.g., `mesh-vm2` (distinguishes the two stacks)
6. **Same cloud or cross-cloud?**: Both VMs on same provider, or one AWS + one Azure?

### Gate Check

- [ ] Cloud CLI authenticated (no auth errors)
- [ ] IaC tool can list resources
- [ ] Ansible available on control plane
- [ ] Developer confirmed instance type and labels

---

## Phase 2: Provision VM(s)

Provision one (or two) VMs using the cloud-appropriate IaC tool.

### AWS (CDK)

```bash
cd devtools/skypilot

# VM 1 (both tracks)
make cdk-deploy CDK_USER_LABEL=<user-label> CDK_ENV_LABEL=dev CDK_STOP_MINUTES=240

# Retrieve connection info (PrivateIP, InstanceId, SSHCommand)
make cdk-get-connection-info

# Retrieve SSH key
make cdk-retrieve-key
```

For **mesh** track, repeat with different user label:
```bash
make cdk-deploy CDK_USER_LABEL=<second-label> CDK_ENV_LABEL=dev CDK_STOP_MINUTES=240
make cdk-get-connection-info
make cdk-retrieve-key
```

### Azure (Pulumi)

```bash
cd infra/azure/pulumi

# VM 1
pulumi up --stack dev-vm1

# Get outputs (IP, resource group, SSH command)
pulumi stack output vm1_ip
pulumi stack output ssh_command
```

For **mesh** track:
```bash
pulumi up --stack dev-vm2
pulumi stack output vm2_ip
```

### GCP (Terraform)

```bash
cd infra/gcp

# VM 1
terraform apply -var="instance_name=adept-dev-1" -var="machine_type=n2-standard-8"

# Get outputs
terraform output instance_ip
```

For **mesh** track:
```bash
terraform apply -var="instance_name=adept-dev-2" -var="machine_type=n2-standard-8"
terraform output instance_ip
```

### Gate Check

- [ ] VM 1 IP address obtained
- [ ] (mesh) VM 2 IP address obtained
- [ ] SSH/SSM connectivity confirmed

Record these values for all subsequent phases:
- `VM1_IP=<ip>`
- (mesh) `VM2_IP=<ip>`

---

## Phase 3: Wait for Readiness

VMs need time to initialize.

### AWS

```bash
cd devtools/skypilot

# Poll until SSM Online (typically 3-5 minutes)
make cdk-instance-status
```

Repeat every 60 seconds until: Instance state = `running`, SSM ping = `Online`.

### Azure / GCP

```bash
# SSH should be available within 1-2 minutes
ssh -o ConnectTimeout=10 <user>@$VM1_IP "hostname"
```

### Gate Check

- [ ] VM 1: Reachable via SSH or SSM
- [ ] (mesh) VM 2: Reachable via SSH or SSM

---

## Phase 4: OS Preparation (Ansible)

Install Docker, Python, configure storage and firewall on each VM. Ansible works identically regardless of cloud provider -- it only needs SSH access.

### Commands

**AWS** (via SkyPilot Makefile):
```bash
cd devtools/skypilot
make ansible-prepare-vm ANSIBLE_TARGET_HOST=$VM1_IP ANSIBLE_SSH_KEY=<key-filename>
```

**Azure / GCP** (direct Ansible):
```bash
cd deployment/ansible
ansible-playbook -i "$VM1_IP," playbooks/prepare-rocky-vm.yml \
    --user <ssh-user> --private-key <key-path> \
    -e "data_volume=/data site_name=cloud"
```

This runs `deployment/ansible/playbooks/prepare-rocky-vm.yml` with 10 phases:
- Docker CE installation
- Python 3.11 setup
- /data volume mount
- Firewall configuration
- Source code transfer (tarball from git HEAD)
- Symlinks and permissions

For **mesh** track (can run in parallel):
```bash
# VM 2 -- same command with different IP
make ansible-prepare-vm ANSIBLE_TARGET_HOST=$VM2_IP ANSIBLE_SSH_KEY=<key-filename>
```

### MANDATORY Post-Ansible Step: Regenerate Keycloak Credentials

Ansible tarball extraction OVERWRITES `.env-keycloak-credentials-dir/` files with empty templates from the source tree. You MUST regenerate them from the running Keycloak instance BEFORE any validation.

```bash
# On the target VM (via SSM or SSH):
cd $ADEPT_DIR   # Ansible deploys to /data/<volume>/adept-<datestamp>
make fix-credentials    # Regenerates all credential files from Keycloak DB
make sync-credentials   # Syncs to project root for validation targets
```

### Gate Check

Verify via SSM or SSH:

```bash
# On target VM
docker --version    # Docker CE 29.x
python3.11 --version
ls $ADEPT_DIR/  # Source code present
```

- [ ] VM 1: Docker installed, source present, credentials regenerated
- [ ] (mesh) VM 2: Docker installed, source present, credentials regenerated

---

## Phase 4.5: Credential Provisioning

Ansible creates `.env` from `.env.example` with empty placeholders. You MUST inject real credentials before running quickstart, or image pulls will fail and LLM services won't connect.

### Required Credentials

These are external service keys that cannot be derived from the instance profile:

| Variable | Purpose | Failure Mode Without |
|----------|---------|---------------------|
| `DOCKERHUB_USERNAME` + `DOCKERHUB_TOKEN` | Docker Hub authenticated pulls | Image build fails with 429 Too Many Requests |
| `AZURE_API_KEY` + `AZURE_API_BASE` + `AZURE_API_VERSION` | Azure OpenAI model access | Agent can't use Azure models |
| `BRAVE_API_KEY` | Web search tool (MCP server) | WebSearch tool returns errors |
| `DEFAULT_LLM_MODEL` + `LANGCHAIN_LLM_MODEL` | Model routing config | Uses .env.example defaults |
| `CODING_AGENT_DEFAULT_MODEL` + `CODING_AGENT_AWS_REGION_NAME` | Coding agent model config | Falls back to default model |

### NOT Copied (provided by instance profile on AWS)

On AWS EC2, do NOT inject `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY`. The CDK stack attaches an IAM instance profile with Bedrock access. Env vars would shadow the instance profile.

### Injection Method (via SSH)

```bash
# Extract only external service credentials (NOT AWS keys)
grep -E '^(AZURE_API_KEY|AZURE_API_BASE|AZURE_API_VERSION|BRAVE_API_KEY|DOCKERHUB_USERNAME|DOCKERHUB_TOKEN|DEFAULT_LLM_MODEL|LANGCHAIN_LLM_MODEL|RAG_DEFAULT_MODEL|CODING_AGENT_DEFAULT_MODEL|CODING_AGENT_AWS_REGION_NAME|AWS_REGION_NAME)' .env > /tmp/creds_patch.env
scp -i $KEY /tmp/creds_patch.env $USER@$VM_IP:/tmp/
ssh -i $KEY $USER@$VM_IP "cd \$ADEPT_DIR && cat /tmp/creds_patch.env >> .env && rm /tmp/creds_patch.env"
rm /tmp/creds_patch.env
```

### Injection Method (via SSM for AWS)

For AWS instances, use the SSM heredoc pattern:

```bash
cd devtools/skypilot

# Step 1: Collect credentials into base64 payload
CREDS_B64=$(grep -E '^(AZURE_API_KEY|AZURE_API_BASE|AZURE_API_VERSION|BRAVE_API_KEY|DEFAULT_LLM_MODEL|LANGCHAIN_LLM_MODEL|RAG_DEFAULT_MODEL|CODING_AGENT_DEFAULT_MODEL|CODING_AGENT_AWS_REGION_NAME|AWS_REGION_NAME)' ../../.env | base64 -w0)

# Step 2: Write payload to remote instance
make cdk-ssm-run CMD="#!/bin/bash
echo '$CREDS_B64' | base64 -d > /tmp/creds_to_inject.env
echo \"Wrote \$(wc -l < /tmp/creds_to_inject.env) credential lines\""

# Step 3: Merge into .env on remote
make cdk-ssm-run CMD='#!/bin/bash
cd $(ls -d /data/*/adept-* | head -1)
cat /tmp/creds_to_inject.env >> .env
rm /tmp/creds_to_inject.env
echo "Credentials injected"'

# Step 4: Authenticate Docker Hub
make cdk-ssm-run CMD='#!/bin/bash
cd $(ls -d /data/*/adept-* | head -1)
DOCKERHUB_USERNAME=$(grep "^DOCKERHUB_USERNAME=" .env | cut -d= -f2)
DOCKERHUB_TOKEN=$(grep "^DOCKERHUB_TOKEN=" .env | cut -d= -f2)
echo "$DOCKERHUB_TOKEN" | docker login -u "$DOCKERHUB_USERNAME" --password-stdin'
```

### Verify

```bash
# Confirm Docker Hub auth works
ssh -i $KEY $USER@$VM_IP "docker pull hello-world && echo 'Docker Hub auth OK'"
```

### Gate Check

- [ ] Docker Hub login succeeds on remote instance
- [ ] .env has credential vars populated (not just placeholders)
- [ ] (mesh) Both VMs have credentials injected

---

## Phase 5: Stack Deployment

Launch the full ADEPT stack on each VM.

### Commands (via SSM or SSH)

On each target VM:

```bash
ADEPT_DIR=$(ls -d /data/*/adept-* | head -1)
cd $ADEPT_DIR

# Full stack startup (25-30 minutes first run, 5-10 minutes on subsequent runs)
nohup ./scripts/quick-start-adept-and-subsystems.sh > logs/quickstart-$(date +%Y%m%d-%H%M).log 2>&1 &

# Monitor
tail -f logs/quickstart-*.log | grep -E "Phase|DONE|Error"
```

### Monitoring Progress

```bash
# Check container count (grows from 0 to 45+ over 25 minutes)
docker ps --format '{{.Names}}' | wc -l

# Tail the log
tail -10 logs/quickstart-*.log

# Check for failures
grep -i 'error\|failed\|fatal' logs/quickstart-*.log | tail -5
```

### Common Failures

| Failure | Symptom | Fix |
|---------|---------|-----|
| Docker Hub rate limit | `429 Too Many Requests` during image build | Run Phase 4.5 (credential provisioning) first |
| conda env creation timeout | `sandbox_mcp_server` build fails | Retry (transient DNS); or skip sandbox with `SKIP_SANDBOX=1` |
| Keycloak bootstrap race | Services start before Keycloak is ready | Automatic retry built into quickstart |
| Disk space | Build cache fills /data volume | `docker system prune -f` then retry |

### Gate Check

After quickstart completes on each VM:

```bash
# Verify container count (expect 45-50)
docker ps | wc -l

# Health check
make validate-service-health

# Quick smoke test
curl -s http://localhost:8083/v1/models | head -5
```

- [ ] VM 1: 45+ containers, health check passes
- [ ] (mesh) VM 2: 45+ containers, health check passes

### Wall Clock Time

| Scenario | Duration |
|----------|----------|
| First deploy (all images built from scratch) | 25-35 minutes |
| Retry after partial failure (cached layers) | 10-20 minutes |
| Subsequent deploys (images cached) | 5-10 minutes |

For **single** track: proceed to Phase 6 (final validation).
For **mesh** track: proceed to Phase 6 (A2A configuration).

---

## Phase 6: Validation (single track) / A2A Configuration (mesh track)

### Single Track -- Final Validation

```bash
# Full validation suite
make validate

# Connect Claude Code to this instance
# Run /connect-adept with the VM's IP
```

DONE. The developer now has a running ADEPT development environment.

---

### Mesh Track -- A2A Configuration

Configure both VMs to trust each other's Keycloak JWKS and allow peer registration.

### Configuration Required (on each VM)

On **VM 1** (`.env`):

```bash
PUBLIC_GATEWAY_URL=https://$VM1_IP
NGINX_PUBLIC_FQDN=$VM1_IP
PUBLIC_BASE_URL=https://$VM1_IP
ALLOWED_PEER_CIDRS=10.0.0.0/8
A2A_TRUSTED_PEER_JWKS_URLS=https://$VM2_IP/realms/master/protocol/openid-connect/certs
```

On **VM 2** (`.env`):

```bash
PUBLIC_GATEWAY_URL=https://$VM2_IP
NGINX_PUBLIC_FQDN=$VM2_IP
PUBLIC_BASE_URL=https://$VM2_IP
ALLOWED_PEER_CIDRS=10.0.0.0/8
A2A_TRUSTED_PEER_JWKS_URLS=https://$VM1_IP/realms/master/protocol/openid-connect/certs
```

After configuration, rebuild the agent gateway on both VMs:

```bash
make rebuild-gateway
```

### Gate Check

```bash
docker exec agent_gateway env | grep A2A_TRUSTED_PEER_JWKS_URLS
docker exec agent_gateway env | grep PUBLIC_GATEWAY_URL
```

- [ ] VM 1: A2A env vars configured, gateway rebuilt
- [ ] VM 2: A2A env vars configured, gateway rebuilt

---

## Phase 7: Bidirectional Peer Registration

Register each stack as a peer of the other.

### Commands

From **VM 1** (register VM 2 as peer):

```bash
python scripts/a2a/manage_gateway_registrations.py register \
    --alias vm2-gateway \
    --ip $VM2_IP \
    --description "ADEPT VM2 Gateway" \
    --tags mesh,dev
```

From **VM 2** (register VM 1 as peer):

```bash
python scripts/a2a/manage_gateway_registrations.py register \
    --alias vm1-gateway \
    --ip $VM1_IP \
    --description "ADEPT VM1 Gateway" \
    --tags mesh,dev
```

### Verify Registration

```bash
# On VM 1
python scripts/a2a/manage_gateway_registrations.py verify --alias vm2-gateway

# On VM 2
python scripts/a2a/manage_gateway_registrations.py verify --alias vm1-gateway
```

### Gate Check

- [ ] VM 1 can reach VM 2's agent-card at `https://$VM2_IP/a2a/.well-known/agent-card.json`
- [ ] VM 2 can reach VM 1's agent-card at `https://$VM1_IP/a2a/.well-known/agent-card.json`

---

## Phase 8: Cross-Host A2A Validation

Run the cross-host validation suite to confirm bidirectional task delegation works.

### Commands

From **VM 1**:

```bash
export A2A_PEER_GATEWAY_URL=https://$VM2_IP
make validate-a2a-cross-host-responses-api
```

From **VM 2**:

```bash
export A2A_PEER_GATEWAY_URL=https://$VM1_IP
make validate-a2a-cross-host-responses-api
```

### What the Tests Validate

- JWKS endpoint reachability across VMs
- Cross-host JWT authentication (service token + user token)
- Thread CRUD operations on peer gateway
- Chat completions via A2A delegation
- File operations across gateways
- Security boundary enforcement

### Gate Check

- [ ] VM 1 to VM 2: Cross-host validation passes
- [ ] VM 2 to VM 1: Cross-host validation passes

---

## Phase 9: Connect Claude Code to Mesh

Optionally connect Claude Code (or other clients) to one or both ADEPT instances.

```bash
# Connect to VM 1
/connect-adept  # Use URL: https://$VM1_IP/v1

# Or connect to VM 2
/connect-adept  # Use URL: https://$VM2_IP/v1
```

The connected instance can delegate tasks to its peer via the A2A mesh.

---

## Troubleshooting

### CDK deploy fails

Ensure AWS credentials are valid (`aws sts get-caller-identity`) and the CDK stack uses allowed subnets/VPCs.

### Pulumi up fails with auth error (Azure)

Run `az login` and ensure correct subscription is selected: `az account set --subscription <id>`.

### SSM never shows Online (AWS)

- Check instance is in a private subnet with NAT/VPC endpoints for SSM
- Verify IAM role has `AmazonSSMManagedInstanceCore` policy

### Ansible fails with "unreachable"

- Verify SSH key matches the provisioned instance
- Check security group / NSG / firewall allows SSH from your IP
- Ensure SSH user matches AMI default (ubuntu for Ubuntu, ec2-user for Amazon Linux, azureuser for Azure)

### A2A registration fails with "SSRF blocked"

`ALLOWED_PEER_CIDRS` not set or doesn't include the peer's subnet. Add the VPC CIDR.

### JWKS validation fails

- Verify `A2A_TRUSTED_PEER_JWKS_URLS` is correct (include full path to `/certs`)
- Verify nginx on the peer VM is accepting HTTPS on port 443
- Check security group has port 443 ingress rule

---

## Wall Clock Timing (Single Track)

Measured on t3.2xlarge (8 vCPU, 32 GB) with 200 GB gp3 volume:

| Phase | Duration | Notes |
|-------|----------|-------|
| Phase 1: Prerequisites | 1 min | Verify tools, confirm settings |
| Phase 2: VM provisioning | 30-90 sec | Varies by provider |
| Phase 3: Wait for readiness | 3-5 min | SSH/SSM agent registration |
| Phase 4: Ansible prepare-vm | 4-6 min | Source transfer + 84 tasks |
| Phase 4.5: Credential provisioning | 30-60 sec | SSH/SSM round-trip |
| Phase 5: Stack deployment (first) | 25-35 min | All images built from scratch |
| **Total (first deploy)** | **~40-50 min** | End-to-end |

---

## Reference

| Resource | Path |
|----------|------|
| CDK/SkyPilot targets | `devtools/skypilot/Makefile` |
| SkyPilot onboarding | `devtools/skypilot/ONBOARDING.md` |
| Ansible playbooks | `deployment/ansible/playbooks/` |
| A2A registration CLI | `scripts/a2a/manage_gateway_registrations.py` |
| Cross-host validation | `make validate-a2a-cross-host-responses-api` |
| A2A federation guide | `docs/guides/A2A_IP_BASED_VM_FEDERATION_GUIDE.md` |
| A2A quickstart | `docs/guides/A2A_IP_BASED_VM_FEDERATION_QUICKSTART.md` |
| Multi-stack compose | `deployment/local/docker-compose/docker-compose.multi-stack.yaml` |
| K8s onboarding | `docs/deployment/INFRASTRUCTURE_ENGINEER_K8S_ONBOARDING.md` |
