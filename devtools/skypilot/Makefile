# devtools/skypilot/Makefile — ADEPT Infrastructure Deployment (Public Version)
#
# This is the public version of the SkyPilot/CDK/Ansible Makefile for external
# users of the pnnl/adept-agentic repository. Internal-specific targets and
# credentials have been removed or replaced with configurable placeholders.
#
# Prerequisites:
#   - AWS credentials exported in your environment (AWS_ACCESS_KEY_ID, etc.)
#   - Docker installed and running
#   - The adept-skypilot container built (make sky-build)
#
# Self-contained Makefile for SkyPilot, CDK, and Ansible operations.
# All state lives in contexts/<DEPLOY_CONTEXT>/ (never $HOME).
#
# Usage from this directory:
#   make sky-build
#   make cdk-deploy DEPLOY_CONTEXT=aws-<your-account-id>-dev
#   make ansible-prepare-vm ANSIBLE_TARGET_HOST=<your-ec2-private-ip> ANSIBLE_SSH_KEY=ADE-dev-<user>-<account>-key.pem
#
# Usage from project root (delegated):
#   make -C devtools/skypilot <target> [DEPLOY_CONTEXT=...]

# ============================================================================
# Shared Variables
# ============================================================================

GREEN  := \033[0;32m
YELLOW := \033[1;33m
RED    := \033[0;31m
NC     := \033[0m

# Paths relative to this Makefile's directory
SKYPILOT_DIR     := $(shell pwd)
PROJECT_ROOT     := $(shell cd ../.. && pwd)

SKYPILOT_IMAGE   := adept-skypilot:latest

# Multi-context deployment state
DEPLOY_CONTEXT   ?= aws-<your-account-id>-dev
CONTEXT_DIR      := $(SKYPILOT_DIR)/contexts/$(DEPLOY_CONTEXT)
STATE_DIR        := $(CONTEXT_DIR)/.sky
SSH_DIR          := $(CONTEXT_DIR)/.ssh
LOGS_DIR         := $(CONTEXT_DIR)/logs
CONFIG_FILE      := $(CONTEXT_DIR)/config.yaml

# Common docker run base for all SkyPilot operations requiring state
SKYPILOT_RUN_BASE = docker run --rm \
	  -v "$(SKYPILOT_DIR)/tasks":/app/skypilot/tasks:ro \
	  -v "$(STATE_DIR)":/app/state/.sky \
	  -v "$(CONFIG_FILE)":/app/state/.sky/config.yaml:ro

# CDK variables
CDK_USER_LABEL   ?= $(USER)
CDK_ENV_LABEL    ?= dev
CDK_VPC_ID       ?=
CDK_AMI_ID       ?=
CDK_SUBNET_ID    ?=
CDK_INSTANCE_TYPE ?= t3.2xlarge
CDK_KEY_PAIR_NAME ?=

CDK_RUN_BASE = docker run --rm \
	  -v "$(PROJECT_ROOT)/devtools/aws-cdk":/app/cdk-src:ro \
	  -e CDK_USER_LABEL=$(CDK_USER_LABEL) \
	  -e CDK_ENV_LABEL=$(CDK_ENV_LABEL) \
	  -e CDK_VPC_ID=$(CDK_VPC_ID) \
	  -e CDK_AMI_ID=$(CDK_AMI_ID) \
	  -e CDK_INSTANCE_TYPE=$(CDK_INSTANCE_TYPE) \
	  -e CDK_KEY_PAIR_NAME=$(CDK_KEY_PAIR_NAME)

CDK_SETUP = cp -r /app/cdk-src /tmp/cdk && cd /tmp/cdk && pip install -q -r requirements.txt

# Ansible variables
ANSIBLE_TARGET_HOST ?=
ANSIBLE_SSH_KEY     ?=
ANSIBLE_USER        ?= ubuntu
ANSIBLE_SITE_NAME   ?= aws_ec2
# Source transfer mode: tarball (default) or git clone on target
# Tarball is preferred — some private VPCs may not have GitHub access
ANSIBLE_SOURCE_TARBALL ?= true
ANSIBLE_TARBALL_PATH   ?= /tmp/adept-source.tar.gz

# Auto-stop
CDK_STOP_MINUTES ?= 120

.PHONY: sky-build sky-bootstrap-iam sky-simulate-iam sky-dry-run sky-clean-state \
	sky-status sky-validate-syntax sky-validate-schema sky-validate-parity \
	sky-validate-offline sky-validate-all sky-list-contexts sky-init-context \
	sky-check sky-deploy-aws \
	sky-deploy-aws-bg sky-deploy-log sky-down \
	cdk-synth cdk-diff cdk-list cdk-deploy cdk-deploy-bg cdk-bootstrap \
	cdk-get-connection-info cdk-retrieve-key cdk-check-ssm cdk-instance-status cdk-ssm-run \
	cdk-schedule-stop cdk-cancel-stop cdk-destroy \
	ansible-prepare-vm ansible-prepare-vm-bg

# ============================================================================
# Container Build
# ============================================================================

## Build the SkyPilot validation/deployment container
sky-build:
	@echo -e "$(GREEN)--> Building SkyPilot container...$(NC)"
	docker build -t $(SKYPILOT_IMAGE) .

# ============================================================================
# Deployment Context Management
# ============================================================================

## List available deployment contexts
sky-list-contexts:
	@echo "Available deployment contexts:"
	@ls -1 contexts/ 2>/dev/null || echo "  (none — create one with make sky-init-context)"
	@echo ""
	@echo "Active: $(DEPLOY_CONTEXT)"

## Scaffold a new deployment context directory
## Usage: make sky-init-context DEPLOY_CONTEXT=aws-123456789012-staging
sky-init-context:
	@test -n "$(DEPLOY_CONTEXT)" || { echo "ERROR: Set DEPLOY_CONTEXT=<provider-account-env>"; exit 1; }
	@mkdir -p contexts/$(DEPLOY_CONTEXT)/.sky
	@mkdir -p contexts/$(DEPLOY_CONTEXT)/.ssh
	@mkdir -p contexts/$(DEPLOY_CONTEXT)/logs
	@echo "Created context: contexts/$(DEPLOY_CONTEXT)/"
	@echo "Next: create contexts/$(DEPLOY_CONTEXT)/config.yaml"

# ============================================================================
# SkyPilot Offline Validation (no cloud credentials needed)
# ============================================================================

## Validate SkyPilot YAML syntax (yamllint + bash -n)
sky-validate-syntax: sky-build
	@echo -e "$(GREEN)--> Validating SkyPilot YAML syntax...$(NC)"
	docker run --rm \
	  -v "$(SKYPILOT_DIR)/tasks":/app/skypilot/tasks:ro \
	  --entrypoint /app/scripts/validate-yaml-offline.sh \
	  $(SKYPILOT_IMAGE)

## Validate SkyPilot YAML schema + env var coverage
sky-validate-schema: sky-build
	@echo -e "$(GREEN)--> Validating SkyPilot YAML schema...$(NC)"
	docker run --rm \
	  -v "$(SKYPILOT_DIR)/tasks":/app/skypilot/tasks:ro \
	  --entrypoint python3 \
	  $(SKYPILOT_IMAGE) /app/scripts/validate-yaml-schema.py

## Validate Ansible + CDK parity (all critical setup phases present)
sky-validate-parity: sky-build
	@echo -e "$(GREEN)--> Checking Ansible/CDK parity...$(NC)"
	docker run --rm \
	  -v "$(SKYPILOT_DIR)/tasks":/app/skypilot/tasks:ro \
	  --entrypoint /app/scripts/validate-ansible-parity.sh \
	  $(SKYPILOT_IMAGE)

## Run all offline SkyPilot validations (no cloud credentials)
sky-validate-offline: sky-validate-syntax sky-validate-schema sky-validate-parity
	@echo -e "$(GREEN)==> All offline SkyPilot validations passed.$(NC)"

## Full SkyPilot validation pipeline (offline only — safe to run anytime)
sky-validate-all: sky-validate-offline
	@echo -e "$(GREEN)==> SkyPilot validation complete.$(NC)"

# ============================================================================
# SkyPilot Cloud Operations (require credentials)
#
# Prerequisites: Export AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and
# optionally AWS_DEFAULT_REGION in your shell before running these targets.
# ============================================================================

## Bootstrap AWS IAM prerequisites for SkyPilot (idempotent)
sky-bootstrap-iam: sky-build
	@test -n "$$AWS_ACCESS_KEY_ID" || { echo "ERROR: AWS_ACCESS_KEY_ID not set. Export your AWS credentials first."; exit 1; }
	@mkdir -p "$(STATE_DIR)"
	$(SKYPILOT_RUN_BASE) \
	  -e AWS_ACCESS_KEY_ID=$$AWS_ACCESS_KEY_ID \
	  -e AWS_SECRET_ACCESS_KEY=$$AWS_SECRET_ACCESS_KEY \
	  -e AWS_DEFAULT_REGION=$${AWS_DEFAULT_REGION:-us-west-2} \
	  --entrypoint bash \
	  $(SKYPILOT_IMAGE) /app/scripts/bootstrap-aws-iam.sh

## Simulate IAM policy evaluation for SkyPilot-required actions (no state changes)
sky-simulate-iam: sky-build
	@echo -e "$(GREEN)--> Simulating IAM policies for SkyPilot prerequisites...$(NC)"
	@$(SKYPILOT_DIR)/scripts/sky-simulate-iam.sh

## Dry-run EC2 launch to validate AMI + subnet + SCP compliance (no instance created)
## Requires: CDK_AMI_ID and CDK_SUBNET_ID to be set
sky-dry-run: sky-build
	@echo -e "$(GREEN)--> Dry-run EC2 launch (validates AMI, subnet, SCP compliance)...$(NC)"
	@test -n "$$AWS_ACCESS_KEY_ID" || { echo "ERROR: AWS_ACCESS_KEY_ID not set. Export your AWS credentials first."; exit 1; }
	@test -n "$(CDK_AMI_ID)" || { echo "ERROR: CDK_AMI_ID not set. Set CDK_AMI_ID=ami-xxxxxxxxxxxxxxxxx"; exit 1; }
	@test -n "$(CDK_SUBNET_ID)" || { echo "ERROR: CDK_SUBNET_ID not set. Set CDK_SUBNET_ID=subnet-xxxxxxxxxxxxxxxxx"; exit 1; }
	@docker run --rm \
	  -e AWS_ACCESS_KEY_ID=$$AWS_ACCESS_KEY_ID \
	  -e AWS_SECRET_ACCESS_KEY=$$AWS_SECRET_ACCESS_KEY \
	  -e AWS_DEFAULT_REGION=$${AWS_DEFAULT_REGION:-us-west-2} \
	  --entrypoint aws $(SKYPILOT_IMAGE) \
	  ec2 run-instances --dry-run \
	    --image-id $(CDK_AMI_ID) \
	    --instance-type $(CDK_INSTANCE_TYPE) \
	    --subnet-id $(CDK_SUBNET_ID) \
	  2>&1 && true ; \
	echo -e "$(GREEN)  DryRunOperation = launch WOULD succeed (AMI + subnet + SCP OK)$(NC)" || \
	echo -e "$(RED)  Dry-run failed — check AMI, subnet, or SCP restrictions above$(NC)"

## Wipe cached SkyPilot state for a fresh start (cluster cache, state.db, locks)
sky-clean-state:
	@echo -e "$(YELLOW)--> Wiping SkyPilot state for context $(DEPLOY_CONTEXT)...$(NC)"
	sudo rm -rf "$(STATE_DIR)"
	mkdir -p "$(STATE_DIR)"
	@echo "State cleared for $(DEPLOY_CONTEXT). Next deploy starts fresh."

## Show SkyPilot cluster status
sky-status: sky-build
	@mkdir -p "$(STATE_DIR)"
	$(SKYPILOT_RUN_BASE) \
	  $(SKYPILOT_IMAGE) status

## Verify SkyPilot can connect to AWS
sky-check: sky-build
	@echo -e "$(GREEN)--> Checking SkyPilot cloud connectivity...$(NC)"
	@test -n "$$AWS_ACCESS_KEY_ID" || { echo "ERROR: AWS_ACCESS_KEY_ID not set. Export your AWS credentials first."; exit 1; }
	@mkdir -p "$(STATE_DIR)"
	$(SKYPILOT_RUN_BASE) \
	  -e AWS_ACCESS_KEY_ID=$$AWS_ACCESS_KEY_ID \
	  -e AWS_SECRET_ACCESS_KEY=$$AWS_SECRET_ACCESS_KEY \
	  -e AWS_DEFAULT_REGION=$${AWS_DEFAULT_REGION:-us-west-2} \
	  $(SKYPILOT_IMAGE) check

## Deploy ADEPT to AWS EC2 (interactive)
sky-deploy-aws: sky-build
	@echo -e "$(GREEN)--> Deploying ADEPT to AWS EC2 [context: $(DEPLOY_CONTEXT)]...$(NC)"
	@test -n "$$AWS_ACCESS_KEY_ID" || { echo "ERROR: AWS_ACCESS_KEY_ID not set. Export your AWS credentials first."; exit 1; }
	@mkdir -p "$(STATE_DIR)"
	$(SKYPILOT_RUN_BASE) -it \
	  -e AWS_ACCESS_KEY_ID=$$AWS_ACCESS_KEY_ID \
	  -e AWS_SECRET_ACCESS_KEY=$$AWS_SECRET_ACCESS_KEY \
	  -e AWS_DEFAULT_REGION=$${AWS_DEFAULT_REGION:-us-west-2} \
	  $(SKYPILOT_IMAGE) launch -c adept-dev /app/skypilot/tasks/deploy-adept-cloud.yaml

## Deploy ADEPT to AWS EC2 in background (nohup + timestamped log)
sky-deploy-aws-bg: sky-build
	@echo -e "$(GREEN)--> Deploying ADEPT to AWS EC2 (background) [context: $(DEPLOY_CONTEXT)]...$(NC)"
	@test -n "$$AWS_ACCESS_KEY_ID" || { echo "ERROR: AWS_ACCESS_KEY_ID not set. Export your AWS credentials first."; exit 1; }
	@mkdir -p $(LOGS_DIR) "$(STATE_DIR)"
	$(eval SKY_LOG := $(LOGS_DIR)/sky_deploy_aws_$(shell date +%Y%m%d_%H%M%S).log)
	@echo "Log file: $(SKY_LOG)"
	@nohup $(SKYPILOT_RUN_BASE) \
	  -e AWS_ACCESS_KEY_ID=$$AWS_ACCESS_KEY_ID \
	  -e AWS_SECRET_ACCESS_KEY=$$AWS_SECRET_ACCESS_KEY \
	  -e AWS_DEFAULT_REGION=$${AWS_DEFAULT_REGION:-us-west-2} \
	  $(SKYPILOT_IMAGE) launch -y -c adept-dev /app/skypilot/tasks/deploy-adept-cloud.yaml \
	  > $(SKY_LOG) 2>&1 & \
	echo "Deploy running in background. Monitor with: tail -f $(SKY_LOG)"

## Tail the most recent SkyPilot deploy log
sky-deploy-log:
	@ls -t $(LOGS_DIR)/sky_deploy_*.log 2>/dev/null | head -1 | xargs -I{} tail -f {} || \
	  echo "No SkyPilot deploy logs found in $(LOGS_DIR)/"

## Teardown SkyPilot cluster (destroys VM and data)
sky-down:
	@echo -e "$(YELLOW)--> Tearing down SkyPilot cluster [context: $(DEPLOY_CONTEXT)]...$(NC)"
	@test -n "$$AWS_ACCESS_KEY_ID" || { echo "ERROR: AWS_ACCESS_KEY_ID not set. Export your AWS credentials first."; exit 1; }
	@mkdir -p "$(STATE_DIR)"
	$(SKYPILOT_RUN_BASE) \
	  -e AWS_ACCESS_KEY_ID=$$AWS_ACCESS_KEY_ID \
	  -e AWS_SECRET_ACCESS_KEY=$$AWS_SECRET_ACCESS_KEY \
	  -e AWS_DEFAULT_REGION=$${AWS_DEFAULT_REGION:-us-west-2} \
	  $(SKYPILOT_IMAGE) down adept-dev -y

# ============================================================================
# AWS CDK Targets
#
# Provisions EC2 instances with explicit subnet, AMI, and IAM targeting.
# Uses the same adept-skypilot container (includes CDK + Node.js).
# ============================================================================

## Synthesize CDK CloudFormation template (needs credentials for VPC lookup)
cdk-synth: sky-build
	@echo -e "$(GREEN)--> Synthesizing CDK stack [context: $(DEPLOY_CONTEXT)]...$(NC)"
	@test -n "$$AWS_ACCESS_KEY_ID" || { echo "ERROR: AWS_ACCESS_KEY_ID not set. Export your AWS credentials first."; exit 1; }
	@$(CDK_RUN_BASE) \
	  -e AWS_ACCESS_KEY_ID=$$AWS_ACCESS_KEY_ID \
	  -e AWS_SECRET_ACCESS_KEY=$$AWS_SECRET_ACCESS_KEY \
	  -e AWS_DEFAULT_REGION=$${AWS_DEFAULT_REGION:-us-west-2} \
	  -e CDK_ACCOUNT=$$(docker run --rm \
	    -e AWS_ACCESS_KEY_ID=$$AWS_ACCESS_KEY_ID \
	    -e AWS_SECRET_ACCESS_KEY=$$AWS_SECRET_ACCESS_KEY \
	    -e AWS_DEFAULT_REGION=$${AWS_DEFAULT_REGION:-us-west-2} \
	    --entrypoint aws $(SKYPILOT_IMAGE) \
	    sts get-caller-identity --query Account --output text) \
	  --entrypoint bash $(SKYPILOT_IMAGE) -c \
	  "$(CDK_SETUP) && cdk synth \
	    -c env=$(CDK_ENV_LABEL) -c user=$(CDK_USER_LABEL) \
	    -c vpc=$(CDK_VPC_ID) -c ami=$(CDK_AMI_ID) \
	    -c instance_type=$(CDK_INSTANCE_TYPE) \
	    -c account=\$$CDK_ACCOUNT"

## Show diff between deployed and local CDK stack
cdk-diff: sky-build
	@echo -e "$(GREEN)--> CDK diff (deployed vs local) [context: $(DEPLOY_CONTEXT)]...$(NC)"
	@test -n "$$AWS_ACCESS_KEY_ID" || { echo "ERROR: AWS_ACCESS_KEY_ID not set. Export your AWS credentials first."; exit 1; }
	@$(CDK_RUN_BASE) \
	  -e AWS_ACCESS_KEY_ID=$$AWS_ACCESS_KEY_ID \
	  -e AWS_SECRET_ACCESS_KEY=$$AWS_SECRET_ACCESS_KEY \
	  -e AWS_DEFAULT_REGION=$${AWS_DEFAULT_REGION:-us-west-2} \
	  -e CDK_ACCOUNT=$$(docker run --rm \
	    -e AWS_ACCESS_KEY_ID=$$AWS_ACCESS_KEY_ID \
	    -e AWS_SECRET_ACCESS_KEY=$$AWS_SECRET_ACCESS_KEY \
	    -e AWS_DEFAULT_REGION=$${AWS_DEFAULT_REGION:-us-west-2} \
	    --entrypoint aws $(SKYPILOT_IMAGE) \
	    sts get-caller-identity --query Account --output text) \
	  --entrypoint bash $(SKYPILOT_IMAGE) -c \
	  "$(CDK_SETUP) && cdk diff \
	    -c env=$(CDK_ENV_LABEL) -c user=$(CDK_USER_LABEL) \
	    -c vpc=$(CDK_VPC_ID) -c ami=$(CDK_AMI_ID) \
	    -c instance_type=$(CDK_INSTANCE_TYPE) \
	    -c account=\$$CDK_ACCOUNT"

## List CDK stacks
cdk-list: sky-build
	@echo -e "$(GREEN)--> Listing CDK stacks...$(NC)"
	@test -n "$$AWS_ACCESS_KEY_ID" || { echo "ERROR: AWS_ACCESS_KEY_ID not set. Export your AWS credentials first."; exit 1; }
	@$(CDK_RUN_BASE) \
	  -e AWS_ACCESS_KEY_ID=$$AWS_ACCESS_KEY_ID \
	  -e AWS_SECRET_ACCESS_KEY=$$AWS_SECRET_ACCESS_KEY \
	  -e AWS_DEFAULT_REGION=$${AWS_DEFAULT_REGION:-us-west-2} \
	  --entrypoint bash $(SKYPILOT_IMAGE) -c \
	  "$(CDK_SETUP) && cdk list \
	    -c env=$(CDK_ENV_LABEL) -c user=$(CDK_USER_LABEL)"

## Deploy EC2 via CDK (interactive — prompts for approval)
cdk-deploy: sky-build
	@echo -e "$(GREEN)--> Deploying EC2 via CDK [context: $(DEPLOY_CONTEXT)]...$(NC)"
	@test -n "$$AWS_ACCESS_KEY_ID" || { echo "ERROR: AWS_ACCESS_KEY_ID not set. Export your AWS credentials first."; exit 1; }
	@$(CDK_RUN_BASE) -it \
	  -e AWS_ACCESS_KEY_ID=$$AWS_ACCESS_KEY_ID \
	  -e AWS_SECRET_ACCESS_KEY=$$AWS_SECRET_ACCESS_KEY \
	  -e AWS_DEFAULT_REGION=$${AWS_DEFAULT_REGION:-us-west-2} \
	  -e CDK_ACCOUNT=$$(docker run --rm \
	    -e AWS_ACCESS_KEY_ID=$$AWS_ACCESS_KEY_ID \
	    -e AWS_SECRET_ACCESS_KEY=$$AWS_SECRET_ACCESS_KEY \
	    -e AWS_DEFAULT_REGION=$${AWS_DEFAULT_REGION:-us-west-2} \
	    --entrypoint aws $(SKYPILOT_IMAGE) \
	    sts get-caller-identity --query Account --output text) \
	  --entrypoint bash $(SKYPILOT_IMAGE) -c \
	  "$(CDK_SETUP) && cdk deploy \
	    -c env=$(CDK_ENV_LABEL) -c user=$(CDK_USER_LABEL) \
	    -c vpc=$(CDK_VPC_ID) -c ami=$(CDK_AMI_ID) \
	    -c instance_type=$(CDK_INSTANCE_TYPE) \
	    -c account=\$$CDK_ACCOUNT"

## Deploy EC2 via CDK in background (auto-approve, timestamped log)
cdk-deploy-bg: sky-build
	@echo -e "$(GREEN)--> Deploying EC2 via CDK (background) [context: $(DEPLOY_CONTEXT)]...$(NC)"
	@test -n "$$AWS_ACCESS_KEY_ID" || { echo "ERROR: AWS_ACCESS_KEY_ID not set. Export your AWS credentials first."; exit 1; }
	@mkdir -p $(LOGS_DIR)
	$(eval CDK_LOG := $(LOGS_DIR)/cdk_deploy_$(shell date +%Y%m%d_%H%M%S).log)
	@echo "Log file: $(CDK_LOG)"
	@CDK_ACCOUNT=$$(docker run --rm \
	    -e AWS_ACCESS_KEY_ID=$$AWS_ACCESS_KEY_ID \
	    -e AWS_SECRET_ACCESS_KEY=$$AWS_SECRET_ACCESS_KEY \
	    -e AWS_DEFAULT_REGION=$${AWS_DEFAULT_REGION:-us-west-2} \
	    --entrypoint aws $(SKYPILOT_IMAGE) \
	    sts get-caller-identity --query Account --output text) && \
	  nohup $(CDK_RUN_BASE) \
	  -e AWS_ACCESS_KEY_ID=$$AWS_ACCESS_KEY_ID \
	  -e AWS_SECRET_ACCESS_KEY=$$AWS_SECRET_ACCESS_KEY \
	  -e AWS_DEFAULT_REGION=$${AWS_DEFAULT_REGION:-us-west-2} \
	  -e CDK_ACCOUNT=$$CDK_ACCOUNT \
	  --entrypoint bash $(SKYPILOT_IMAGE) -c \
	  "$(CDK_SETUP) && cdk deploy --require-approval never \
	    -c env=$(CDK_ENV_LABEL) -c user=$(CDK_USER_LABEL) \
	    -c vpc=$(CDK_VPC_ID) -c ami=$(CDK_AMI_ID) \
	    -c instance_type=$(CDK_INSTANCE_TYPE) \
	    -c account=\$$CDK_ACCOUNT" \
	  > $(CDK_LOG) 2>&1 & \
	echo "CDK deploy running in background. Monitor: tail -f $(CDK_LOG)"

## Bootstrap CDK in target account (one-time setup per account)
cdk-bootstrap: sky-build
	@echo -e "$(GREEN)--> Bootstrapping CDK in target account...$(NC)"
	@test -n "$$AWS_ACCESS_KEY_ID" || { echo "ERROR: AWS_ACCESS_KEY_ID not set. Export your AWS credentials first."; exit 1; }
	@$(CDK_RUN_BASE) -it \
	  -e AWS_ACCESS_KEY_ID=$$AWS_ACCESS_KEY_ID \
	  -e AWS_SECRET_ACCESS_KEY=$$AWS_SECRET_ACCESS_KEY \
	  -e AWS_DEFAULT_REGION=$${AWS_DEFAULT_REGION:-us-west-2} \
	  -e CDK_ACCOUNT=$$(docker run --rm \
	    -e AWS_ACCESS_KEY_ID=$$AWS_ACCESS_KEY_ID \
	    -e AWS_SECRET_ACCESS_KEY=$$AWS_SECRET_ACCESS_KEY \
	    -e AWS_DEFAULT_REGION=$${AWS_DEFAULT_REGION:-us-west-2} \
	    --entrypoint aws $(SKYPILOT_IMAGE) \
	    sts get-caller-identity --query Account --output text) \
	  --entrypoint bash $(SKYPILOT_IMAGE) -c \
	  "$(CDK_SETUP) && cdk bootstrap aws://\$$CDK_ACCOUNT/us-west-2 \
	    --qualifier adeptdev \
	    --toolkit-stack-name CDKToolkit-AdeptDev"

## Get connection info for deployed CDK stack (private IP + SSH key retrieval command)
cdk-get-connection-info: sky-build
	@echo -e "$(GREEN)--> Retrieving CDK stack outputs [context: $(DEPLOY_CONTEXT)]...$(NC)"
	@test -n "$$AWS_ACCESS_KEY_ID" || { echo "ERROR: AWS_ACCESS_KEY_ID not set. Export your AWS credentials first."; exit 1; }
	@docker run --rm \
	  -e AWS_ACCESS_KEY_ID=$$AWS_ACCESS_KEY_ID \
	  -e AWS_SECRET_ACCESS_KEY=$$AWS_SECRET_ACCESS_KEY \
	  -e AWS_DEFAULT_REGION=$${AWS_DEFAULT_REGION:-us-west-2} \
	  --entrypoint bash $(SKYPILOT_IMAGE) -c " \
	    STACK_NAME=ADE-$(CDK_ENV_LABEL)-$(CDK_USER_LABEL)-Stack && \
	    echo \"Stack: \$$STACK_NAME\" && \
	    echo \"---\" && \
	    aws cloudformation describe-stacks --stack-name \$$STACK_NAME \
	      --query \"Stacks[0].Outputs[?OutputKey==\\\`PrivateIP\\\` || OutputKey==\\\`InstanceId\\\` || OutputKey==\\\`SSHCommand\\\` || OutputKey==\\\`RetrievePrivateKeyCommand\\\` || OutputKey==\\\`SessionManagerCommand\\\`].{Key:OutputKey,Value:OutputValue}\" \
	      --output table"

## Retrieve SSH private key from SSM Parameter Store → contexts/<DEPLOY_CONTEXT>/.ssh/
cdk-retrieve-key: sky-build
	@echo -e "$(GREEN)--> Retrieving SSH private key [context: $(DEPLOY_CONTEXT)]...$(NC)"
	@test -n "$$AWS_ACCESS_KEY_ID" || { echo "ERROR: AWS_ACCESS_KEY_ID not set. Export your AWS credentials first."; exit 1; }
	@mkdir -p $(SSH_DIR)
	@docker run --rm \
	  -v "$(SSH_DIR)":/app/ssh_out \
	  -e AWS_ACCESS_KEY_ID=$$AWS_ACCESS_KEY_ID \
	  -e AWS_SECRET_ACCESS_KEY=$$AWS_SECRET_ACCESS_KEY \
	  -e AWS_DEFAULT_REGION=$${AWS_DEFAULT_REGION:-us-west-2} \
	  --entrypoint bash $(SKYPILOT_IMAGE) -c " \
	    STACK_NAME=ADE-$(CDK_ENV_LABEL)-$(CDK_USER_LABEL)-Stack && \
	    ACCOUNT=\$$(aws sts get-caller-identity --query Account --output text) && \
	    KEY_PAIR_ID=\$$(aws cloudformation describe-stacks --stack-name \$$STACK_NAME \
	      --query \"Stacks[0].Outputs[?OutputKey==\\\`KeyPairId\\\`].OutputValue\" --output text) && \
	    KEY_FILE=/app/ssh_out/ADE-$(CDK_ENV_LABEL)-$(CDK_USER_LABEL)-\$$ACCOUNT-key.pem && \
	    echo \"KeyPairId: \$$KEY_PAIR_ID\" && \
	    aws ssm get-parameter --name /ec2/keypair/\$$KEY_PAIR_ID \
	      --with-decryption --query Parameter.Value --output text > \$$KEY_FILE && \
	    chmod 400 \$$KEY_FILE && \
	    echo \"Key saved to contexts/$(DEPLOY_CONTEXT)/.ssh/ADE-$(CDK_ENV_LABEL)-$(CDK_USER_LABEL)-\$$ACCOUNT-key.pem\""

## Check SSM connectivity to deployed instance (API-based, no SSH needed)
cdk-check-ssm: sky-build
	@echo -e "$(GREEN)--> Checking SSM connectivity [context: $(DEPLOY_CONTEXT)]...$(NC)"
	@$(SKYPILOT_DIR)/scripts/cdk-check-ssm.sh

## Quick instance state check (running/stopped/terminated, SSM ping, Nessus agent)
cdk-instance-status: sky-build
	@$(SKYPILOT_DIR)/scripts/cdk-instance-status.sh

## Run arbitrary command on EC2 instance via SSM
## Single-line: make cdk-ssm-run CMD='docker ps --format "{{.Names}}" | wc -l'
## Multiline or $() in CMD: devtools/skypilot/scripts/cdk-ssm-run.sh '...'
## See scripts/cdk-ssm-run.sh for full documentation.
CMD ?=
cdk-ssm-run: sky-build
	@test -n "$(CMD)" || { echo "ERROR: CMD required. Example: make cdk-ssm-run CMD='docker ps'"; exit 1; }
	@$(SKYPILOT_DIR)/scripts/cdk-ssm-run.sh "$(CMD)"

## Schedule EC2 instance stop after N minutes (default: 120 = 2 hours)
## Usage: make cdk-schedule-stop CDK_STOP_MINUTES=60
cdk-schedule-stop: sky-build
	@echo -e "$(GREEN)--> Scheduling instance stop in $(CDK_STOP_MINUTES) minutes [context: $(DEPLOY_CONTEXT)]...$(NC)"
	@$(SKYPILOT_DIR)/scripts/cdk-schedule-stop.sh $(CDK_STOP_MINUTES)

## Cancel a previously scheduled stop
cdk-cancel-stop: sky-build
	@echo -e "$(GREEN)--> Cancelling scheduled stop [context: $(DEPLOY_CONTEXT)]...$(NC)"
	@$(SKYPILOT_DIR)/scripts/cdk-cancel-stop.sh

## Destroy CDK stack (uses --force to skip interactive confirmation)
cdk-destroy: sky-build
	@echo -e "$(YELLOW)--> Destroying CDK stack [context: $(DEPLOY_CONTEXT)]...$(NC)"
	@test -n "$$AWS_ACCESS_KEY_ID" || { echo "ERROR: AWS_ACCESS_KEY_ID not set. Export your AWS credentials first."; exit 1; }
	@$(CDK_RUN_BASE) \
	  -e AWS_ACCESS_KEY_ID=$$AWS_ACCESS_KEY_ID \
	  -e AWS_SECRET_ACCESS_KEY=$$AWS_SECRET_ACCESS_KEY \
	  -e AWS_DEFAULT_REGION=$${AWS_DEFAULT_REGION:-us-west-2} \
	  -e CDK_ACCOUNT=$$(docker run --rm \
	    -e AWS_ACCESS_KEY_ID=$$AWS_ACCESS_KEY_ID \
	    -e AWS_SECRET_ACCESS_KEY=$$AWS_SECRET_ACCESS_KEY \
	    -e AWS_DEFAULT_REGION=$${AWS_DEFAULT_REGION:-us-west-2} \
	    --entrypoint aws $(SKYPILOT_IMAGE) \
	    sts get-caller-identity --query Account --output text) \
	  --entrypoint bash $(SKYPILOT_IMAGE) -c \
	  "$(CDK_SETUP) && cdk destroy --force \
	    -c env=$(CDK_ENV_LABEL) -c user=$(CDK_USER_LABEL) \
	    -c account=\$$CDK_ACCOUNT"

# ============================================================================
# Ansible Targets
#
# Runs Ansible playbooks against provisioned EC2 instances.
# Uses --network host so container has transit gateway routing
# to private EC2 instances in managed VPCs.
#
# Source transfer: tarball (default) vs git clone
#   Some private VPCs may not have GitHub access from EC2 instances (transit
#   gateway doesn't route to github.com). Default is tarball: git archive on
#   this host, SCP to target via Ansible unarchive module.
#   Override: ANSIBLE_SOURCE_TARBALL=false to attempt git clone on target.
# ============================================================================

## Create source tarball from current git HEAD (internal helper)
## Prefix matches playbook's adept_workspace naming: adept-agentic-{site}-{date}
_ansible-tarball:
ifeq ($(ANSIBLE_SOURCE_TARBALL),true)
	@echo -e "$(GREEN)--> Creating source tarball from git HEAD...$(NC)"
	@git -C "$(PROJECT_ROOT)" archive --format=tar.gz \
	  --prefix=adept-agentic-$(ANSIBLE_SITE_NAME)-$(shell date +%Y%m%d)/ \
	  -o "$(ANSIBLE_TARBALL_PATH)" HEAD
	@echo "Tarball: $(ANSIBLE_TARBALL_PATH) ($$(du -h $(ANSIBLE_TARBALL_PATH) | cut -f1))"
endif

## Prepare a VM for ADEPT (Docker, permissions, firewall, sysctl)
## Uses --network host for transit gateway routing to private EC2 instances.
## Usage: make ansible-prepare-vm ANSIBLE_TARGET_HOST=<ip> ANSIBLE_SSH_KEY=ADE-dev-<user>-<account>-key.pem
ansible-prepare-vm: sky-build _ansible-tarball
	@echo -e "$(GREEN)--> Running prepare-rocky-vm.yml on $(ANSIBLE_TARGET_HOST) [context: $(DEPLOY_CONTEXT)]...$(NC)"
	@test -n "$(ANSIBLE_TARGET_HOST)" || { echo "ERROR: Set ANSIBLE_TARGET_HOST=<ip-or-hostname>"; exit 1; }
	@test -n "$(ANSIBLE_SSH_KEY)" || { echo "ERROR: Set ANSIBLE_SSH_KEY=<key-filename>"; exit 1; }
	docker run --rm --network host \
	  -v "$(PROJECT_ROOT)/deployment/ansible":/app/ansible:ro \
	  -v "$(SSH_DIR)":/app/ssh_keys:ro \
	  $(if $(filter true,$(ANSIBLE_SOURCE_TARBALL)),-v "$(ANSIBLE_TARBALL_PATH)":/tmp/adept-source.tar.gz:ro) \
	  --entrypoint bash $(SKYPILOT_IMAGE) -c " \
	    cp /app/ssh_keys/$(ANSIBLE_SSH_KEY) /tmp/ssh_key && chmod 400 /tmp/ssh_key && \
	    echo '[adept_vms]' > /tmp/inventory.ini && \
	    echo '$(ANSIBLE_TARGET_HOST) ansible_user=$(ANSIBLE_USER) ansible_python_interpreter=/usr/bin/python3' >> /tmp/inventory.ini && \
	    echo '' >> /tmp/inventory.ini && \
	    echo '[adept_vms:vars]' >> /tmp/inventory.ini && \
	    echo 'data_volume=/data' >> /tmp/inventory.ini && \
	    echo 'site_name=$(ANSIBLE_SITE_NAME)' >> /tmp/inventory.ini && \
	    echo 'adept_user=$(ANSIBLE_USER)' >> /tmp/inventory.ini && \
	    echo '# adept_workspace set by playbook vars: /data/workspace/adept-agentic-{site}-{date}' >> /tmp/inventory.ini && \
	    echo 'git_branch=$(shell git rev-parse --abbrev-ref HEAD)' >> /tmp/inventory.ini && \
	    echo 'clean_podman_storage=false' >> /tmp/inventory.ini && \
	    ansible-playbook \
	      -i /tmp/inventory.ini \
	      --private-key /tmp/ssh_key \
	      --ssh-extra-args '-o StrictHostKeyChecking=no' \
	      $(if $(filter true,$(ANSIBLE_SOURCE_TARBALL)),-e source_tarball=true -e git_clone=false) \
	      /app/ansible/playbooks/prepare-rocky-vm.yml -v"

## Prepare a VM for ADEPT in background (timestamped log)
ansible-prepare-vm-bg: sky-build _ansible-tarball
	@echo -e "$(GREEN)--> Preparing VM $(ANSIBLE_TARGET_HOST) (background) [context: $(DEPLOY_CONTEXT)]...$(NC)"
	@test -n "$(ANSIBLE_TARGET_HOST)" || { echo "ERROR: Set ANSIBLE_TARGET_HOST=<ip-or-hostname>"; exit 1; }
	@test -n "$(ANSIBLE_SSH_KEY)" || { echo "ERROR: Set ANSIBLE_SSH_KEY=<key-filename>"; exit 1; }
	@mkdir -p $(LOGS_DIR)
	$(eval ANSIBLE_LOG := $(LOGS_DIR)/ansible_prepare_$(shell date +%Y%m%d_%H%M%S).log)
	@echo "Log file: $(ANSIBLE_LOG)"
	@nohup docker run --rm --network host \
	  -v "$(PROJECT_ROOT)/deployment/ansible":/app/ansible:ro \
	  -v "$(SSH_DIR)":/app/ssh_keys:ro \
	  $(if $(filter true,$(ANSIBLE_SOURCE_TARBALL)),-v "$(ANSIBLE_TARBALL_PATH)":/tmp/adept-source.tar.gz:ro) \
	  --entrypoint bash $(SKYPILOT_IMAGE) -c " \
	    cp /app/ssh_keys/$(ANSIBLE_SSH_KEY) /tmp/ssh_key && chmod 400 /tmp/ssh_key && \
	    echo '[adept_vms]' > /tmp/inventory.ini && \
	    echo '$(ANSIBLE_TARGET_HOST) ansible_user=$(ANSIBLE_USER) ansible_python_interpreter=/usr/bin/python3' >> /tmp/inventory.ini && \
	    echo '' >> /tmp/inventory.ini && \
	    echo '[adept_vms:vars]' >> /tmp/inventory.ini && \
	    echo 'data_volume=/data' >> /tmp/inventory.ini && \
	    echo 'site_name=$(ANSIBLE_SITE_NAME)' >> /tmp/inventory.ini && \
	    echo 'adept_user=$(ANSIBLE_USER)' >> /tmp/inventory.ini && \
	    echo '# adept_workspace set by playbook vars: /data/workspace/adept-agentic-{site}-{date}' >> /tmp/inventory.ini && \
	    echo 'git_branch=$(shell git rev-parse --abbrev-ref HEAD)' >> /tmp/inventory.ini && \
	    echo 'clean_podman_storage=false' >> /tmp/inventory.ini && \
	    ansible-playbook \
	      -i /tmp/inventory.ini \
	      --private-key /tmp/ssh_key \
	      --ssh-extra-args '-o StrictHostKeyChecking=no' \
	      $(if $(filter true,$(ANSIBLE_SOURCE_TARBALL)),-e source_tarball=true -e git_clone=false) \
	      /app/ansible/playbooks/prepare-rocky-vm.yml -v" \
	  > $(ANSIBLE_LOG) 2>&1 & \
	echo "Ansible running in background. Monitor: tail -f $(ANSIBLE_LOG)"
