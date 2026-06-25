# ADEPT DevTools Container — Multi-Cloud IaC + Ansible + Validation
#
# Purpose: Single container for all ADEPT infrastructure operations:
#   - SkyPilot: Cloud VM provisioning, lifecycle management
#   - AWS: CDK (Python), CLI v2, boto3
#   - Azure: Pulumi (Python), Azure CLI
#   - GCP: OpenTofu, Terraform, gcloud CLI
#   - Ansible: OS-level VM preparation and configuration
#   - boto3: AWS SDK for Python (used by CDK and custom scripts)
#
# State isolation: Container HOME is /app/state. The host mounts
# devtools/skypilot/contexts/<DEPLOY_CONTEXT>/.sky/ → /app/state/.sky/
# so all SkyPilot state stays project-local and per-context (never
# touches host $HOME). See Makefile SKYPILOT_RUN_BASE for mount details.
#
# Build:  docker build -t adept-skypilot:latest devtools/skypilot/
# Usage:
#   docker run --rm adept-skypilot:latest --version        # SkyPilot
#   docker run --rm --entrypoint aws adept-skypilot:latest --version  # AWS CLI
#   docker run --rm --entrypoint cdk adept-skypilot:latest --version  # CDK
#   docker run --rm --entrypoint pulumi adept-skypilot:latest version  # Pulumi
#   docker run --rm --entrypoint tofu adept-skypilot:latest --version  # OpenTofu
#   docker run --rm --entrypoint terraform adept-skypilot:latest --version  # Terraform
#   docker run --rm --entrypoint az adept-skypilot:latest --version  # Azure CLI
#   docker run --rm --entrypoint ansible adept-skypilot:latest --version  # Ansible

FROM python:3.11-slim

WORKDIR /app

# Redirect SkyPilot state to /app/state/.sky/ (mounted from host)
ENV HOME=/app/state
RUN mkdir -p /app/state/.sky

# ─── System dependencies ─────────────────────────────────────────────────────
# SSH: SkyPilot + Ansible remote execution
# Node.js 20.x: AWS CDK CLI requirement (cdk synth/deploy)
# rsync/curl/unzip/jq/git: SkyPilot cloud operations + general tooling
# sshpass: Ansible password-based SSH (fallback for non-key auth)
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client sshpass rsync curl unzip jq git bash \
    ca-certificates gnupg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
       | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" \
       > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# ─── AWS CLI v2 (binary install — not pip) ────────────────────────────────────
RUN curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip \
    && unzip -q /tmp/awscliv2.zip -d /tmp \
    && /tmp/aws/install \
    && rm -rf /tmp/awscliv2.zip /tmp/aws

# ─── AWS CDK CLI (global npm install) ────────────────────────────────────────
RUN npm install -g aws-cdk && npm cache clean --force

# ─── OpenTofu (GCP/Azure IaC — open-source Terraform fork) ──────────────────
ARG OPENTOFU_VERSION=1.9.1
RUN curl -fsSL "https://github.com/opentofu/opentofu/releases/download/v${OPENTOFU_VERSION}/tofu_${OPENTOFU_VERSION}_linux_amd64.zip" -o /tmp/tofu.zip \
    && unzip -q /tmp/tofu.zip -d /usr/local/bin/ \
    && chmod +x /usr/local/bin/tofu \
    && rm -f /tmp/tofu.zip

# ─── Terraform (legacy — some modules still require it) ──────────────────────
ARG TERRAFORM_VERSION=1.10.5
RUN curl -fsSL "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" -o /tmp/terraform.zip \
    && unzip -q /tmp/terraform.zip -d /usr/local/bin/ \
    && chmod +x /usr/local/bin/terraform \
    && rm -f /tmp/terraform.zip

# ─── Pulumi CLI (Azure IaC — Python runtime) ────────────────────────────────
RUN curl -fsSL https://get.pulumi.com | sh \
    && mv /app/state/.pulumi/bin/pulumi /usr/local/bin/ \
    && mv /app/state/.pulumi/bin/pulumi-* /usr/local/bin/ 2>/dev/null || true \
    && rm -rf /app/state/.pulumi

# ─── Azure CLI ───────────────────────────────────────────────────────────────
RUN pip install --no-cache-dir azure-cli

# ─── Google Cloud CLI (gcloud) ───────────────────────────────────────────────
RUN curl -fsSL https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-linux-x86_64.tar.gz \
    | tar -xz -C /opt \
    && /opt/google-cloud-sdk/install.sh --quiet --path-update=true \
    && ln -sf /opt/google-cloud-sdk/bin/gcloud /usr/local/bin/gcloud \
    && ln -sf /opt/google-cloud-sdk/bin/gsutil /usr/local/bin/gsutil

# ─── Python packages ─────────────────────────────────────────────────────────
# SkyPilot: Cloud VM provisioning + lifecycle
# AWS: aws-cdk-lib, constructs, boto3
# Azure: pulumi, pulumi-azure-native
# GCP: google-cloud-compute (for Terraform/OpenTofu provider auth)
# Ansible: OS-level VM configuration + collections
# Validation: yamllint, jsonschema for task YAML checks
ARG SKYPILOT_VERSION=0.12.0
RUN pip install --no-cache-dir \
    "skypilot[aws]==${SKYPILOT_VERSION}" \
    "aws-cdk-lib>=2.100.0" \
    "constructs>=10.0.0" \
    "boto3>=1.26.0" \
    "pulumi>=3.100.0" \
    "pulumi-aws>=6.0.0" \
    "pulumi-azure-native>=2.0.0" \
    "pulumi-gcp>=7.0.0" \
    "python-dotenv>=1.0.0" \
    "ansible-core>=2.16.0,<2.18.0" \
    yamllint pyyaml jsonschema

# ─── ADEPT CLI runtime dependencies ─────────────────────────────────────────
# SDK source is volume-mounted at runtime (always fresh, never stale).
# Only install the runtime deps here so imports resolve.
RUN pip install --no-cache-dir \
    "httpx>=0.24.0" \
    "pydantic>=2.0.0" \
    "typing-extensions>=4.0.0" \
    "click>=8.0.0" \
    "rich>=13.0.0" \
    "requests>=2.31.0" \
    "PyJWT>=2.12.1,<3.0.0"

# ─── Ansible collections ─────────────────────────────────────────────────────
RUN ansible-galaxy collection install \
    "ansible.posix>=1.5.0,<2.0.0" \
    "community.general>=8.0.0,<9.0.0" \
    "amazon.aws>=7.0.0,<8.0.0"

# ─── Scripts ──────────────────────────────────────────────────────────────────
COPY scripts/ /app/scripts/
RUN chmod +x /app/scripts/*.sh 2>/dev/null || true

# ─── SkyPilot verbose logging ────────────────────────────────────────────────
# Enable debug-level logging for all SkyPilot operations.
# Without this, SkyPilot only emits minimal progress to stdout.
ENV SKYPILOT_DEBUG=1
ENV SKY_LOG_LEVEL=DEBUG

ENTRYPOINT ["sky"]
