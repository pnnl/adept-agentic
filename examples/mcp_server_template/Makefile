# Makefile for {{DISPLAY_NAME}} MCP Server
# ============================================
# This Makefile manages the lifecycle of the {{DISPLAY_NAME}} MCP server stack,
# including Docker builds, service health checks, tool registration with ADEPT,
# and comprehensive testing.

# ============================================
# Configuration
# ============================================

# Project paths — PROJECT_ROOT is the ADEPT project root (two levels up)
PROJECT_ROOT := $(shell cd ../.. && pwd)

# Container engine configuration
ENGINE ?= docker
COMPOSE_FILE ?= docker-compose.yaml
COMPOSE_CPU ?= docker-compose.cpu.yaml
COMPOSE_GPU ?= docker-compose.gpu.yaml

# Container names
CONTAINER_MCP := {{NAME}}_mcp_server
CONTAINER_PROXY := {{NAME}}_nginx_proxy
CONTAINER_REDIS := {{NAME}}_redis

# Port configuration
MCP_PORT := {{MCP_PORT}}
PROXY_HTTP_PORT := {{PROXY_HTTP_PORT}}
PROXY_HTTPS_PORT := {{PROXY_HTTPS_PORT}}
REDIS_HOST_PORT := {{REDIS_HOST_PORT}}

# Tool registration configuration
TOOL_PREFIX := {{NAME}}
TOOL_URL := http://host.docker.internal:$(PROXY_HTTP_PORT)/mcp

# Agentic CLI discovery
AGENTIC_CLI := $(shell \
	if [ -f "$(EXAMPLES_ROOT)/.venv311/bin/afk" ]; then \
		echo "$(EXAMPLES_ROOT)/.venv311/bin/afk"; \
	elif [ -f "$(EXAMPLES_ROOT)/.venv/bin/afk" ]; then \
		echo "$(EXAMPLES_ROOT)/.venv/bin/afk"; \
	elif command -v afk >/dev/null 2>&1; then \
		which afk; \
	else \
		echo ""; \
	fi)

# ADEPT authentication (for tool registration)
ADMIN_USER ?= admin
ADMIN_PASS ?= changeme
KEYCLOAK_URL ?= http://localhost:8180
GATEWAY_URL ?= http://localhost:8083

# ============================================
# Combined Lifecycle Targets
# ============================================

.PHONY: all
all: check-prerequisites build start wait-healthy register-tools health
	@echo "✅ {{DISPLAY_NAME}} MCP server stack is fully operational"

.PHONY: setup
setup: setup-cpu

.PHONY: setup-cpu
setup-cpu: check-prerequisites init-data build-cpu start-cpu wait-healthy
	@echo "✅ CPU-based setup complete"

.PHONY: setup-gpu
setup-gpu: check-prerequisites init-data build-gpu start-gpu wait-healthy
	@echo "✅ GPU-based setup complete"

.PHONY: rebuild
rebuild: stop build start wait-healthy
	@echo "✅ Rebuild complete"

.PHONY: rebuild-quick
rebuild-quick: stop build start
	@echo "✅ Quick rebuild complete (no health check)"

.PHONY: teardown
teardown:
	@echo "🧹 Tearing down {{DISPLAY_NAME}} MCP server stack..."
	$(ENGINE)-compose -f $(COMPOSE_FILE) down -v --remove-orphans
	@echo "✅ Teardown complete"

# ============================================
# Prerequisites
# ============================================

.PHONY: check-prerequisites
check-prerequisites: check-cli check-network
	@echo "✅ All prerequisites satisfied"

.PHONY: check-cli
check-cli:
	@if [ -z "$(AGENTIC_CLI)" ]; then \
		echo "❌ ERROR: agentic-framework-sdk CLI (afk) not found"; \
		echo "   Install: pip install -e $(EXAMPLES_ROOT)"; \
		exit 1; \
	fi
	@echo "✅ Found agentic CLI at: $(AGENTIC_CLI)"

.PHONY: check-network
check-network:
	@if ! $(ENGINE) network inspect adept_application_network >/dev/null 2>&1; then \
		echo "⚠️  WARNING: adept_application_network not found"; \
		echo "   This network is needed for ADEPT integration"; \
		echo "   Run 'make start' in main ADEPT directory first"; \
	else \
		echo "✅ Found adept_application_network"; \
	fi

.PHONY: init-data
init-data:
	@echo "📁 Initializing data directories..."
	@mkdir -p data/uploaded_files
	@mkdir -p data/{{NAME}}/results
	@mkdir -p logs
	@chmod -R a+rwx data logs
	@echo "✅ Data directories initialized"

# ============================================
# Docker Build Targets
# ============================================

.PHONY: build
build: build-cpu

.PHONY: build-cpu
build-cpu:
	@echo "🔨 Building {{DISPLAY_NAME}} MCP server (CPU)..."
	$(ENGINE)-compose -f $(COMPOSE_CPU) build
	@echo "✅ Build complete"

.PHONY: build-gpu
build-gpu:
	@echo "🔨 Building {{DISPLAY_NAME}} MCP server (GPU)..."
	$(ENGINE)-compose -f $(COMPOSE_GPU) build
	@echo "✅ Build complete"

.PHONY: build-no-cache
build-no-cache:
	@echo "🔨 Building {{DISPLAY_NAME}} MCP server (no cache)..."
	$(ENGINE)-compose -f $(COMPOSE_FILE) build --no-cache
	@echo "✅ Build complete"

# ============================================
# Service Management
# ============================================

.PHONY: start
start: start-cpu

.PHONY: start-cpu
start-cpu:
	@echo "🚀 Starting {{DISPLAY_NAME}} MCP server stack (CPU)..."
	$(ENGINE)-compose -f $(COMPOSE_CPU) up -d
	@echo "✅ Services started"

.PHONY: start-gpu
start-gpu:
	@echo "🚀 Starting {{DISPLAY_NAME}} MCP server stack (GPU)..."
	$(ENGINE)-compose -f $(COMPOSE_GPU) up -d
	@echo "✅ Services started"

.PHONY: stop
stop:
	@echo "🛑 Stopping {{DISPLAY_NAME}} MCP server stack..."
	$(ENGINE)-compose -f $(COMPOSE_FILE) down
	@echo "✅ Services stopped"

.PHONY: restart
restart: stop start wait-healthy
	@echo "✅ Services restarted"

# ============================================
# Health Checks
# ============================================

.PHONY: health
health:
	@echo "🏥 Health check for {{DISPLAY_NAME}} MCP server stack:"
	@echo ""
	@echo "Redis:"
	@$(ENGINE) exec $(CONTAINER_REDIS) redis-cli ping 2>/dev/null && echo "  ✅ Redis: healthy" || echo "  ❌ Redis: unhealthy"
	@echo ""
	@echo "MCP Server:"
	@curl -sf http://localhost:$(MCP_PORT)/health >/dev/null 2>&1 && echo "  ✅ MCP Server: healthy" || echo "  ❌ MCP Server: unhealthy"
	@echo ""
	@echo "Nginx Proxy:"
	@curl -sf http://localhost:$(PROXY_HTTP_PORT)/health >/dev/null 2>&1 && echo "  ✅ Nginx Proxy: healthy" || echo "  ❌ Nginx Proxy: unhealthy"

.PHONY: wait-healthy
wait-healthy:
	@echo "⏳ Waiting for services to become healthy..."
	@max_attempts=60; \
	attempt=0; \
	while [ $$attempt -lt $$max_attempts ]; do \
		if curl -sf http://localhost:$(MCP_PORT)/health >/dev/null 2>&1 && \
		   curl -sf http://localhost:$(PROXY_HTTP_PORT)/health >/dev/null 2>&1; then \
			echo "✅ All services healthy"; \
			exit 0; \
		fi; \
		attempt=$$((attempt + 1)); \
		echo "  Attempt $$attempt/$$max_attempts..."; \
		sleep 2; \
	done; \
	echo "❌ Services did not become healthy in time"; \
	exit 1

# ============================================
# Tool Registration (ADEPT Integration)
# ============================================

.PHONY: register-tools
register-tools:
	@echo "📝 Registering {{DISPLAY_NAME}} tools with ADEPT..."
	@if [ -z "$(AGENTIC_CLI)" ]; then \
		echo "❌ ERROR: agentic CLI not found"; \
		exit 1; \
	fi
	@$(AGENTIC_CLI) tools register \
		--name "$(TOOL_PREFIX)" \
		--url "$(TOOL_URL)" \
		--type mcp \
		--username "$(ADMIN_USER)" \
		--password "$(ADMIN_PASS)" \
		--keycloak-url "$(KEYCLOAK_URL)" \
		--gateway-url "$(GATEWAY_URL)"
	@echo "✅ Tool registration complete"

.PHONY: deregister-tools
deregister-tools:
	@echo "🗑️  Deregistering {{DISPLAY_NAME}} tools from ADEPT..."
	@if [ -z "$(AGENTIC_CLI)" ]; then \
		echo "❌ ERROR: agentic CLI not found"; \
		exit 1; \
	fi
	@$(AGENTIC_CLI) tools deregister \
		--name "$(TOOL_PREFIX)" \
		--username "$(ADMIN_USER)" \
		--password "$(ADMIN_PASS)" \
		--keycloak-url "$(KEYCLOAK_URL)" \
		--gateway-url "$(GATEWAY_URL)"
	@echo "✅ Tool deregistration complete"

.PHONY: verify-tools
verify-tools:
	@echo "🔍 Verifying {{DISPLAY_NAME}} tool registration..."
	@if [ -z "$(AGENTIC_CLI)" ]; then \
		echo "❌ ERROR: agentic CLI not found"; \
		exit 1; \
	fi
	@$(AGENTIC_CLI) tools list \
		--username "$(ADMIN_USER)" \
		--password "$(ADMIN_PASS)" \
		--keycloak-url "$(KEYCLOAK_URL)" \
		--gateway-url "$(GATEWAY_URL)" \
		| grep -i "$(TOOL_PREFIX)" && echo "✅ Tools verified" || echo "❌ Tools not found"

.PHONY: show-tool-schemas
show-tool-schemas:
	@echo "📋 Fetching {{DISPLAY_NAME}} tool schemas..."
	@curl -s http://localhost:$(PROXY_HTTP_PORT)/mcp/schemas | jq '.'

# ============================================
# Test Infrastructure
# ============================================

# Test image and configuration
TEST_IMAGE := agentic-framework-deps-base
TEST_VOLS := -v "$(PROJECT_ROOT)/{{NAME}}_mcp":/app/{{NAME}}_mcp:ro \
             -v "$(PROJECT_ROOT)/tests":/app/tests:ro \
             -v "$(PROJECT_ROOT)/logs":/app/logs
TEST_ENV := -e REDIS_URL=redis://$(CONTAINER_REDIS):6379 \
            -e {{NAME_UPPER}}_HOST=$(CONTAINER_MCP) \
            -e {{NAME_UPPER}}_PORT=$(MCP_PORT) \
            -e PROXY_URL=http://$(CONTAINER_PROXY):80 \
            -e TOOL_PREFIX=$(TOOL_PREFIX) \
            -e PYTHONPATH=/app
NET_APP := adept_application_network
TEST_SVC_ENV := -e ADMIN_USER=$(ADMIN_USER) \
                -e ADMIN_PASS=$(ADMIN_PASS) \
                -e KEYCLOAK_URL=$(KEYCLOAK_URL) \
                -e GATEWAY_URL=$(GATEWAY_URL)

.PHONY: ensure-test-image
ensure-test-image:
	@if ! $(ENGINE) image inspect $(TEST_IMAGE) >/dev/null 2>&1; then \
		echo "❌ ERROR: Test image $(TEST_IMAGE) not found"; \
		echo "   Build ADEPT base image first: make -C $(EXAMPLES_ROOT) build-deps-base"; \
		exit 1; \
	fi

.PHONY: ensure-log-dir
ensure-log-dir:
	@mkdir -p logs
	@chmod a+rwx logs

.PHONY: build-dev
build-dev: ensure-test-image
	@echo "🔨 Building development test image..."
	$(ENGINE) build -t {{NAME}}-mcp-test -f Dockerfile.test .
	@echo "✅ Development image built"

# ============================================
# Test Targets
# ============================================

.PHONY: test-imports
test-imports: ensure-test-image ensure-log-dir
	@echo "🧪 Testing Python imports..."
	$(ENGINE) run --rm $(TEST_VOLS) $(TEST_ENV) \
		$(TEST_IMAGE) \
		python3 -c "import {{NAME}}_mcp; print('✅ Imports successful')"

.PHONY: test-config
test-config: ensure-test-image ensure-log-dir
	@echo "🧪 Testing configuration..."
	$(ENGINE) run --rm --network=$(NET_APP) $(TEST_VOLS) $(TEST_ENV) \
		$(TEST_IMAGE) \
		python3 -m pytest tests/unit/test_config.py -v

.PHONY: test-unit
test-unit: ensure-test-image ensure-log-dir
	@echo "🧪 Running unit tests..."
	$(ENGINE) run --rm --network=$(NET_APP) $(TEST_VOLS) $(TEST_ENV) \
		$(TEST_IMAGE) \
		python3 -m pytest tests/unit/ -v --tb=short

.PHONY: test-schema-discovery
test-schema-discovery: ensure-test-image ensure-log-dir
	@echo "🧪 Testing MCP schema discovery..."
	$(ENGINE) run --rm --network=$(NET_APP) $(TEST_VOLS) $(TEST_ENV) \
		$(TEST_IMAGE) \
		python3 -m pytest tests/integration/test_schema_discovery.py -v

.PHONY: test-integration
test-integration: ensure-test-image ensure-log-dir
	@echo "🧪 Running integration tests..."
	$(ENGINE) run --rm --network=$(NET_APP) $(TEST_VOLS) $(TEST_ENV) \
		$(TEST_IMAGE) \
		python3 -m pytest tests/integration/ -v --tb=short

.PHONY: test-registration
test-registration: ensure-test-image ensure-log-dir
	@echo "🧪 Testing tool registration workflow..."
	@$(MAKE) test-registration-adept

.PHONY: test-registration-adept
test-registration-adept: ensure-test-image ensure-log-dir
	@echo "🧪 Testing ADEPT tool registration via CLI..."
	$(ENGINE) run --rm --network=$(NET_APP) \
		$(TEST_VOLS) $(TEST_ENV) $(TEST_SVC_ENV) \
		$(TEST_IMAGE) \
		python3 -m pytest tests/e2e/test_tool_registration.py -v

.PHONY: test-registration-lifecycle
test-registration-lifecycle: ensure-test-image
	@echo "--> Running CLI registration lifecycle tests (dual-network + agentic CLI)..."
	@CID=$$($(ENGINE) create --rm \
		--network=adept_application_network $(TEST_VOLS) $(TEST_ENV) $(TEST_SVC_ENV) \
		-v "$(PROJECT_ROOT)/src":/project/src:ro \
		-e KEYCLOAK_URL=$(KEYCLOAK_URL) \
		-e AGENT_GATEWAY_URL=http://agent_gateway:8081 \
		-e {{NAME_UPPER}}_REDIS_URL=redis://redis:6379 \
		-e ADMIN_USER=$(ADMIN_USER) -e ADMIN_PASS=$(ADMIN_PASS) \
		-e HOME=/tmp \
		--entrypoint /bin/bash $(TEST_IMAGE) \
		-c "cp -r /project/src /tmp/src && python -m venv /tmp/cli_venv && /tmp/cli_venv/bin/pip install -q /tmp/src/ 2>&1 | tail -3 && export PATH=/tmp/cli_venv/bin:\$$PATH && echo CLI: \$$(which agentic) && /app/.venv/bin/python -m pytest tests/test_tool_registration.py::TestCLIRegistrationLifecycle -v --tb=short") && \
	$(ENGINE) network connect adept_data_network $$CID && \
	$(ENGINE) start -a $$CID
	@echo "  CLI registration lifecycle tests passed"

.PHONY: test-all
test-all: ensure-test-image ensure-log-dir test-imports test-config test-unit test-schema-discovery test-integration test-registration
	@echo "✅ All tests complete"

# ============================================
# Nohup Test Runners (background execution)
# ============================================

.PHONY: nohup-test-all
nohup-test-all: ensure-log-dir
	@echo "🧪 Running all tests in background..."
	@nohup $(MAKE) test-all > logs/test-all-$$(date +%Y%m%d_%H%M%S).log 2>&1 &
	@echo "✅ Tests running in background. Check logs/ directory for output."

.PHONY: nohup-test-integration
nohup-test-integration: ensure-log-dir
	@echo "🧪 Running integration tests in background..."
	@nohup $(MAKE) test-integration > logs/test-integration-$$(date +%Y%m%d_%H%M%S).log 2>&1 &
	@echo "✅ Tests running in background. Check logs/ directory for output."

# ============================================
# Logging
# ============================================

.PHONY: logs
logs:
	$(ENGINE)-compose -f $(COMPOSE_FILE) logs -f

.PHONY: logs-mcp
logs-mcp:
	$(ENGINE) logs -f $(CONTAINER_MCP)

.PHONY: logs-proxy
logs-proxy:
	$(ENGINE) logs -f $(CONTAINER_PROXY)

.PHONY: logs-redis
logs-redis:
	$(ENGINE) logs -f $(CONTAINER_REDIS)

# ============================================
# Help
# ============================================

.PHONY: help
help:
	@echo "{{DISPLAY_NAME}} MCP Server - Makefile Commands"
	@echo "================================================"
	@echo ""
	@echo "Combined Lifecycle:"
	@echo "  all                 - Build, start, health check, and register tools"
	@echo "  setup               - Full setup (CPU mode)"
	@echo "  setup-cpu           - Setup with CPU configuration"
	@echo "  setup-gpu           - Setup with GPU configuration"
	@echo "  rebuild             - Stop, rebuild, start, and health check"
	@echo "  rebuild-quick       - Rebuild without health check"
	@echo "  teardown            - Stop and remove all containers and volumes"
	@echo ""
	@echo "Prerequisites:"
	@echo "  check-prerequisites - Verify all prerequisites"
	@echo "  check-cli           - Check for agentic CLI"
	@echo "  check-network       - Check for ADEPT network"
	@echo "  init-data           - Initialize data directories"
	@echo ""
	@echo "Docker Build:"
	@echo "  build               - Build Docker images (CPU)"
	@echo "  build-cpu           - Build with CPU configuration"
	@echo "  build-gpu           - Build with GPU configuration"
	@echo "  build-no-cache      - Build without cache"
	@echo ""
	@echo "Service Management:"
	@echo "  start               - Start services (CPU)"
	@echo "  start-cpu           - Start with CPU configuration"
	@echo "  start-gpu           - Start with GPU configuration"
	@echo "  stop                - Stop services"
	@echo "  restart             - Restart services with health check"
	@echo ""
	@echo "Health Checks:"
	@echo "  health              - Check service health"
	@echo "  wait-healthy        - Wait for services to become healthy"
	@echo ""
	@echo "Tool Registration:"
	@echo "  register-tools      - Register tools with ADEPT"
	@echo "  deregister-tools    - Deregister tools from ADEPT"
	@echo "  verify-tools        - Verify tool registration"
	@echo "  show-tool-schemas   - Display tool schemas"
	@echo ""
	@echo "Testing:"
	@echo "  test-imports        - Test Python imports"
	@echo "  test-config         - Test configuration"
	@echo "  test-unit           - Run unit tests"
	@echo "  test-schema-discovery - Test MCP schema discovery"
	@echo "  test-integration    - Run integration tests"
	@echo "  test-registration   - Test tool registration workflow"
	@echo "  test-registration-adept - Test ADEPT CLI registration"
	@echo "  test-registration-lifecycle - Test full lifecycle (ephemeral venv)"
	@echo "  test-all            - Run all tests"
	@echo "  nohup-test-all      - Run all tests in background"
	@echo "  nohup-test-integration - Run integration tests in background"
	@echo ""
	@echo "Development:"
	@echo "  build-dev           - Build development test image"
	@echo ""
	@echo "Logging:"
	@echo "  logs                - Show all logs (follow)"
	@echo "  logs-mcp            - Show MCP server logs"
	@echo "  logs-proxy          - Show nginx proxy logs"
	@echo "  logs-redis          - Show Redis logs"
	@echo ""
	@echo "Configuration:"
	@echo "  ENGINE              - Container engine (docker/podman) [default: docker]"
	@echo "  COMPOSE_FILE        - Docker compose file [default: docker-compose.yaml]"
	@echo "  ADMIN_USER          - ADEPT admin username [default: admin]"
	@echo "  ADMIN_PASS          - ADEPT admin password [default: changeme]"
	@echo "  KEYCLOAK_URL        - Keycloak URL [default: http://localhost:8180]"
	@echo "  GATEWAY_URL         - ADEPT Gateway URL [default: http://localhost:8083]"
