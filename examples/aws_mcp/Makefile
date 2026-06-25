# =============================================================================
# Makefile — AWS MCP Server Manager for ADEPT
# =============================================================================
# Full lifecycle management for the AWS meta-MCP server + nginx proxy.
#
# Quick start:  make setup
# Manual flow:  make build && make start && make register-tools
# =============================================================================

# --- Configuration ---
CONTAINER_ENGINE ?= docker
COMPOSE_CMD = $(CONTAINER_ENGINE) compose -f docker-compose.yaml
PROJECT_ROOT := $(shell cd ../.. && pwd)

# Colors
GREEN  = \033[0;32m
YELLOW = \033[1;33m
RED    = \033[0;31m
NC     = \033[0m

# --- Detect agentic CLI ---
AGENTIC_CLI := $(shell \
    if [ -x "$(PROJECT_ROOT)/.venv311/bin/agentic" ]; then \
        echo "$(PROJECT_ROOT)/.venv311/bin/agentic"; \
    elif [ -x "$(PROJECT_ROOT)/.venv/bin/agentic" ]; then \
        echo "$(PROJECT_ROOT)/.venv/bin/agentic"; \
    elif command -v agentic >/dev/null 2>&1; then \
        echo "agentic"; \
    else \
        echo ""; \
    fi \
)

# Test image (built from base stage — no pre-installed AWS servers)
TEST_IMAGE = aws-mcp-manager:test
TEST_RUN = $(CONTAINER_ENGINE) run --rm --user $$(id -u):$$(id -g) --entrypoint python

.PHONY: all setup build start stop restart teardown status logs health \
        wait-healthy rebuild-mcp start-mcp stop-mcp restart-mcp logs-mcp \
        health-mcp health-proxy health-tls \
        generate-certs \
        register-tools deregister-tools verify-tools \
        generate-catalog \
        build-test-image ensure-test-image test-unit test-integration test-e2e test-tls test-all \
        validate-mcp validate-tls validate-all \
        check-prerequisites init-network init-env preflight help

# =============================================================================
# Convenience Targets
# =============================================================================

all: help

## Full end-to-end setup: preflight, build, start, register tools
setup: preflight build start wait-healthy register-tools verify-tools
	@echo -e "$(GREEN)=== AWS MCP Manager stack fully operational ===$(NC)"

# =============================================================================
# Prerequisites
# =============================================================================

check-prerequisites:
	@echo -e "$(YELLOW)Checking prerequisites...$(NC)"
	@command -v $(CONTAINER_ENGINE) >/dev/null 2>&1 || { echo -e "$(RED)ERROR: $(CONTAINER_ENGINE) not found$(NC)"; exit 1; }
	@$(CONTAINER_ENGINE) compose version >/dev/null 2>&1 || { echo -e "$(RED)ERROR: $(CONTAINER_ENGINE) compose not found$(NC)"; exit 1; }
	@echo "  $(CONTAINER_ENGINE) compose: OK"
	@if [ -n "$(AGENTIC_CLI)" ]; then echo "  agentic CLI: $(AGENTIC_CLI)"; else echo -e "  $(YELLOW)agentic CLI: not found (tool registration will fail)$(NC)"; fi

init-network:
	@$(CONTAINER_ENGINE) network inspect adept_application_network >/dev/null 2>&1 || \
		$(CONTAINER_ENGINE) network create adept_application_network

## Initialize .env from .env.example if it doesn't exist
init-env:
	@if [ ! -f .env ]; then \
		echo -e "$(YELLOW)Creating .env from .env.example...$(NC)"; \
		cp .env.example .env; \
		echo -e "$(GREEN).env created — edit with your AWS credentials$(NC)"; \
	fi

## Full pre-flight: prerequisites, env, network
preflight: check-prerequisites init-env init-network
	@echo -e "$(GREEN)Pre-flight complete$(NC)"

# =============================================================================
# Build Targets
# =============================================================================

## Build all images
build: init-network
	@echo -e "$(YELLOW)Building AWS MCP Manager images...$(NC)"
	$(COMPOSE_CMD) build
	@echo -e "$(GREEN)Build complete$(NC)"

## Build with no cache
build-no-cache: init-network
	$(COMPOSE_CMD) build --no-cache

# =============================================================================
# Lifecycle Targets
# =============================================================================

## Start all services
start:
	@echo -e "$(YELLOW)Starting AWS MCP Manager...$(NC)"
	$(COMPOSE_CMD) up -d
	@echo -e "$(GREEN)Services started$(NC)"

## Stop all services
stop:
	$(COMPOSE_CMD) down

## Restart all services
restart: stop start

## Full teardown (remove containers, networks, volumes)
teardown:
	$(COMPOSE_CMD) down -v --remove-orphans

## Show service status
status:
	$(COMPOSE_CMD) ps

## Show logs (follow)
logs:
	$(COMPOSE_CMD) logs -f

## Check health of all services
health: health-mcp health-proxy

## Wait for services to be healthy (up to 60s)
wait-healthy:
	@echo -e "$(YELLOW)Waiting for services to become healthy...$(NC)"
	@for i in $$(seq 1 30); do \
		if $(CONTAINER_ENGINE) exec aws_mcp_manager python -c \
			"import socket; s=socket.create_connection(('localhost',8003),2); s.close()" 2>/dev/null; then \
			echo -e "$(GREEN)AWS MCP Manager is healthy$(NC)"; \
			exit 0; \
		fi; \
		sleep 2; \
	done; \
	echo -e "$(RED)Timeout waiting for AWS MCP Manager$(NC)"; exit 1

# =============================================================================
# Per-Service Targets
# =============================================================================

## Rebuild MCP server only (stop + build + start)
rebuild-mcp: stop-mcp
	$(COMPOSE_CMD) build aws_mcp_manager
	$(COMPOSE_CMD) up -d aws_mcp_manager
	@echo -e "$(GREEN)MCP server rebuilt$(NC)"

start-mcp:
	$(COMPOSE_CMD) up -d aws_mcp_manager

stop-mcp:
	$(COMPOSE_CMD) stop aws_mcp_manager

restart-mcp: stop-mcp start-mcp

logs-mcp:
	$(COMPOSE_CMD) logs -f aws_mcp_manager

## Health check: MCP server
health-mcp:
	@echo -n "MCP server: "
	@$(CONTAINER_ENGINE) exec aws_mcp_manager python -c \
		"import socket; s=socket.create_connection(('localhost',8003),2); s.close()" 2>/dev/null \
		&& echo -e "$(GREEN)healthy$(NC)" || echo -e "$(RED)unhealthy$(NC)"

## Health check: nginx proxy (HTTP)
health-proxy:
	@echo -n "Nginx proxy (HTTP):  "
	@curl -sf http://localhost:9830/health >/dev/null 2>&1 \
		&& echo -e "$(GREEN)healthy$(NC)" || echo -e "$(RED)unhealthy$(NC)"

## Health check: nginx proxy (HTTPS — requires certs)
health-tls:
	@echo -n "Nginx proxy (HTTPS): "
	@if [ -f certs/ca.crt ]; then \
		curl -sf --cacert certs/ca.crt https://localhost:9831/health >/dev/null 2>&1 \
			&& echo -e "$(GREEN)healthy$(NC)" || echo -e "$(RED)unhealthy$(NC)"; \
	else \
		echo -e "$(YELLOW)skipped (no certs/ca.crt)$(NC)"; \
	fi

# =============================================================================
# TLS / Certificate Generation
# =============================================================================

## Generate CA + server TLS certificates for nginx proxy
generate-certs:
	@echo -e "$(YELLOW)Generating CA + server certificates...$(NC)"
	@bash scripts/generate-ca-and-certs.sh
	@echo -e "$(GREEN)Certs generated in certs/$(NC)"
	@echo -e "$(GREEN)For cross-host: copy certs/ca.crt to ADEPT host$(NC)"

# =============================================================================
# Tool Registration
# =============================================================================

## Register 6 meta-tools with ADEPT gateway
register-tools:
	@echo -e "$(YELLOW)Registering AWS MCP Manager tools with ADEPT...$(NC)"
	@./scripts/register-aws-tools.sh register

## Deregister tools from ADEPT gateway
deregister-tools:
	@./scripts/register-aws-tools.sh deregister

## Verify tools are registered in Redis
verify-tools:
	@./scripts/register-aws-tools.sh verify

# =============================================================================
# Catalog Generation
# =============================================================================

## Generate catalog.json from temp/mcp/src/
generate-catalog:
	@echo -e "$(YELLOW)Generating catalog from temp/mcp/src/...$(NC)"
	@python3 scripts/generate-catalog.py
	@echo -e "$(GREEN)Catalog generated$(NC)"

# =============================================================================
# Testing
# =============================================================================

## Build lightweight test image (base stage, no pre-installed AWS servers)
build-test-image:
	@echo -e "$(YELLOW)Building test image (base stage)...$(NC)"
	$(CONTAINER_ENGINE) build --target base -t $(TEST_IMAGE) -f aws_mcp_manager/Dockerfile aws_mcp_manager/
	@echo -e "$(GREEN)Test image built$(NC)"

ensure-test-image:
	@$(CONTAINER_ENGINE) image inspect $(TEST_IMAGE) >/dev/null 2>&1 || \
		$(MAKE) build-test-image

## Run unit tests (mocked AWS)
test-unit: ensure-test-image
	$(TEST_RUN) \
		-v "$$(pwd)/aws_mcp_manager":/app/aws_mcp_manager:ro \
		-v "$$(pwd)/tests":/app/tests:ro \
		-w /app \
		-e PYTHONPATH=/app \
		$(TEST_IMAGE) \
		-m pytest tests/unit/ -v --tb=short

## Run integration tests
test-integration: ensure-test-image
	$(TEST_RUN) \
		--network=adept_application_network \
		-v "$$(pwd)/aws_mcp_manager":/app/aws_mcp_manager:ro \
		-v "$$(pwd)/tests":/app/tests:ro \
		-w /app \
		-e PYTHONPATH=/app \
		$(TEST_IMAGE) \
		-m pytest tests/integration/ -v --tb=short

## Run end-to-end tests
test-e2e: ensure-test-image
	$(TEST_RUN) \
		--network=adept_application_network \
		-v "$$(pwd)/aws_mcp_manager":/app/aws_mcp_manager:ro \
		-v "$$(pwd)/tests":/app/tests:ro \
		-w /app \
		-e PYTHONPATH=/app \
		-e AWS_MCP_AWS_ACCESS_KEY_ID=$${AWS_MCP_AWS_ACCESS_KEY_ID:-} \
		-e AWS_MCP_AWS_SECRET_ACCESS_KEY=$${AWS_MCP_AWS_SECRET_ACCESS_KEY:-} \
		-e AWS_MCP_AWS_REGION=$${AWS_MCP_AWS_REGION:-us-east-1} \
		-e AWS_MCP_STS_ROLE_ARN=$${AWS_MCP_STS_ROLE_ARN:-} \
		$(TEST_IMAGE) \
		-m pytest tests/e2e/ -v --tb=short

## Run TLS certificate and HTTPS flow tests
test-tls: ensure-test-image
	$(TEST_RUN) \
		--network=adept_application_network \
		-v "$$(pwd)/aws_mcp_manager":/app/aws_mcp_manager:ro \
		-v "$$(pwd)/tests":/app/tests:ro \
		-v "$$(pwd)/certs":/app/certs:ro \
		-w /app \
		-e PYTHONPATH=/app \
		$(TEST_IMAGE) \
		-m pytest tests/unit/test_certs.py tests/integration/test_tls.py -v --tb=short

## Run all tests
test-all: test-unit test-integration test-e2e test-tls

# =============================================================================
# Validation
# =============================================================================

## Validate MCP server and proxy health
validate-mcp: health-mcp health-proxy

## Validate TLS endpoint (requires certs + running proxy)
validate-tls: health-tls

## Run all validations
validate-all: validate-mcp validate-tls verify-tools

# =============================================================================
# Help
# =============================================================================

## Show this help
help:
	@echo ""
	@echo "AWS MCP Server Manager — Makefile Targets"
	@echo "=========================================="
	@echo ""
	@echo "Convenience:"
	@echo "  setup              Full end-to-end setup"
	@echo "  help               Show this help"
	@echo ""
	@echo "Build:"
	@echo "  build              Build all images"
	@echo "  build-no-cache     Build with no cache"
	@echo ""
	@echo "Lifecycle:"
	@echo "  start / stop / restart / teardown"
	@echo "  status / logs / health / wait-healthy"
	@echo ""
	@echo "Per-Service:"
	@echo "  rebuild-mcp        Rebuild MCP server only"
	@echo "  health-mcp         Health check MCP server"
	@echo "  health-proxy       Health check nginx proxy (HTTP)"
	@echo "  health-tls         Health check nginx proxy (HTTPS)"
	@echo "  logs-mcp           Follow MCP server logs"
	@echo ""
	@echo "TLS / Certificates:"
	@echo "  generate-certs     Generate CA + server TLS certs"
	@echo "                     Requires: AWS_MCP_HOST_IP=<ip>"
	@echo ""
	@echo "Registration:"
	@echo "  register-tools     Register 6 meta-tools with ADEPT"
	@echo "  deregister-tools   Remove tools from ADEPT"
	@echo "  verify-tools       Check Redis for tools"
	@echo ""
	@echo "Catalog:"
	@echo "  generate-catalog   Generate catalog.json from temp/mcp/src/"
	@echo ""
	@echo "Testing:"
	@echo "  test-unit          Unit tests (mocked AWS)"
	@echo "  test-integration   Integration tests"
	@echo "  test-e2e           End-to-end tests"
	@echo "  test-tls           TLS cert + HTTPS flow tests"
	@echo "  test-all           All tests"
	@echo ""
	@echo "Validation:"
	@echo "  validate-mcp       Health checks (HTTP)"
	@echo "  validate-tls       Health checks (HTTPS)"
	@echo "  validate-all       All validations"
	@echo ""
