# ADEPT Cloud Deployment DevTools

Containerized infrastructure-as-code toolkit for deploying ADEPT to cloud VMs.

## Overview

This directory provides a Docker-based build system for provisioning, configuring, and managing cloud EC2 instances running the ADEPT stack. All tools run inside the `adept-skypilot:latest` container for reproducibility.

## Quick Start

```bash
# Build the devtools container
docker build -t adept-skypilot:latest devtools/skypilot/

# Deploy an EC2 instance (CDK)
make cdk-deploy

# Configure the VM (Ansible)
make ansible-prepare-vm ANSIBLE_TARGET_HOST=<private-ip>

# Launch ADEPT on the VM
make ec2-ssh EC2_HOST=<private-ip>
# Then: ./scripts/quick-start-adept-and-subsystems.sh
```

## Container Contents

| Tool | Purpose |
|------|---------|
| SkyPilot 0.12.0 | Cloud VM provisioning and lifecycle |
| AWS CLI v2 | IAM bootstrap, EC2 operations |
| AWS CDK (Python) | Infrastructure-as-code deployment |
| Ansible | OS-level VM preparation |
| yamllint, jsonschema | Task YAML validation |

## Directory Structure

```
devtools/skypilot/
├── Dockerfile          # Multi-tool container definition
├── Makefile            # All sky-*, cdk-*, ansible-* targets
├── scripts/            # Helper scripts (IAM, SSM, validation)
├── tasks/              # SkyPilot task YAML definitions
└── contexts/           # Per-deployment state (gitignored)
```

## Documentation

See [ONBOARDING.md](ONBOARDING.md) for the full deployment guide, including:
- End-to-end deployment walkthrough
- CDK vs SkyPilot decision framework
- State isolation (multi-context) architecture
- Makefile target reference
- Troubleshooting guide
