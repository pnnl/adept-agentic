# Makefile for OpenTrons MCP Server — Build, Register, and Teardown
#
# This Makefile automates the full lifecycle of the OpenTrons MCP server:
#   1. Docker image build and container start (on adept_application_network)
#   2. Tool registration with ADEPT's dynamic tool management via agentic CLI
#   3. Health verification and E2E smoke tests
#   4. Teardown and cleanup
#
# Prerequisites:
#   - ADEPT core stack running (make start from project root)
#   - adept_application_network must exist
#   - agentic CLI installed (pip install -e src/ from project root)
#
# Usage:
#   make setup            # Full lifecycle: build, start, wait, register, verify
#   make rebuild          # Rebuild image from scratch and re-register tool
#   make teardown         # Stop container and deregister tool
#
#   make build            # Build Docker image only
#   make start            # Start container only
#   make stop             # Stop container only
#   make register-tool    # Register tool via agentic CLI only
#   make deregister-tool  # Deregister tool via agentic CLI only
#   make health           # Check container health endpoint
#   make smoke-test       # Run E2E smoke test via Response API
#   make logs             # Tail container logs

SHELL := /bin/bash

# ====================================================================================
# Configuration
# ====================================================================================

PROJECT_ROOT := $(shell cd ../.. && pwd)
COMPOSE_FILE := docker-compose.opentrons.yaml
CONTAINER_NAME := opentrons_mcp_server
SERVER_PORT := 9003

# MCP tool registration parameters
TOOL_NAME := execute_opentrons_protocol
TOOL_DISPLAY_NAME := execute_opentrons_protocol_tool
TOOL_PROTOCOL := mcp
TOOL_URL := http://$(CONTAINER_NAME):$(SERVER_PORT)/mcp
TOOL_DESCRIPTION := Execute an OpenTrons OT-2 liquid handling protocol. \
Supports 96-well and 384-well plates with p10, p20, p300, and p1000 pipettes. \
Validates and executes transfer protocols in dry-run (validation) or live mode.
TOOL_ARGS_SCHEMA := {"protocol_json":{"type":"object","description":"Protocol spec with protocol_name (str), plate_type (96-well|384-well), transfers (array of {source_well, dest_well, volume_ul, tip_type})"},"dry_run":{"type":"boolean","description":"If true, validate only without executing on hardware (default: true)","default":true}}

# agentic CLI — auto-detect from project venv or PATH
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

# Keycloak URL for token generation (smoke test)
KEYCLOAK_URL ?= http://localhost:8180

# Agent Gateway URL for smoke test (host port)
GATEWAY_URL ?= http://localhost:8083

# Note: agentic CLI uses Rich spinners that corrupt terminal output when piped.
# We suppress CLI output (>/dev/null 2>&1) and print our own status lines instead.

.PHONY: all setup rebuild teardown build start stop restart \
	register-tool deregister-tool verify-tool \
	health wait-healthy smoke-test logs help \
	check-cli check-network

# ====================================================================================
# Combined Lifecycle Targets
# ====================================================================================

all: setup

setup: check-prerequisites build start wait-healthy register-tool verify-tool
	@echo "DONE: OpenTrons MCP Server setup complete"
	@echo "  Container: $(CONTAINER_NAME) (port $(SERVER_PORT))"
	@echo "  Tool:      $(TOOL_NAME) (protocol: $(TOOL_PROTOCOL))"
	@echo "  Health:    http://localhost:$(SERVER_PORT)/health"
	@echo "  MCP:       $(TOOL_URL) (internal Docker network)"

rebuild: stop build-no-cache start wait-healthy deregister-tool register-tool verify-tool
	@echo "DONE: OpenTrons MCP Server rebuilt and re-registered"

teardown: deregister-tool stop
	@echo "DONE: OpenTrons MCP Server torn down"

# ====================================================================================
# Prerequisite Checks
# ====================================================================================

check-prerequisites: check-cli check-network

check-cli:
	@if [ -z "$(AGENTIC_CLI)" ]; then \
		echo "ERROR: agentic CLI not found"; \
		echo "Install it with: cd $(PROJECT_ROOT) && pip install -e src/"; \
		echo "Or create a venv: python3.11 -m venv .venv311 && .venv311/bin/pip install -e src/"; \
		exit 1; \
	fi
	@echo "  agentic CLI: $(AGENTIC_CLI)"

check-network:
	@docker network inspect adept_application_network >/dev/null 2>&1 || \
		(echo "ERROR: adept_application_network not found. Start ADEPT first: make start (from project root)" && exit 1)
	@echo "  Docker network: adept_application_network exists"

# ====================================================================================
# Docker Build & Container Targets
# ====================================================================================

build:
	@echo "--> Building OpenTrons MCP Server image..."
	docker compose -f $(COMPOSE_FILE) build

build-no-cache:
	@echo "--> Building OpenTrons MCP Server image (no cache)..."
	docker compose -f $(COMPOSE_FILE) build --no-cache

start:
	@echo "--> Starting OpenTrons MCP Server..."
	docker compose -f $(COMPOSE_FILE) up -d
	@echo "  Container $(CONTAINER_NAME) started on port $(SERVER_PORT)"

stop:
	@echo "--> Stopping OpenTrons MCP Server..."
	docker compose -f $(COMPOSE_FILE) down 2>/dev/null || true
	@echo "  Container stopped"

restart: stop start wait-healthy
	@echo "  Container restarted"

# ====================================================================================
# Health & Readiness
# ====================================================================================

health:
	@echo "--> Checking health..."
	@curl -sf http://localhost:$(SERVER_PORT)/health | python3 -m json.tool && \
		echo "  Healthy" || \
		(echo "  FAILED: Health check failed" && exit 1)

wait-healthy:
	@echo "--> Waiting for container to become healthy..."
	@for i in $$(seq 1 15); do \
		if curl -sf http://localhost:$(SERVER_PORT)/health >/dev/null 2>&1; then \
			echo "  Container healthy (attempt $$i)"; \
			exit 0; \
		fi; \
		echo "  Waiting... ($$i/15)"; \
		sleep 2; \
	done; \
	echo "  FAILED: Container did not become healthy within 30s"; \
	docker logs $(CONTAINER_NAME) --tail 20; \
	exit 1

# ====================================================================================
# Tool Registration via agentic CLI
# ====================================================================================

register-tool: check-cli
	@echo "--> Registering OpenTrons tool..."
	@echo "  Tool: $(TOOL_NAME) | Protocol: $(TOOL_PROTOCOL) | URL: $(TOOL_URL)"
	@$(AGENTIC_CLI) tools register $(TOOL_NAME) \
		-d "$(TOOL_DESCRIPTION)" \
		-p $(TOOL_PROTOCOL) \
		-u $(TOOL_URL) \
		--tool-name $(TOOL_DISPLAY_NAME) \
		--args-schema '$(TOOL_ARGS_SCHEMA)' \
		--username $(ADMIN_USER) --password $(ADMIN_PASS) >/dev/null 2>&1 || \
		(echo "  FAILED: Tool registration failed. Run agentic CLI directly for details." && exit 1)
	@echo "  Tool registered"

deregister-tool: check-cli
	@echo "--> Deregistering OpenTrons tool..."
	@$(AGENTIC_CLI) tools delete $(TOOL_NAME) -y \
		--username $(ADMIN_USER) --password $(ADMIN_PASS) >/dev/null 2>&1 || true
	@echo "  Tool deregistered (or was not registered)"

verify-tool:
	@echo "--> Verifying tool registration..."
	@REDIS_CHECK=$$(docker exec redis redis-cli GET "external_tool:$(TOOL_NAME)" 2>/dev/null) && \
	if [ -n "$$REDIS_CHECK" ] && [ "$$REDIS_CHECK" != "(nil)" ]; then \
		echo "  Tool '$(TOOL_NAME)' found in Redis"; \
		echo "$$REDIS_CHECK" | python3 -c "import sys,json; d=json.load(sys.stdin); inv=d.get('invocation',{}); conn=inv.get('connection',{}); print(f'     protocol={inv.get(\"protocol\",\"?\")} url={conn.get(\"url\",\"?\")} tool_name={conn.get(\"tool_name\",\"?\")}')" 2>/dev/null || true; \
	else \
		echo "  FAILED: Tool '$(TOOL_NAME)' NOT found in Redis"; \
		exit 1; \
	fi
	@ADMIN_TOKEN=$$(curl -sf -X POST "$(KEYCLOAK_URL)/realms/master/protocol/openid-connect/token" \
		-d "grant_type=password&client_id=login-client&username=$(ADMIN_USER)&password=$(ADMIN_PASS)" \
		| python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null) && \
	if [ -n "$$ADMIN_TOKEN" ]; then \
		API_CHECK=$$(curl -sf -H "Authorization: Bearer $$ADMIN_TOKEN" "$(GATEWAY_URL)/v1/tools/list" 2>/dev/null) && \
		echo "$$API_CHECK" | python3 -c "import sys,json; tools=json.load(sys.stdin); matches=[t for t in tools if t.get('name')=='$(TOOL_NAME)']; print('  Tool found in Gateway API (%d args)' % len(matches[0].get('args_schema',{}).get('properties',{}))) if matches else print('  WARNING: Tool not yet visible in Gateway API (may need restart)')" 2>/dev/null || true; \
	fi

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
			"messages": [{"role": "user", "content": "Use the execute_opentrons_protocol tool with dry_run=true and this protocol_json: {\"protocol_name\": \"Smoke Test\", \"plate_type\": \"96-well\", \"transfers\": [{\"source_well\": \"A1\", \"dest_well\": \"B1\", \"volume_ul\": 50.0, \"tip_type\": \"p300_single\"}]}"}], \
			"stream": false, \
			"max_tokens": 2000 \
		}') && \
	echo "$$RESPONSE" | python3 -m json.tool && \
	echo "  Smoke test passed (HTTP 200)" || \
	(echo "  FAILED: Smoke test failed" && exit 1)

# ====================================================================================
# Logging
# ====================================================================================

logs:
	docker logs $(CONTAINER_NAME) --tail 50 -f

logs-short:
	docker logs $(CONTAINER_NAME) --tail 20

# ====================================================================================
# Help
# ====================================================================================

help:
	@echo ""
	@echo "OpenTrons MCP Server Makefile Targets"
	@echo "========================================"
	@echo ""
	@echo "Lifecycle:"
	@echo "  make setup            Full lifecycle: build, start, register, verify"
	@echo "  make rebuild          Rebuild from scratch and re-register tool"
	@echo "  make teardown         Stop container and deregister tool"
	@echo ""
	@echo "Docker:"
	@echo "  make build            Build Docker image"
	@echo "  make build-no-cache   Build Docker image (no cache)"
	@echo "  make start            Start container"
	@echo "  make stop             Stop container"
	@echo "  make restart          Restart container"
	@echo ""
	@echo "Tool Management (agentic CLI):"
	@echo "  make register-tool    Register MCP tool with ADEPT"
	@echo "  make deregister-tool  Remove MCP tool from ADEPT"
	@echo "  make verify-tool      Verify tool appears in ADEPT tool list"
	@echo ""
	@echo "Verification:"
	@echo "  make health           Check server health endpoint"
	@echo "  make smoke-test       Run E2E smoke test via Response API"
	@echo ""
	@echo "Logging:"
	@echo "  make logs             Tail container logs (follow)"
	@echo "  make logs-short       Show last 20 log lines"
	@echo ""
	@echo "Configuration (override via environment):"
	@echo "  ADMIN_USER=admin      Admin username for tool registration"
	@echo "  ADMIN_PASS=admin      Admin password for tool registration"
	@echo "  KEYCLOAK_URL          Keycloak URL (default: http://localhost:8180)"
	@echo "  GATEWAY_URL           Agent Gateway URL (default: http://localhost:8083)"
	@echo ""
