# ADEPT Batch Deployment - Executive Summary
## Infrastructure Review and Workshop Deployment Readiness

**Date**: 2026-01-22
**Status**: 60% Ready (Strong foundation, orchestration layer needed)

---

## Current State Assessment

### ✅ What Exists and Works (60%)

1. **Multi-User CDK Architecture** (100% Complete)
   - Per-user parameterized deployments: `ADE-{env}-{user}-Stack`
   - Files: `devtools/aws-cdk/app.py`, `stacks/dev_environment_stack.py`, `stacks/application_stack.py`
   - Supports concurrent deployments with unique stack names

2. **Two Deployment Modes** (100% Complete)
   - **Mode A**: EC2 Instance Provisioning (t3.2xlarge, 500GB data volume, SSH key auto-gen)
   - **Mode B**: Application Stack (ALB + Cognito + WAF + Route53)

3. **Ansible Automation Framework** (90% Complete)
   - Files: `deployment/ansible/playbooks/deploy-infrastructure.yml`, `roles/aws_cdk_deploy/`
   - Configuration-driven deployment via YAML
   - Cloud authentication and validation roles
   - **MISSING**: Batch loop for multiple users

4. **Cognito User Management** (100% Complete)
   - File: `deployment/cloud/aws/cdk-stacks/manage-cognito-users.py`
   - CLI for user CRUD operations (create, delete, reset password, list)

5. **EC2-to-ALB Registration** (100% Complete)
   - File: `deployment/cloud/aws/cdk-stacks/link-ec2-to-alb.sh`
   - Registers EC2 instances to both Streamlit (8503) and JupyterLab (8888) target groups

6. **Instance Management Utilities** (100% Complete)
   - File: `devtools/aws-cdk/scripts/manage-instances.py`
   - List, start, stop, and status commands for all ADEPT instances

### ❌ What's Missing (40%)

1. **Batch Deployment Orchestration** (BLOCKER)
   - Current: Manual deployment one user at a time
   - Needed: Multi-user loop in Ansible playbook
   - File to create: `deployment/ansible/playbooks/deploy-workshop.yml`

2. **Credential Extraction Utilities** (BLOCKER)
   - SSH keys: Manual retrieval from SSM Parameter Store
   - JupyterLab tokens: Manual SSH + docker logs command
   - Files to create: `scripts/workshop/extract-ssh-keys.py`, `scripts/workshop/extract-jupyterlab-tokens.py`

3. **Environment Configuration Generator** (BLOCKER)
   - `.env` files: Manual copy from template
   - Claude Code setup: Manual credential insertion
   - Files to create: `scripts/workshop/generate-env-files.py`, `templates/.env.workshop.template`

4. **Welcome Packet Generation** (BLOCKER)
   - Manual aggregation of credentials
   - No automated participant onboarding
   - File to create: `scripts/workshop/generate-welcome-packets.py`

5. **Workshop Orchestration Config** (BLOCKER)
   - Current: One config file per user (e.g., `adept-config-dev-alice.yml`)
   - Needed: Single workshop config with participant list
   - File to create: `deployment/ansible/config/workshops/workshop-2026-01.yml`

---

## CNAME Mapping Architecture

### URL Pattern
```
{app}.{deployment_id}.{waf_id}.{domain_name}

Example:
  streamlit.ade-dev-scientist1.waf-abc123.amazonaws.com
  jupyter.ade-dev-scientist1.waf-abc123.amazonaws.com
```

### Components
- **Deployment ID**: `ade-{env}-{user}` (e.g., `ade-dev-scientist1`)
- **WAF ID**: Short identifier for DNS (e.g., `waf-abc123`)
- **Domain**: Base domain (e.g., `amazonaws.com`)

### EC2 Instance ID Mapping
- **Storage**: CloudFormation Stack Outputs + DynamoDB table (planned)
- **Table**: `adept-workshop-deployments`
- **Schema**:
  ```json
  {
    "workshop_id": "workshop-2026-01",
    "user": "scientist1",
    "ec2_instance_id": "i-1234567890abcdef0",
    "urls": {
      "streamlit": "streamlit.ade-dev-scientist1.waf-abc123.amazonaws.com",
      "jupyter": "jupyter.ade-dev-scientist1.waf-abc123.amazonaws.com"
    },
    "ssh_key_parameter": "/ec2/keypair/key-00d4fbe3473d7450e"
  }
  ```

### Utility Command
```bash
# List all participant URLs for a workshop
./scripts/workshop/list-participant-urls.py --workshop-id workshop-2026-01
```

---

## Batch Deployment Workflow

### High-Level Steps

```
1. Validate Prerequisites (WAF, VPC, Route53)
2. Generate Participant List from Config
3. Batch Deploy EC2 Stacks (3 at a time)
4. Wait for Cloud-Init Completion
5. Bootstrap ADEPT on Each Instance
6. Batch Deploy App Stacks (ALB + Cognito)
7. Register EC2 to ALB Target Groups
8. Create Cognito Users
9. Extract SSH Keys + JupyterLab Tokens
10. Generate Welcome Packets
11. Validate All Deployments
12. Email Welcome Packets to Participants
```

### Expected Timeline
- **10 participants**: 30-45 minutes total
- **Parallel batches**: 3 deployments at a time
- **Per-participant time**: 3-5 minutes (when parallelized)

---

## Utility Scripts Specification

### 1. SSH Key Extraction
**File**: `scripts/workshop/extract-ssh-keys.py`

**Usage**:
```bash
python3 scripts/workshop/extract-ssh-keys.py \
  --workshop-id workshop-2026-01 \
  --output-dir ~/.ssh/workshop-2026-01/
```

**Output**: PEM files with chmod 400 permissions
```
~/.ssh/workshop-2026-01/ADE-dev-scientist1-key.pem
~/.ssh/workshop-2026-01/ADE-dev-scientist2-key.pem
...
```

### 2. JupyterLab Token Extraction
**File**: `scripts/workshop/extract-jupyterlab-tokens.py`

**Usage**:
```bash
python3 scripts/workshop/extract-jupyterlab-tokens.py \
  --workshop-id workshop-2026-01 \
  --output-file jupyterlab-tokens.csv
```

**Output**: CSV file with tokens
```csv
user,instance_id,jupyter_url,token
scientist1,i-1234567890abcdef0,https://jupyter.ade-dev-scientist1.waf-abc123.amazonaws.com,a3f5c8d9e2b4f7a1c6e8d3b9f2a5c7e1
scientist2,i-0987654321fedcba0,https://jupyter.ade-dev-scientist2.waf-abc123.amazonaws.com,b8d2c4e6f9a1b3d5e7c9a2b4d6e8f0a2
```

### 3. Environment Configuration Generator
**File**: `scripts/workshop/generate-env-files.py`

**Usage**:
```bash
python3 scripts/workshop/generate-env-files.py \
  --workshop-id workshop-2026-01 \
  --template .env.workshop.template \
  --output-dir ./env-files/
```

**Template Variables**:
- `{{workshop_id}}` → `workshop-2026-01`
- `{{username}}` → `scientist1`
- `{{bedrock_access_key_id}}` → IAM user access key
- `{{bedrock_secret_access_key}}` → IAM user secret key
- `{{generated_postgres_password}}` → Secure random password
- `{{generated_keycloak_secret}}` → Secure random secret

### 4. Claude Code Setup Script Generator
**File**: `scripts/workshop/generate-claude-code-setup.sh`

**Output**: Per-participant setup script
```bash
#!/bin/bash
# Claude Code Setup for scientist1

export AWS_ACCESS_KEY_ID="AKIA_SCIENTIST1_BEDROCK"
export AWS_SECRET_ACCESS_KEY="..."
export AWS_REGION_NAME="us-west-2"
export CODING_AGENT_DEFAULT_MODEL="bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"

echo "✅ Claude Code environment configured"
```

### 5. Welcome Packet Generator
**File**: `scripts/workshop/generate-welcome-packets.py`

**Output Structure**:
```
output/workshop-2026-01/welcome-packets/
├── scientist1/
│   ├── welcome.pdf                  # PDF guide
│   ├── credentials.txt              # All credentials
│   ├── ADE-dev-scientist1-key.pem  # SSH key
│   ├── .env                         # Environment file
│   ├── setup-claude-code.sh         # Claude Code setup
│   └── quick-start-guide.md         # Markdown guide
├── scientist2/
│   └── ...
└── index.html                       # Workshop dashboard
```

---

## Ansible Recipe Extensions

### New Playbook: `deploy-workshop.yml`
**File**: `deployment/ansible/playbooks/deploy-workshop.yml`

**Features**:
- Multi-user orchestration with parallel batch processing
- Phase-based deployment (9 phases from EC2 → Welcome Packets)
- Automatic prerequisite validation
- Credential extraction integration
- Post-deployment validation

**Usage**:
```bash
cd deployment/ansible

ansible-playbook playbooks/deploy-workshop.yml \
  --vault-password-file ~/.ansible-vault-password \
  -e "@config/workshops/workshop-2026-01.yml"
```

### New Role: `credential_extraction`
**Directory**: `deployment/ansible/roles/credential_extraction/`

**Tasks**:
- Extract SSH keys from SSM Parameter Store
- Extract JupyterLab tokens via SSM Session Manager
- Generate .env files from templates
- Generate Claude Code setup scripts

---

## Pre-Requisites Management

### 1. WAF WebACL (Shared Across All Participants)
**Status**: Manual deployment required
**ARN Pattern**: `arn:aws:wafv2:us-west-2:867041162975:regional/webacl/adept-workshop-waf/abc123`

**Deployment**:
```bash
aws wafv2 create-web-acl \
  --name adept-workshop-waf \
  --scope REGIONAL \
  --region us-west-2 \
  --default-action Allow={} \
  --rules file://waf-rules.json
```

### 2. EFS (Optional Shared Storage)
**Use Case**: Shared datasets, workshop materials
**Cost**: $0.30/GB-month × 100GB = $30/month

**Deployment** (if needed):
```bash
aws efs create-file-system \
  --region us-west-2 \
  --encrypted \
  --tags Key=Workshop,Value=workshop-2026-01
```

### 3. AWS Resource Quotas
**Critical Quotas**:
- **EC2 vCPUs**: Need 80 for 10 × t3.2xlarge (default: 32) → **Request increase to 128**
- **ALBs**: Need 10 (default: 50) → Sufficient
- **EBS Volumes**: Need 20 (default: 5,000) → Sufficient
- **Route53 Records**: Need 20 (default: 10,000) → Sufficient

**Action Required** (5-7 days lead time):
```bash
aws service-quotas request-service-quota-increase \
  --service-code ec2 \
  --quota-code L-1216C47A \
  --desired-value 128 \
  --region us-west-2
```

---

## Cost Estimation

### Per-Participant Cost (Monthly)
| Resource | Cost |
|----------|------|
| EC2 t3.2xlarge | $300.48 |
| EBS 100GB root + 500GB data | $48.00 |
| ALB | $22.50 |
| Cognito | $0.00 (free tier) |
| Route53 | $1.00 |
| Other | $6.00 |
| **Total** | **$377.88/month** |

### Workshop Scenarios
- **1-Day Workshop (10 participants)**: $254
- **1-Week Workshop (10 participants)**: $1,144
- **Monthly Workshop Series (4 workshops × 10 participants)**: $4,031

### Cost Optimization
- **Stop instances overnight**: 30% savings
- **Right-size to t3.xlarge**: $150/participant/month saved
- **Shared ALB** (future): $202.50/month saved

---

## Implementation Phases

### Phase 1: Foundation Scripts (Week 1) - 3-5 days
- Batch deployment playbook (`deploy-workshop.yml`)
- Workshop configuration schema
- SSH key extraction utility
- JupyterLab token extraction utility

### Phase 2: Environment Configuration (Week 2) - 3-5 days
- `.env` file generator
- Claude Code setup script generator
- IAM user provisioning for Bedrock
- Automated `.env` upload to instances

### Phase 3: Welcome Packet Generation (Week 3) - 3-5 days
- Welcome packet generator (PDF + TXT + Markdown)
- Email template
- Workshop dashboard (HTML)

### Phase 4: Production Hardening (Week 4) - 5-7 days
- Error handling and retry logic
- Parallel deployment optimization
- CloudWatch monitoring
- Rollback procedures

### Phase 5: Documentation and Testing (Week 5) - 3-5 days
- Workshop facilitator guide
- Troubleshooting runbook
- End-to-end test suite

**Total**: 4-5 weeks (17-27 developer-days)

---

## Ansible Building Blocks Already Available

### Existing Roles (Can Be Reused)
1. **cloud_auth**: AWS authentication via credentials
2. **aws_cdk_deploy**: CDK deployment wrapper (single-user)
3. **validation**: Post-deployment validation

### Existing Playbooks (Can Be Extended)
1. **deploy-infrastructure.yml**: Meta-playbook for single user
2. **deploy-aws.yml**: AWS-specific deployment (single user)

### Required Extensions
1. **New Playbook**: `deploy-workshop.yml` (multi-user orchestration)
2. **New Role**: `credential_extraction` (SSH keys, tokens, .env files)
3. **New Role**: `welcome_packet_generator` (PDF, TXT, HTML)
4. **New Role**: `aws_prerequisites` (WAF, EFS deployment)

---

## Quick Reference Commands

### Deploy Workshop (Full Batch)
```bash
cd deployment/ansible

# Dry-run (validation only)
ansible-playbook playbooks/deploy-workshop.yml \
  --vault-password-file ~/.ansible-vault-password \
  -e "@config/workshops/workshop-2026-01.yml" \
  --check

# Production run
ansible-playbook playbooks/deploy-workshop.yml \
  --vault-password-file ~/.ansible-vault-password \
  -e "@config/workshops/workshop-2026-01.yml"
```

### Extract Credentials
```bash
# SSH keys
python3 scripts/workshop/extract-ssh-keys.py \
  --workshop-id workshop-2026-01 \
  --output-dir ~/.ssh/workshop-2026-01/

# JupyterLab tokens
python3 scripts/workshop/extract-jupyterlab-tokens.py \
  --workshop-id workshop-2026-01 \
  --output-file tokens.csv

# Generate .env files
python3 scripts/workshop/generate-env-files.py \
  --workshop-id workshop-2026-01 \
  --output-dir ./env-files/
```

### Generate Welcome Packets
```bash
python3 scripts/workshop/generate-welcome-packets.py \
  --workshop-id workshop-2026-01 \
  --output-dir output/workshop-2026-01/
```

### Cleanup After Workshop
```bash
# Backup data (optional)
ansible-playbook playbooks/backup-workshop-data.yml \
  --vault-password-file ~/.ansible-vault-password \
  -e "@config/workshops/workshop-2026-01.yml"

# Destroy all stacks
ansible-playbook playbooks/destroy-workshop.yml \
  --vault-password-file ~/.ansible-vault-password \
  -e "@config/workshops/workshop-2026-01.yml" \
  -e "confirm_destroy=yes"
```

---

## Next Steps

### Immediate Actions (Before Workshop)
1. **Review comprehensive plan**: `docs/deployment/BATCH_WORKSHOP_DEPLOYMENT_PLAN.md`
2. **Validate AWS quotas**: EC2 vCPUs (need 80+), ALBs (need 10)
3. **Deploy shared WAF WebACL**: Manual deployment (see plan section 6.1)
4. **Test single-participant deployment**: End-to-end validation
5. **Request AWS quota increases**: Submit 5-7 days before workshop

### Development Tasks (Phases 1-5)
- Implement batch deployment playbook
- Create credential extraction utilities
- Build welcome packet generator
- Set up CloudWatch monitoring
- Write troubleshooting runbook

### Key Files to Review
- **Current Infrastructure**:
  - `devtools/aws-cdk/app.py` (Multi-user CDK architecture)
  - `devtools/aws-cdk/stacks/dev_environment_stack.py` (EC2 provisioning)
  - `devtools/aws-cdk/stacks/application_stack.py` (ALB + Cognito + WAF)
  - `deployment/ansible/playbooks/deploy-infrastructure.yml` (Existing single-user playbook)
  - `deployment/ansible/config/adept-config.example.yml` (Config template)

- **Documentation**:
  - `devtools/AWS_VM_DEPLOYMENT_GUIDE.md` (Single-user deployment guide)
  - `docs/deployment/aws-multi-instance-deployment-readiness-assessment.md` (Infrastructure analysis)
  - `docs/deployment/BATCH_WORKSHOP_DEPLOYMENT_PLAN.md` (Full implementation plan - NEW)

---

## Summary

**Current Readiness**: 60% (Strong foundation, orchestration layer needed)

**Key Strengths**:
- Multi-user CDK architecture fully implemented
- Ansible automation framework in place
- Cognito user management utilities complete
- Instance management scripts ready

**Critical Gaps**:
- Batch deployment orchestration (multi-user loop)
- Credential extraction automation
- Welcome packet generation
- Workshop configuration schema

**Estimated Implementation**: 4-5 weeks (17-27 developer-days)

**Recommended Approach**:
1. Implement Phase 1 (Foundation Scripts) first for basic batch deployment
2. Test with 2-3 participants before full workshop
3. Add credential extraction and welcome packets in Phase 2-3
4. Harden for production in Phase 4
5. Document and test thoroughly in Phase 5

For detailed specifications, see: `docs/deployment/BATCH_WORKSHOP_DEPLOYMENT_PLAN.md`
