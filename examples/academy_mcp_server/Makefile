# Makefile for Academy MCP Server — Build, Register, and Teardown
#
# Canonical pattern matching biofoundation_mcp_server and vfm_mcp_server.
# See docs/ACADEMY_MCP_SERVER_LIFECYCLE_ARCHITECTURE.md for full details.
#
# Lifecycle:
#   make setup            # Full: build, start, wait, register, verify
#   make rebuild          # Rebuild from scratch and re-register tools
#   make teardown         # Stop containers and deregister tools
#
# Individual targets:
#   make build            # Build Docker images
#   make start            # Start containers (3 services)
#   make stop             # Stop containers
#   make register-tools   # Register 4 tools with ADEPT (two-step: container discovery + host CLI)
#   make deregister-tools # Remove tools from ADEPT
#   make health           # Check all 3 services
#   make smoke-test       # E2E test via Response API
#   make logs             # Tail container logs

SHELL := /bin/bash

# ====================================================================================
# Configuration
# ====================================================================================

PROJECT_ROOT := $(shell cd ../.. && pwd)
ENGINE ?= docker
COMPOSE_FILE := docker-compose.yaml
COMPOSE_CPU := docker-compose.cpu.yaml

# Container names (canonical: {project}_{role})
CONTAINER_MCP   := academy_mcp_server
CONTAINER_PROXY := academy_nginx_proxy
CONTAINER_REDIS := academy_redis

# Ports
MCP_PORT        := 9004
PROXY_HTTP_PORT := 9050

# Tool registration
TOOL_PREFIX  := academy
TOOL_URL     := http://$(CONTAINER_MCP):$(MCP_PORT)/mcp
REGISTER_SCRIPT := scripts/register_academy_tools.py
REGISTER_HOST_SCRIPT := scripts/register_from_schemas.py

# agentic CLI — auto-detect (canonical pattern from biofoundation/VFM)
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

# Admin credentials for tool registration (ROPC flow)
ADMIN_USER ?= admin
ADMIN_PASS ?= admin

# CRITICAL: KEYCLOAK_URL must use Docker service name for JWT issuer match
# /etc/hosts must map "keycloak" to 127.0.0.1 so the CLI can resolve it
KEYCLOAK_URL ?= http://keycloak:8180

# Agent Gateway URL (host port)
GATEWAY_URL ?= http://localhost:8083

# Academy PKG dir (for volume mounts)
ACADEMY_PKG_DIR := $(shell pwd)

.PHONY: all setup rebuild rebuild-quick teardown \
	build build-no-cache start stop restart \
	check-prerequisites check-cli check-network init-data \
	health wait-healthy \
	register-tools deregister-tools verify-tools show-schemas \
	smoke-test \
	ensure-test-image validate-tests validate-unit validate-integration validate-registration-e2e \
	test-registration-adept test-registration-lifecycle \
	test-infrastructure-health validate-registration-lifecycle \
	test-e2e-lifecycle test-e2e-mcp-discovery test-e2e-auth-flows \
	test-e2e-full-lifecycle test-e2e-echo-agent \
	nohup-test-e2e-lifecycle \
	ensure-log-dir nohup-test-all nohup-test-unit nohup-test-integration \
	nohup-test-registration-adept nohup-test-registration-lifecycle \
	logs logs-mcp logs-proxy logs-short \
	help

# ====================================================================================
# Combined Lifecycle Targets
# ====================================================================================

all: setup

setup: check-prerequisites init-data build start wait-healthy register-tools verify-tools
	@echo "DONE: Academy MCP Server setup complete"
	@echo "  Containers: $(CONTAINER_MCP), $(CONTAINER_PROXY), $(CONTAINER_REDIS)"
	@echo "  MCP:        $(TOOL_URL)"
	@echo "  Proxy:      http://localhost:$(PROXY_HTTP_PORT)/mcp"
	@echo "  Health:     http://localhost:$(MCP_PORT)/health"

rebuild: stop build-no-cache start wait-healthy deregister-tools register-tools verify-tools
	@echo "DONE: Academy MCP Server rebuilt and re-registered"

rebuild-quick: stop build start wait-healthy
	@echo "DONE: Academy MCP Server rebuilt (cached) and restarted"
	@echo "  Next: make deregister-tools && make register-tools && make verify-tools"

teardown: deregister-tools stop
	@echo "DONE: Academy MCP Server torn down"

# ====================================================================================
# Prerequisite Checks
# ====================================================================================

check-prerequisites: check-cli check-network

check-cli:
	@if [ -z "$(AGENTIC_CLI)" ]; then \
		echo "ERROR: agentic CLI not found"; \
		echo "  Install: cd $(PROJECT_ROOT) && pip install -e src/"; \
		exit 1; \
	fi
	@echo "  agentic CLI: $(AGENTIC_CLI)"

check-network:
	@$(ENGINE) network inspect adept_application_network >/dev/null 2>&1 || \
		(echo "ERROR: adept_application_network not found. Start ADEPT first: make start (from project root)" && exit 1)
	@echo "  Docker network: adept_application_network exists"

init-data:
	@mkdir -p $(PROJECT_ROOT)/data/academy/sessions
	@mkdir -p $(PROJECT_ROOT)/data/academy/cache
	@# Set ownership to appuser:appgroup (1200:1200) so the non-root container can write.
	@# Uses a lightweight Alpine container to chown — no sudo needed if user is in docker group.
	@# UID/GID 1200 is pinned in infra/dockerfiles/Dockerfile.os-base (APP_UID/APP_GID).
	@$(ENGINE) run --rm -v "$(PROJECT_ROOT)/data/academy":/data alpine \
		chown -R 1200:1200 /data 2>/dev/null && \
		echo "  Data directories: owned by appuser:appgroup (1200:1200)" || \
		(chmod -R a+rwX $(PROJECT_ROOT)/data/academy/ 2>/dev/null && \
		echo "  Data directories: world-writable (docker chown fallback)")
	@echo "  Data directories initialized"

# ====================================================================================
# Docker Build & Container Targets
# ====================================================================================

build:
	@echo "--> Building Academy MCP Server images..."
	$(ENGINE) compose -f $(COMPOSE_FILE) -f $(COMPOSE_CPU) build

build-no-cache:
	@echo "--> Building Academy MCP Server images (no cache)..."
	$(ENGINE) compose -f $(COMPOSE_FILE) -f $(COMPOSE_CPU) build --no-cache

start:
	@echo "--> Starting Academy MCP Server (3 services)..."
	$(ENGINE) compose -f $(COMPOSE_FILE) -f $(COMPOSE_CPU) up -d
	@echo "  3 containers started"

stop:
	@echo "--> Stopping Academy MCP Server..."
	$(ENGINE) compose -f $(COMPOSE_FILE) down 2>/dev/null || true
	@echo "  Containers stopped"

restart: stop start wait-healthy
	@echo "  Containers restarted"

# ====================================================================================
# Health & Readiness
# ====================================================================================

health:
	@echo "--> Checking health..."
	@echo "  MCP Server:"
	@curl -sf http://localhost:$(MCP_PORT)/health | python3 -m json.tool 2>/dev/null || echo "    UNAVAILABLE"
	@echo "  Nginx Proxy:"
	@curl -sf http://localhost:$(PROXY_HTTP_PORT)/health | python3 -m json.tool 2>/dev/null || echo "    UNAVAILABLE"
	@echo "  Redis:"
	@$(ENGINE) exec $(CONTAINER_REDIS) redis-cli ping 2>/dev/null || echo "    UNAVAILABLE"

wait-healthy:
	@echo "--> Waiting for MCP server to become healthy..."
	@for i in $$(seq 1 30); do \
		if curl -sf http://localhost:$(MCP_PORT)/health >/dev/null 2>&1; then \
			echo "  MCP server healthy (attempt $$i)"; \
			exit 0; \
		fi; \
		echo "  Waiting... ($$i/30)"; \
		sleep 2; \
	done; \
	echo "  FAILED: MCP server did not become healthy within 60s"; \
	$(ENGINE) logs $(CONTAINER_MCP) --tail 20; \
	exit 1

# ====================================================================================
# Tool Registration (4 tools) — Two-Step Pattern
#
# Step 1: Discover schemas INSIDE the container (academy-py only available there)
# Step 2: Register from HOST via agentic CLI (needs /etc/hosts keycloak mapping)
#
# Docker socket must be group-readable and group-owned by the docker group.
#
# NOTE: We use inline Python import (not argparse show-schemas) because the
# container image may have an older script version where show-schemas prints
# config preamble to stdout, corrupting JSON. Direct import is always clean.
# ====================================================================================

# Inline Python command to extract clean JSON schemas from the container
DISCOVER_SCHEMAS_CMD = python3 -c "import sys; sys.path.insert(0,'.'); \
	from scripts.register_academy_tools import discover_tools, show_schemas; \
	show_schemas(discover_tools())"

register-tools:
	@echo "--> Step 1: Discovering Academy tool schemas from container..."
	@$(ENGINE) exec -w /app/academy_mcp_server $(CONTAINER_MCP) \
		$(DISCOVER_SCHEMAS_CMD) > /tmp/academy_schemas.json
	@echo "  Discovered $$(python3 -c 'import json; print(len(json.load(open("/tmp/academy_schemas.json"))))') tools"
	@echo "--> Step 2: Registering with ADEPT gateway..."
	@KEYCLOAK_URL=$(KEYCLOAK_URL) AGENT_GATEWAY_URL=$(GATEWAY_URL) \
		ADMIN_USER=$(ADMIN_USER) ADMIN_PASS=$(ADMIN_PASS) \
		ACADEMY_MCP_HOST=$(CONTAINER_MCP) ACADEMY_MCP_PORT=$(MCP_PORT) \
		python3 $(REGISTER_HOST_SCRIPT) /tmp/academy_schemas.json

deregister-tools:
	@echo "--> Step 1: Discovering Academy tool schemas from container..."
	@$(ENGINE) exec -w /app/academy_mcp_server $(CONTAINER_MCP) \
		$(DISCOVER_SCHEMAS_CMD) > /tmp/academy_schemas.json
	@echo "--> Step 2: Deregistering from ADEPT gateway..."
	@KEYCLOAK_URL=$(KEYCLOAK_URL) AGENT_GATEWAY_URL=$(GATEWAY_URL) \
		ADMIN_USER=$(ADMIN_USER) ADMIN_PASS=$(ADMIN_PASS) \
		python3 $(REGISTER_HOST_SCRIPT) /tmp/academy_schemas.json deregister

verify-tools:
	@echo "--> Verifying Academy tool registration in Redis..."
	@$(ENGINE) exec -w /app/academy_mcp_server $(CONTAINER_MCP) \
		$(DISCOVER_SCHEMAS_CMD) > /tmp/academy_schemas.json
	@python3 $(REGISTER_HOST_SCRIPT) /tmp/academy_schemas.json verify

show-schemas:
	@$(ENGINE) exec -w /app/academy_mcp_server $(CONTAINER_MCP) \
		$(DISCOVER_SCHEMAS_CMD)

# ====================================================================================
# E2E Smoke Test
# ====================================================================================

smoke-test:
	@echo "--> Running E2E smoke test via Response API..."
	@ADMIN_TOKEN=$$(curl -sf -X POST "$(KEYCLOAK_URL)/realms/master/protocol/openid-connect/token" \
		-d "grant_type=password&client_id=login-client&username=$(ADMIN_USER)&password=$(ADMIN_PASS)" \
		| python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])") && \
	RESPONSE=$$(curl -sf -X POST "$(GATEWAY_URL)/v1/responses/completions" \
		-H "Authorization: Bearer $$ADMIN_TOKEN" \
		-H "Content-Type: application/json" \
		-d '{ \
			"model": "agentic-framework:scientific-agent-v1", \
			"messages": [{"role": "user", "content": "Use the launch_academy_agent tool to launch an echo agent with agent_type=echo and empty agent_config={}, then use invoke_agent_action to call the echo action with message=academy smoke test 20260328 on the returned agent_id, and report the result."}], \
			"stream": false, \
			"max_tokens": 2000 \
		}') && \
	echo "$$RESPONSE" | python3 -m json.tool && \
	echo "  Smoke test passed (HTTP 200)" || \
	(echo "  FAILED: Smoke test failed" && exit 1)

# ====================================================================================
# Test Suite (container-based — canonical DRY pattern)
# ====================================================================================

# Base image with academy-py + fastmcp pre-installed
VALIDATION_IMAGE ?= academy_mcp_server-academy_mcp_server
LOG_DIR    := $(shell pwd)/logs
TIMESTAMP  := $(shell date +%Y%m%d_%H%M%S)

# Shared test variables (DRY — matches biofoundation/VFM pattern)
NET_APP   = --network=adept_application_network
TEST_VOLS = -v "$(ACADEMY_PKG_DIR)":/app/academy_mcp_server:ro \
            -v "$(PROJECT_ROOT)/pyproject.toml":/app/pyproject.toml:ro
TEST_ENV  = -w /app -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1
TEST_SVC_ENV = -e MCP_URL=http://$(CONTAINER_MCP):$(MCP_PORT) \
               -e ACADEMY_MCP_URL=http://$(CONTAINER_MCP):$(MCP_PORT) \
               -e ADEPT_REDIS_HOST=redis -e ADEPT_REDIS_PORT=6379

# Composed run commands
#   TEST_RUN         : offline (no network), RO volumes
#   TEST_RUN_NET     : application network, RO volumes, service env
TEST_RUN     = $(ENGINE) run --rm --user $$(id -u):$$(id -g) \
	$(TEST_VOLS) $(TEST_ENV) $(VALIDATION_IMAGE) /app/.venv/bin/python
TEST_RUN_NET = $(ENGINE) run --rm --user $$(id -u):$$(id -g) \
	$(NET_APP) $(TEST_VOLS) $(TEST_ENV) $(TEST_SVC_ENV) $(VALIDATION_IMAGE) /app/.venv/bin/python

ensure-test-image:
	@$(ENGINE) image inspect $(VALIDATION_IMAGE) >/dev/null 2>&1 || { \
		echo "  Test image $(VALIDATION_IMAGE) not found — building..."; \
		$(MAKE) build; \
	}

# Run all tests (unit + integration)
validate-tests: ensure-test-image
	@echo "--> Running full Academy MCP Server test suite..."
	$(TEST_RUN) -m pytest /app/academy_mcp_server/tests/ -v --tb=short
	@echo "  All tests passed"

# Run unit tests only (agent_templates, schemas, config, register script — no Academy Manager needed)
validate-unit: ensure-test-image
	@echo "--> Running unit tests (schemas + agent templates + config + register script)..."
	$(TEST_RUN) -m pytest \
		/app/academy_mcp_server/tests/test_agent_templates.py \
		/app/academy_mcp_server/tests/test_schemas.py \
		/app/academy_mcp_server/tests/test_config.py \
		/app/academy_mcp_server/tests/test_register_script.py \
		-v --tb=short
	@echo "  Unit tests passed"

# Run integration tests (manager_registry, lifecycle, main, nginx — need Academy runtime)
validate-integration: ensure-test-image
	@echo "--> Running integration tests (registry + lifecycle + endpoints + nginx proxy)..."
	$(TEST_RUN) -m pytest \
		/app/academy_mcp_server/tests/test_manager_registry.py \
		/app/academy_mcp_server/tests/test_agent_lifecycle.py \
		/app/academy_mcp_server/tests/test_main.py \
		/app/academy_mcp_server/tests/test_nginx_proxy.py \
		-v --tb=short
	@echo "  Integration tests passed"

# E2E registration tests — runs on the HOST (needs agentic CLI + ADEPT stack + Redis)
# Uses --noconftest to avoid importing academy-py (not installed on host).
validate-registration-e2e: check-cli check-network
	@echo "--> Running E2E tool registration tests (agentic CLI -> Gateway -> Redis)..."
	PYTHONPATH="$(ACADEMY_PKG_DIR)/..:$(ACADEMY_PKG_DIR)" \
	$(shell \
		if [ -x "$(PROJECT_ROOT)/.venv311/bin/pytest" ]; then \
			echo "$(PROJECT_ROOT)/.venv311/bin/pytest"; \
		elif [ -x "$(PROJECT_ROOT)/.venv/bin/pytest" ]; then \
			echo "$(PROJECT_ROOT)/.venv/bin/pytest"; \
		else \
			echo "pytest"; \
		fi \
	) \
		$(ACADEMY_PKG_DIR)/tests/test_tool_registration_e2e.py \
		--noconftest \
		-v --tb=short
	@echo "  E2E registration tests passed"

# ---------------------------------------------------------------------------
# Globus Tool Tests (mocked SDK — offline)
# ---------------------------------------------------------------------------

validate-globus-tools: ensure-test-image
	@echo "--> Running Globus tool unit tests (71 tests, mocked SDK)..."
	@$(TEST_RUN) -m pytest \
		academy_mcp_server/tests/test_globus_transfer.py \
		academy_mcp_server/tests/test_globus_search.py \
		academy_mcp_server/tests/test_globus_compute.py \
		academy_mcp_server/tests/test_globus_flows.py \
		academy_mcp_server/tests/test_globus_groups.py \
		academy_mcp_server/tests/test_globus_client.py \
		-v --tb=short
	@echo "  Globus tool tests passed"

validate-globus-tools-integration: ensure-test-image
	@echo "--> Running Globus integration tests (live API — requires ACADEMY_GLOBUS_CLIENT_ID)..."
	@$(ENGINE) run --rm --user $$(id -u):$$(id -g) \
		$(TEST_VOLS) $(TEST_ENV) \
		-e ACADEMY_GLOBUS_CLIENT_ID=$(ACADEMY_GLOBUS_CLIENT_ID) \
		-e ACADEMY_GLOBUS_CLIENT_SECRET=$(ACADEMY_GLOBUS_CLIENT_SECRET) \
		$(VALIDATION_IMAGE) /app/.venv/bin/python -m pytest \
		academy_mcp_server/tests/test_globus_integration.py \
		-v --tb=short
	@echo "  Globus integration tests passed"

validate-globus-all: validate-globus-tools
	@echo "--> All Globus tests passed (71 unit)"

nohup-test-globus: ensure-test-image ensure-log-dir
	@echo "--> Running Globus tool tests in background -> $(LOG_DIR)/academy_test_globus_$$(date +%Y%m%d_%H%M%S).log"
	@nohup $(TEST_RUN) -m pytest \
		academy_mcp_server/tests/test_globus_transfer.py \
		academy_mcp_server/tests/test_globus_search.py \
		academy_mcp_server/tests/test_globus_compute.py \
		academy_mcp_server/tests/test_globus_flows.py \
		academy_mcp_server/tests/test_globus_groups.py \
		academy_mcp_server/tests/test_globus_client.py \
		-v --tb=short > $(LOG_DIR)/academy_test_globus_$$(date +%Y%m%d_%H%M%S).log 2>&1 &
	@echo "  PID: $$!  -- tail -f $(LOG_DIR)/academy_test_globus_*.log"

## Infrastructure health: Redis isolation + tool visibility (dual-network: app + data)
test-infrastructure-health: ensure-test-image
	@echo "--> Running infrastructure health tests (dual-network)..."
	@CID=$$($(ENGINE) create --rm \
		$(NET_APP) $(TEST_VOLS) $(TEST_ENV) $(TEST_SVC_ENV) \
		--entrypoint python $(VALIDATION_IMAGE) \
		-m pytest academy_mcp_server/tests/test_infrastructure_health.py -v --tb=short) && \
	$(ENGINE) network connect adept_data_network $$CID 2>/dev/null; \
	$(ENGINE) start -a $$CID

## Full registration lifecycle validation (9-step: health → deregister → register → verify → E2E)
validate-registration-lifecycle:
	@$(PROJECT_ROOT)/scripts/diagnostics/test_tool_registration_lifecycle.sh \
		--stack academy \
		--container $(CONTAINER_MCP) \
		--health-port $(MCP_PORT) \
		--tool-count 4 \
		--tools "launch_academy_agent_tool,invoke_agent_action_tool,list_academy_agents_tool,shutdown_academy_agent_tool" \
		--register-cmd "make register-tools" \
		--deregister-cmd "make deregister-tools" \
		--stack-dir examples/academy_mcp_server

## Dual-network ADEPT registration test (G8)
## Verifies tools exist in Redis from INSIDE a container (needs app + data networks)
test-registration-adept: ensure-test-image
	@echo "--> Running ADEPT tool registration tests (dual-network: app + data)..."
	@CID=$$($(ENGINE) create --rm \
		$(NET_APP) $(TEST_VOLS) $(TEST_ENV) $(TEST_SVC_ENV) \
		-e ACADEMY_REDIS_URL=redis://redis:6379 \
		--entrypoint python $(VALIDATION_IMAGE) \
		-m pytest academy_mcp_server/tests/test_tool_registration_e2e.py::TestADEPTToolRegistration -v --tb=short) && \
	$(ENGINE) network connect adept_data_network $$CID && \
	$(ENGINE) start -a $$CID
	@echo "  ADEPT registration tests passed"

## CLI-in-container lifecycle test (G9)
## Installs agentic CLI from source, runs full register/verify/delete cycle
test-registration-lifecycle: ensure-test-image
	@echo "--> Running CLI registration lifecycle tests (dual-network + agentic CLI)..."
	@CID=$$($(ENGINE) create --rm \
		$(NET_APP) $(TEST_VOLS) $(TEST_ENV) \
		-v "$(PROJECT_ROOT)/src":/project/src:ro \
		-e KEYCLOAK_URL=$(KEYCLOAK_URL) \
		-e AGENT_GATEWAY_URL=http://agent_gateway:8081 \
		-e ACADEMY_REDIS_URL=redis://redis:6379 \
		-e ADMIN_USER=$(ADMIN_USER) \
		-e ADMIN_PASS=$(ADMIN_PASS) \
		-e HOME=/tmp \
		--entrypoint /bin/bash $(VALIDATION_IMAGE) \
		-c "cp -r /project/src /tmp/src && python -m venv /tmp/cli_venv && /tmp/cli_venv/bin/pip install -q /tmp/src/ 2>&1 | tail -3 && export PATH=/tmp/cli_venv/bin:\$$PATH && echo CLI: \$$(which agentic) && /app/.venv/bin/python -m pytest academy_mcp_server/tests/test_tool_registration_e2e.py::TestCLIRegistrationLifecycle -v --tb=short") && \
	$(ENGINE) network connect adept_data_network $$CID && \
	$(ENGINE) start -a $$CID
	@echo "  CLI registration lifecycle tests passed"

# ====================================================================================
# E2E Lifecycle Tests (Tier 1-4)
#
# Comprehensive lifecycle tests covering:
#   Tier 1: MCP tool discovery via JSON-RPC tools/list
#   Tier 2: Auth flows (Keycloak JWT → Gateway → Orchestration → Academy MCP)
#   Tier 3: Full lifecycle (register → list → invoke → deregister)
#   Tier 4: Response API echo agent round-trip
#
# All tiers use dual-network (app + data) with agentic CLI for Tier 3.
# ====================================================================================

E2E_TEST_FILE = academy_mcp_server/tests/test_academy_e2e_lifecycle.py

## All E2E lifecycle tiers (dual-network + CLI + Redis)
test-e2e-lifecycle: ensure-test-image
	@echo "--> Running ALL E2E lifecycle tests (Tiers 1-4, dual-network)..."
	@CID=$$($(ENGINE) create --rm \
		$(NET_APP) $(TEST_VOLS) $(TEST_ENV) $(TEST_SVC_ENV) \
		-v "$(PROJECT_ROOT)/src":/project/src:ro \
		-e KEYCLOAK_URL=$(KEYCLOAK_URL) \
		-e AGENT_GATEWAY_URL=http://agent_gateway:8081 \
		-e ACADEMY_MCP_URL=http://$(CONTAINER_MCP):$(MCP_PORT) \
		-e ACADEMY_NGINX_URL=http://$(CONTAINER_PROXY):80 \
		-e ACADEMY_REDIS_URL=redis://redis:6379 \
		-e ADMIN_USER=$(ADMIN_USER) \
		-e ADMIN_PASS=$(ADMIN_PASS) \
		-e HOME=/tmp \
		--entrypoint /bin/bash $(VALIDATION_IMAGE) \
		-c "cp -r /project/src /tmp/src && python -m venv /tmp/cli_venv && /tmp/cli_venv/bin/pip install -q /tmp/src/ 2>&1 | tail -3 && export PATH=/tmp/cli_venv/bin:\$$PATH && /app/.venv/bin/python -m pytest $(E2E_TEST_FILE) -v --tb=short") && \
	$(ENGINE) network connect adept_data_network $$CID 2>/dev/null || true && \
	$(ENGINE) network connect adept_frontend_network $$CID 2>/dev/null || true && \
	$(ENGINE) start -a $$CID
	@echo "  E2E lifecycle tests passed"

## Tier 1 only: MCP tool discovery (application network only)
test-e2e-mcp-discovery: ensure-test-image
	@echo "--> Running Tier 1: MCP tool discovery tests..."
	@$(ENGINE) run --rm --user $$(id -u):$$(id -g) \
		$(NET_APP) $(TEST_VOLS) $(TEST_ENV) $(TEST_SVC_ENV) \
		-e ACADEMY_MCP_URL=http://$(CONTAINER_MCP):$(MCP_PORT) \
		-e ACADEMY_NGINX_URL=http://$(CONTAINER_PROXY):80 \
		$(VALIDATION_IMAGE) /app/.venv/bin/python -m pytest \
		$(E2E_TEST_FILE)::TestMCPToolDiscovery -v --tb=short
	@echo "  MCP tool discovery tests passed"

## Tier 2 only: Auth flows (dual-network for nginx access)
test-e2e-auth-flows: ensure-test-image
	@echo "--> Running Tier 2: Authentication flow tests..."
	@CID=$$($(ENGINE) create --rm \
		$(NET_APP) $(TEST_VOLS) $(TEST_ENV) $(TEST_SVC_ENV) \
		-e KEYCLOAK_URL=$(KEYCLOAK_URL) \
		-e AGENT_GATEWAY_URL=http://agent_gateway:8081 \
		-e HOME=/tmp \
		-e ADMIN_USER=$(ADMIN_USER) \
		-e ADMIN_PASS=$(ADMIN_PASS) \
		--entrypoint python $(VALIDATION_IMAGE) \
		-m pytest $(E2E_TEST_FILE)::TestAuthFlows -v --tb=short) && \
	$(ENGINE) network connect adept_frontend_network $$CID 2>/dev/null || true && \
	$(ENGINE) start -a $$CID
	@echo "  Auth flow tests passed"

## Tier 3 only: Full lifecycle (dual-network + CLI + Redis)
test-e2e-full-lifecycle: ensure-test-image
	@echo "--> Running Tier 3: Full lifecycle tests (register/invoke/deregister)..."
	@CID=$$($(ENGINE) create --rm \
		$(NET_APP) $(TEST_VOLS) $(TEST_ENV) $(TEST_SVC_ENV) \
		-v "$(PROJECT_ROOT)/src":/project/src:ro \
		-e KEYCLOAK_URL=$(KEYCLOAK_URL) \
		-e AGENT_GATEWAY_URL=http://agent_gateway:8081 \
		-e ACADEMY_REDIS_URL=redis://redis:6379 \
		-e ADMIN_USER=$(ADMIN_USER) \
		-e ADMIN_PASS=$(ADMIN_PASS) \
		-e HOME=/tmp \
		--entrypoint /bin/bash $(VALIDATION_IMAGE) \
		-c "cp -r /project/src /tmp/src && python -m venv /tmp/cli_venv && /tmp/cli_venv/bin/pip install -q /tmp/src/ 2>&1 | tail -3 && export PATH=/tmp/cli_venv/bin:\$$PATH && /app/.venv/bin/python -m pytest $(E2E_TEST_FILE)::TestFullLifecycle -v --tb=short") && \
	$(ENGINE) network connect adept_data_network $$CID 2>/dev/null || true && \
	$(ENGINE) start -a $$CID
	@echo "  Full lifecycle tests passed"

## Tier 4 only: Response API echo agent (dual-network)
test-e2e-echo-agent: ensure-test-image
	@echo "--> Running Tier 4: Response API echo agent tests..."
	@CID=$$($(ENGINE) create --rm \
		$(NET_APP) $(TEST_VOLS) $(TEST_ENV) $(TEST_SVC_ENV) \
		-e KEYCLOAK_URL=$(KEYCLOAK_URL) \
		-e AGENT_GATEWAY_URL=http://agent_gateway:8081 \
		-e ACADEMY_MCP_URL=http://$(CONTAINER_MCP):$(MCP_PORT) \
		-e ADMIN_USER=$(ADMIN_USER) \
		-e ADMIN_PASS=$(ADMIN_PASS) \
		-e HOME=/tmp \
		--entrypoint python $(VALIDATION_IMAGE) \
		-m pytest $(E2E_TEST_FILE)::TestResponseAPIEchoAgent -v --tb=short) && \
	$(ENGINE) network connect adept_frontend_network $$CID 2>/dev/null || true && \
	$(ENGINE) start -a $$CID
	@echo "  Response API echo agent tests passed"

## Background runner for all E2E lifecycle tests
nohup-test-e2e-lifecycle: ensure-test-image ensure-log-dir
	@echo "--> Running E2E lifecycle tests in background -> $(LOG_DIR)/academy_e2e_lifecycle_$(TIMESTAMP).log"
	@nohup /bin/bash -c '\
		CID=$$($(ENGINE) create --rm \
			$(NET_APP) $(TEST_VOLS) $(TEST_ENV) $(TEST_SVC_ENV) \
			-v "$(PROJECT_ROOT)/src":/project/src:ro \
			-e KEYCLOAK_URL=$(KEYCLOAK_URL) \
			-e AGENT_GATEWAY_URL=http://agent_gateway:8081 \
			-e ACADEMY_MCP_URL=http://$(CONTAINER_MCP):$(MCP_PORT) \
			-e ACADEMY_NGINX_URL=http://$(CONTAINER_PROXY):80 \
			-e ACADEMY_REDIS_URL=redis://redis:6379 \
			-e ADMIN_USER=$(ADMIN_USER) \
			-e ADMIN_PASS=$(ADMIN_PASS) \
			-e HOME=/tmp \
			--entrypoint /bin/bash $(VALIDATION_IMAGE) \
			-c "cp -r /project/src /tmp/src && python -m venv /tmp/cli_venv && /tmp/cli_venv/bin/pip install -q /tmp/src/ 2>&1 | tail -3 && export PATH=/tmp/cli_venv/bin:\$$PATH && /app/.venv/bin/python -m pytest $(E2E_TEST_FILE) -v --tb=short") && \
		$(ENGINE) network connect adept_data_network $$CID 2>/dev/null || true && \
		$(ENGINE) network connect adept_frontend_network $$CID 2>/dev/null || true && \
		$(ENGINE) start -a $$CID' \
		> $(LOG_DIR)/academy_e2e_lifecycle_$(TIMESTAMP).log 2>&1 &
	@echo "  PID: $$!  -- tail -f $(LOG_DIR)/academy_e2e_lifecycle_$(TIMESTAMP).log"

# ====================================================================================
# Nohup Test Runners — background execution with timestamped log files
# ====================================================================================

ensure-log-dir:
	@mkdir -p $(LOG_DIR)

nohup-test-all: ensure-test-image ensure-log-dir
	@echo "--> Running ALL tests in background -> $(LOG_DIR)/academy_test_all_$(TIMESTAMP).log"
	@nohup $(TEST_RUN) -m pytest /app/academy_mcp_server/tests/ -v --tb=short \
		> $(LOG_DIR)/academy_test_all_$(TIMESTAMP).log 2>&1 &
	@echo "  PID: $$!  -- tail -f $(LOG_DIR)/academy_test_all_$(TIMESTAMP).log"

nohup-test-unit: ensure-test-image ensure-log-dir
	@echo "--> Running unit tests in background -> $(LOG_DIR)/academy_test_unit_$(TIMESTAMP).log"
	@nohup $(TEST_RUN) -m pytest \
		/app/academy_mcp_server/tests/test_agent_templates.py \
		/app/academy_mcp_server/tests/test_schemas.py \
		/app/academy_mcp_server/tests/test_config.py \
		/app/academy_mcp_server/tests/test_register_script.py \
		-v --tb=short \
		> $(LOG_DIR)/academy_test_unit_$(TIMESTAMP).log 2>&1 &
	@echo "  PID: $$!  -- tail -f $(LOG_DIR)/academy_test_unit_$(TIMESTAMP).log"

nohup-test-integration: ensure-test-image ensure-log-dir
	@echo "--> Running integration tests in background -> $(LOG_DIR)/academy_test_integration_$(TIMESTAMP).log"
	@nohup $(TEST_RUN) -m pytest \
		/app/academy_mcp_server/tests/test_manager_registry.py \
		/app/academy_mcp_server/tests/test_agent_lifecycle.py \
		/app/academy_mcp_server/tests/test_main.py \
		/app/academy_mcp_server/tests/test_nginx_proxy.py \
		-v --tb=short \
		> $(LOG_DIR)/academy_test_integration_$(TIMESTAMP).log 2>&1 &
	@echo "  PID: $$!  -- tail -f $(LOG_DIR)/academy_test_integration_$(TIMESTAMP).log"

nohup-test-registration-adept: ensure-test-image ensure-log-dir
	@echo "--> Running ADEPT registration tests in background -> $(LOG_DIR)/academy_test_reg_adept_$(TIMESTAMP).log"
	@nohup /bin/bash -c '\
		CID=$$($(ENGINE) create --rm \
			$(NET_APP) $(TEST_VOLS) $(TEST_ENV) $(TEST_SVC_ENV) \
			-e ACADEMY_REDIS_URL=redis://redis:6379 \
			--entrypoint python $(VALIDATION_IMAGE) \
			-m pytest academy_mcp_server/tests/test_tool_registration_e2e.py::TestADEPTToolRegistration -v --tb=short) && \
		$(ENGINE) network connect adept_data_network $$CID && \
		$(ENGINE) start -a $$CID' \
		> $(LOG_DIR)/academy_test_reg_adept_$(TIMESTAMP).log 2>&1 &
	@echo "  PID: $$!  -- tail -f $(LOG_DIR)/academy_test_reg_adept_$(TIMESTAMP).log"

nohup-test-registration-lifecycle: ensure-test-image ensure-log-dir
	@echo "--> Running CLI lifecycle tests in background -> $(LOG_DIR)/academy_test_reg_lifecycle_$(TIMESTAMP).log"
	@nohup /bin/bash -c '\
		CID=$$($(ENGINE) create --rm \
			$(NET_APP) $(TEST_VOLS) $(TEST_ENV) \
			-v "$(PROJECT_ROOT)/src":/project/src:ro \
			-e KEYCLOAK_URL=$(KEYCLOAK_URL) \
			-e AGENT_GATEWAY_URL=http://agent_gateway:8081 \
			-e ACADEMY_REDIS_URL=redis://redis:6379 \
			-e ADMIN_USER=$(ADMIN_USER) \
			-e ADMIN_PASS=$(ADMIN_PASS) \
			-e HOME=/tmp \
			--entrypoint /bin/bash $(VALIDATION_IMAGE) \
			-c "cp -r /project/src /tmp/src && python -m venv /tmp/cli_venv && /tmp/cli_venv/bin/pip install -q /tmp/src/ 2>&1 | tail -3 && export PATH=/tmp/cli_venv/bin:\$$PATH && echo CLI: \$$(which agentic) && /app/.venv/bin/python -m pytest academy_mcp_server/tests/test_tool_registration_e2e.py::TestCLIRegistrationLifecycle -v --tb=short") && \
		$(ENGINE) network connect adept_data_network $$CID && \
		$(ENGINE) start -a $$CID' \
		> $(LOG_DIR)/academy_test_reg_lifecycle_$(TIMESTAMP).log 2>&1 &
	@echo "  PID: $$!  -- tail -f $(LOG_DIR)/academy_test_reg_lifecycle_$(TIMESTAMP).log"

# ====================================================================================
# Logging
# ====================================================================================

logs:
	$(ENGINE) compose -f $(COMPOSE_FILE) logs -f --tail 50

logs-mcp:
	$(ENGINE) logs $(CONTAINER_MCP) --tail 50 -f

logs-proxy:
	$(ENGINE) logs $(CONTAINER_PROXY) --tail 50 -f

logs-short:
	$(ENGINE) logs $(CONTAINER_MCP) --tail 20

# ====================================================================================
# Help
# ====================================================================================

help:
	@echo ""
	@echo "Academy MCP Server Makefile"
	@echo "==========================="
	@echo ""
	@echo "Lifecycle:"
	@echo "  make setup            Full setup: build, start, register, verify"
	@echo "  make rebuild          Rebuild from scratch and re-register"
	@echo "  make rebuild-quick    Rebuild with cache (no re-register)"
	@echo "  make teardown         Stop and deregister all"
	@echo ""
	@echo "Docker:"
	@echo "  make build            Build images"
	@echo "  make build-no-cache   Build images (no cache)"
	@echo "  make start            Start 3 containers"
	@echo "  make stop             Stop containers"
	@echo "  make restart          Restart containers"
	@echo ""
	@echo "Tools:"
	@echo "  make register-tools   Register 4 tools with ADEPT (two-step: container discovery + host CLI)"
	@echo "  make deregister-tools Remove tools from ADEPT"
	@echo "  make verify-tools     Check Redis for tool metadata"
	@echo "  make show-schemas     Print auto-discovered tool schemas"
	@echo ""
	@echo "Data:"
	@echo "  make init-data        Create data directories with UID 1200:1200"
	@echo ""
	@echo "Testing (interactive):"
	@echo "  make validate-tests              Run all tests (unit + integration)"
	@echo "  make validate-unit               Unit tests (schemas, templates, config, register script)"
	@echo "  make validate-integration        Integration tests (registry, lifecycle, endpoints, nginx)"
	@echo "  make validate-registration-e2e   E2E registration tests (CLI -> Gateway -> Redis)"
	@echo "  make test-registration-adept     Dual-network Redis verification (app + data networks)"
	@echo "  make test-registration-lifecycle CLI-in-container register/verify/delete cycle"
	@echo "  make test-infrastructure-health Redis isolation + tool visibility (dual-network)"
	@echo "  make validate-registration-lifecycle Full 9-step registration lifecycle (live ADEPT)"
	@echo ""
	@echo "E2E Lifecycle Tests (Tiers 1-4):"
	@echo "  make test-e2e-lifecycle        All 4 tiers (dual-network + CLI + Redis)"
	@echo "  make test-e2e-mcp-discovery    Tier 1: MCP JSON-RPC tools/list discovery"
	@echo "  make test-e2e-auth-flows       Tier 2: Keycloak JWT auth chain"
	@echo "  make test-e2e-full-lifecycle   Tier 3: Register/list/invoke/deregister"
	@echo "  make test-e2e-echo-agent       Tier 4: Response API echo agent round-trip"
	@echo ""
	@echo "Testing (nohup + timestamped logs in logs/):"
	@echo "  make nohup-test-all                    All tests in background"
	@echo "  make nohup-test-unit                   Unit tests in background"
	@echo "  make nohup-test-integration            Integration tests in background"
	@echo "  make nohup-test-registration-adept     ADEPT Redis verification (dual-network, background)"
	@echo "  make nohup-test-registration-lifecycle CLI lifecycle (dual-network + CLI, background)"
	@echo "  make nohup-test-e2e-lifecycle           E2E lifecycle (all tiers, background)"
	@echo ""
	@echo "Verification:"
	@echo "  make health           Check all 3 service health endpoints"
	@echo "  make smoke-test       E2E test via Response API"
	@echo ""
	@echo "Logging:"
	@echo "  make logs             All container logs"
	@echo "  make logs-mcp         MCP server logs only"
	@echo "  make logs-proxy       Nginx proxy logs only"
	@echo "  make logs-short       Last 20 MCP server log lines"
	@echo ""
	@echo "Configuration (override via environment):"
	@echo "  ENGINE=docker         Container engine (docker or podman)"
	@echo "  ADMIN_USER=admin      Admin username for tool registration"
	@echo "  ADMIN_PASS=admin      Admin password for tool registration"
	@echo "  KEYCLOAK_URL          Keycloak URL (default: http://keycloak:8180)"
	@echo "  GATEWAY_URL           Agent Gateway URL (default: http://localhost:8083)"
	@echo ""
