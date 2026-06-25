# ====================================================================================
# Agentic Framework Infrastructure & Deployment Makefile
#
# This Makefile provides a centralized, unified interface for managing the setup,
# local development, and deployment of the framework to all target environments.
# ====================================================================================

# --- Configuration ---
# These variables can be overridden by environment variables.
SHELL := /bin/bash

# Docker & Helm
COMPOSE_FILES := -f docker-compose.base.yaml -f docker-compose.core.yaml
HELM_CHART_PATH := ./helm/agentic-framework

# Kubernetes
NAMESPACE ?= agentic-framework
HELM_RELEASE_NAME ?= my-agentic-release
APP_SECRET_NAME ?= my-app-env-secret

# On-Prem (EMSL)
EMSL_SCRIPT_PATH := ../scripts/deploy-to-emsl.sh

# Cloud
AWS_SCRIPT_PATH := ../scripts/deploy-to-aws.sh
AZURE_SCRIPT_PATH := ../scripts/deploy-to-azure.sh
GCP_SCRIPT_PATH := ../scripts/deploy-to-gcp.sh

# --- Colors for Output ---
GREEN = \033[0;32m
YELLOW = \033[1;33m
BLUE = \033[1;34m
NC = \033[0m

.PHONY: all help setup-dev-env local-docker-start local-docker-stop local-docker-rebuild local-docker-down local-docker-logs local-k8s-start local-k8s-stop local-k8s-logs emsl-deploy emsl-delete emsl-status aws-deploy aws-destroy aws-status azure-deploy azure-destroy azure-status gcp-deploy gcp-destroy gcp-status

all: help

# ====================================================================================
# HELP TARGET - Describes all available commands
# ====================================================================================
help:
	@echo -e "${BLUE}Agentic Framework Infrastructure Makefile${NC}"
	@echo "---------------------------------------------------"
	@echo "Usage: make [target]"
	@echo ""
	@echo "  ${YELLOW}Environment Setup:${NC}"
	@echo "    setup-dev-env         - Run bootstrap scripts to configure a new Ubuntu 22.04 dev machine."
	@echo ""
	@echo "  ${YELLOW}Local Development (Docker Compose):${NC}"
	@echo "    local-docker-start    - Start all services using Docker Compose."
	@echo "    local-docker-stop     - Stop all services."
	@echo "    local-docker-rebuild  - Rebuild all images and restart services."
	@echo "    local-docker-down     - Stop and remove all containers, networks, and volumes."
	@echo "    local-docker-logs     - Tail logs from all Docker Compose services."
	@echo ""
	@echo "  ${YELLOW}Local Development (Kubernetes - Recommended):${NC}"
	@echo "    local-k8s-start       - Deploy the entire stack to a local K8s cluster (Minikube, k3d, Docker Desktop)."
	@echo "    local-k8s-stop        - Delete the Helm release from the local K8s cluster."
	@echo "    local-k8s-logs        - Tail logs from all pods in the local K8s deployment."
	@echo ""
	@echo "  ${YELLOW}On-Premises Deployment (EMSL):${NC}"
	@echo "    emsl-deploy           - Deploy to the EMSL K8s cluster. Use 'make emsl-deploy push=true' to push images first."
	@echo "    emsl-delete           - Delete the deployment from the EMSL K8s cluster."
	@echo "    emsl-status           - Check the status of the EMSL deployment."
	@echo ""
	@echo "  ${YELLOW}Cloud Deployment:${NC}"
	@echo "    aws-deploy            - Provision and deploy to AWS EKS."
	@echo "    aws-destroy           - Tear down all AWS resources."
	@echo "    aws-status            - Check status of AWS deployment."
	@echo "    azure-deploy          - Provision and deploy to Azure AKS."
	@echo "    azure-destroy         - Tear down all Azure resources."
	@echo "    azure-status          - Check status of Azure deployment."
	@echo "    gcp-deploy            - Provision and deploy to GCP GKE."
	@echo "    gcp-destroy           - Tear down all GCP resources."
	@echo "    gcp-status            - Check status of GCP deployment."

# ====================================================================================
# ENVIRONMENT SETUP
# ====================================================================================
setup-dev-env:
	@echo -e "${GREEN}--> Setting up Ubuntu 22.04 Development Environment...${NC}"
	@./ubuntu-bootstrap/bootstrap.sh

# ====================================================================================
# LOCAL DEVELOPMENT (DOCKER COMPOSE)
# ====================================================================================
local-docker-start:
	@echo -e "${GREEN}--> Starting all services with Docker Compose...${NC}"
	@docker compose $(COMPOSE_FILES) --profile "*" up -d --wait

local-docker-stop:
	@echo -e "${YELLOW}--> Stopping all Docker Compose services...${NC}"
	@docker compose $(COMPOSE_FILES) --profile "*" stop

local-docker-rebuild:
	@echo -e "${YELLOW}--> Rebuilding all images and restarting services...${NC}"
	@docker compose $(COMPOSE_FILES) --profile "*" up -d --build --force-recreate --wait

local-docker-down:
	@echo -e "${RED}--> Tearing down all Docker Compose services, networks, and volumes...${NC}"
	@docker compose $(COMPOSE_FILES) --profile "*" down -v

local-docker-logs:
	@echo -e "${GREEN}--> Tailing logs from all Docker Compose services...${NC}"
	@docker compose $(COMPOSE_FILES) logs -f --tail=100

# ====================================================================================
# LOCAL DEVELOPMENT (KUBERNETES)
# ====================================================================================
local-k8s-start:
	@echo -e "${GREEN}--> Starting local Kubernetes deployment...${NC}"
	@../scripts/manage-local-k8s.sh start

local-k8s-stop:
	@echo -e "${YELLOW}--> Stopping local Kubernetes deployment...${NC}"
	@../scripts/manage-local-k8s.sh stop

local-k8s-logs:
	@echo -e "${GREEN}--> Tailing logs from all pods...${NC}"
	@../scripts/manage-local-k8s.sh logs

# ====================================================================================
# ON-PREMISES DEPLOYMENT (EMSL)
# ====================================================================================
emsl-deploy:
	@echo -e "${GREEN}--> Deploying to EMSL Kubernetes...${NC}"
ifeq ($(push),true)
	@$(EMSL_SCRIPT_PATH) deploy --push
else
	@$(EMSL_SCRIPT_PATH) deploy
endif

emsl-delete:
	@echo -e "${RED}--> Deleting from EMSL Kubernetes...${NC}"
	@$(EMSL_SCRIPT_PATH) delete

emsl-status:
	@echo -e "${BLUE}--> Checking EMSL deployment status...${NC}"
	@$(EMSL_SCRIPT_PATH) status

# ====================================================================================
# CLOUD DEPLOYMENTS
# ====================================================================================
aws-deploy:
	@echo -e "${GREEN}--> Deploying to AWS EKS...${NC}"
	@$(AWS_SCRIPT_PATH) deploy

aws-destroy:
	@echo -e "${RED}--> Destroying AWS EKS stack...${NC}"
	@$(AWS_SCRIPT_PATH) destroy

aws-status:
	@echo -e "${BLUE}--> Checking AWS EKS deployment status...${NC}"
	@$(AWS_SCRIPT_PATH) status

azure-deploy:
	@echo -e "${GREEN}--> Deploying to Azure AKS...${NC}"
	@$(AZURE_SCRIPT_PATH) deploy

azure-destroy:
	@echo -e "${RED}--> Destroying Azure AKS stack...${NC}"
	@$(AZURE_SCRIPT_PATH) destroy

azure-status:
	@echo -e "${BLUE}--> Checking Azure AKS deployment status...${NC}"
	@$(AZURE_SCRIPT_PATH) status

gcp-deploy:
	@echo -e "${GREEN}--> Deploying to GCP GKE...${NC}"
	@$(GCP_SCRIPT_PATH) deploy

gcp-destroy:
	@echo -e "${RED}--> Destroying GCP GKE stack...${NC}"
	@$(GCP_SCRIPT_PATH) destroy

gcp-status:
	@echo -e "${BLUE}--> Checking GCP GKE deployment status...${NC}"
	@$(GCP_SCRIPT_PATH) status
