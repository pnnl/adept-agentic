# Bootstrap Development Environment - Quick Start

## 🚀 10-Minute Bootstrap Guide

This guide bootstraps your ADEPT development environment on an EC2 instance.

## Prerequisites

- EC2 instance running (see [EC2 Quickstart](../../aws-cdk/QUICKSTART.md))
- SSH key for the instance
- Git personal access token (GitHub or GitLab)

## Step 1: Prepare Connection Info

```bash
# From EC2 deployment
export INSTANCE_IP="54.123.45.67"        # Your instance IP
export SSH_KEY="~/.ssh/adept-dev.pem"    # Your SSH key path

# Get your Git token
# GitHub: Settings → Developer settings → Personal access tokens
# GitLab: User Settings → Access Tokens
export GIT_TOKEN="ghp_xxxxxxxxxxxx"      # Your token
```

## Step 2: Install Bootstrap Tool

```bash
# Navigate to bootstrap directory
cd devtools/shared/bootstrap

# Install dependencies (Python version)
pip install click fabric paramiko rich pyyaml

# OR use the bash version (no dependencies)
chmod +x bootstrap.sh
```

## Step 3: Run Bootstrap

### Option A: GitHub Repository (PNNL)
```bash
python bootstrap.py init \
  --host ${INSTANCE_IP} \
  --key ${SSH_KEY} \
  --repo https://github.com/pnnl/adept-agentic.git \
  --token ${GIT_TOKEN}
```

### Option B: GitLab Repository (EMSL)
```bash
python bootstrap.py init \
  --host ${INSTANCE_IP} \
  --key ${SSH_KEY} \
  --repo https://code.emsl.pnnl.gov/team/adept.git \
  --token ${GIT_TOKEN} \
  --use-conda \
  --conda-env adept
```

### Option C: Bash Script
```bash
./bootstrap.sh init \
  -h ${INSTANCE_IP} \
  -k ${SSH_KEY} \
  -r https://github.com/pnnl/adept-agentic.git \
  -t ${GIT_TOKEN}
```

## Step 4: Validate Setup

```bash
# Quick validation
python bootstrap.py validate \
  --host ${INSTANCE_IP} \
  --key ${SSH_KEY}

# Expected output:
# ✅ SSH Connection: Success
# ✅ Docker: Running
# ✅ Python: 3.11 installed
# ✅ UV: Installed
# ✅ Conda: Installed
# ✅ Repository: Cloned
# ✅ Environment: Configured
```

## Step 5: Start ADEPT Services

```bash
# Execute on remote instance
python bootstrap.py remote \
  --host ${INSTANCE_IP} \
  --key ${SSH_KEY} \
  "cd /data/workspace/adept-extended && make start"

# Or SSH in and run manually
ssh -i ${SSH_KEY} ubuntu@${INSTANCE_IP}
cd /data/workspace/adept-extended
make start
```

## What Gets Configured

### Repository Setup
- Clones to `/data/workspace/adept-extended`
- Configures Git authentication
- Sets up proper permissions

### Python Environment
- **UV (default)**: Fast, modern package management
- **Conda (optional)**: Scientific computing packages
- Installs all ADEPT dependencies

### Environment Configuration
- Creates `.env` from template
- Configures service credentials
- Sets up Docker permissions

## Team-Specific Bootstrap

### PNNL EMSL Team
```bash
python bootstrap.py init \
  --host ${INSTANCE_IP} \
  --key ${SSH_KEY} \
  --config ../configs/teams/pnnl-emsl.yaml \
  --team pnnl-emsl
```

### Custom Team
1. Copy `configs/teams/example-team.yaml`
2. Modify for your team
3. Use with `--config` flag

## Advanced Options

### Custom Branch
```bash
python bootstrap.py init \
  --host ${INSTANCE_IP} \
  --key ${SSH_KEY} \
  --repo ${REPO_URL} \
  --token ${GIT_TOKEN} \
  --branch feature/my-branch
```

### Custom Clone Folder
```bash
python bootstrap.py init \
  --host ${INSTANCE_IP} \
  --key ${SSH_KEY} \
  --repo ${REPO_URL} \
  --token ${GIT_TOKEN} \
  --folder my-workspace
```

### Conda Environment
```bash
python bootstrap.py init \
  --host ${INSTANCE_IP} \
  --key ${SSH_KEY} \
  --repo ${REPO_URL} \
  --token ${GIT_TOKEN} \
  --use-conda \
  --conda-env adept-dev \
  --python 3.11
```

## Troubleshooting

### SSH Connection Failed
```bash
# Test SSH
ssh -v -i ${SSH_KEY} ubuntu@${INSTANCE_IP}

# Check key permissions
chmod 400 ${SSH_KEY}
```

### Git Clone Failed
```bash
# Test token
curl -H "Authorization: token ${GIT_TOKEN}" https://api.github.com/user

# Try manual clone
git clone https://${GIT_TOKEN}@github.com/org/repo.git
```

### Environment Issues
```bash
# Check Python
python bootstrap.py remote \
  --host ${INSTANCE_IP} \
  --key ${SSH_KEY} \
  "python --version && uv --version"
```

## Post-Bootstrap Tasks

1. **Configure IDE for remote development**
2. **Set up additional tools**
3. **Configure Git identity**
4. **Install team-specific packages**

## Quick Reference

### Bootstrap Commands
```bash
init      # Initialize environment
validate  # Check setup
remote    # Execute commands
```

### Common Remote Commands
```bash
# Check services
"docker ps"

# View logs
"cd /data/workspace/adept-extended && docker logs orchestration_service"

# Restart services
"cd /data/workspace/adept-extended && make restart"
```

## Next Steps

- [Configure ADEPT services](../../../docs/CONFIGURATION.md)
- [Run validation tests](../../../docs/TESTING.md)
- [Set up development workflow](../../../docs/DEVELOPMENT.md)

---

**Time to Complete**: ~10 minutes
**Support**: #adept-support on Slack