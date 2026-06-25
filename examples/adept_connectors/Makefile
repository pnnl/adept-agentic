# adept_connectors test runner
#
# Four-tier strategy: unit → integration → e2e → uat
# ALL FOUR TIERS MUST BE RUN. NO TIER MAY BE SKIPPED.
# All invocations produce timestamped logs in logs/ for evidence.
#
# Two execution modes:
#   Host mode:      uv run / python -m pytest (fast, local .venv)
#   Container mode: docker create + network connect + docker start
#                   (validates nginx HTTPS path with ROPC password auth)
#
# See: docs/claude_desktop/TESTING_STRATEGY.md

PYTEST = uv run pytest
UNIT_ARGS     = tests/core/ tests/connectors/ -v --tb=short
INTEG_ARGS    = tests/integration/test_core_integration.py -v --tb=short -m integration
E2E_ARGS      = tests/integration/test_e2e.py -v --tb=short -m e2e
UAT_ARGS      = tests/integration/test_uat.py -v --tb=short -m uat
LOGDIR        = logs
TIMESTAMP     = $(shell date +%Y%m%d_%H%M%S)

# Container-based test settings
# Uses agentic-framework-deps-base image with /app/.venv (pre-installed deps).
# Source and tests mounted read-only. Dual-network: application + frontend.
DEPS_IMAGE       = agentic-framework-deps-base
APP_NET          = adept_application_network
FRONT_NET        = adept_frontend_network
CONTAINER_PYTEST = /app/.venv/bin/pytest
SRC_MOUNT        = -v "$(CURDIR)/src":/app/src:ro
TEST_MOUNT       = -v "$(CURDIR)/tests":/app/tests:ro
TOML_MOUNT       = -v "$(CURDIR)/pyproject.toml":/app/pyproject.toml:ro

# ROPC password auth env vars for container-based UAT through nginx.
# notebook-user password comes from .env (NOTEBOOK_USER_PASSWORD).
# Override with: make test-uat-container ADEPT_UAT_PASSWORD=<password>
ADEPT_UAT_PASSWORD ?= notebook-password
CONTAINER_UAT_ENV  = \
	-e ADEPT_TEST_BASE_URL="https://nginx_proxy/v1" \
	-e ADEPT_BASE_URL="https://nginx_proxy/v1" \
	-e ADEPT_AUTH_METHOD=password \
	-e ADEPT_USERNAME=notebook-user \
	-e ADEPT_PASSWORD="$(ADEPT_UAT_PASSWORD)" \
	-e ADEPT_KEYCLOAK_URL="http://keycloak:8180" \
	-e ADEPT_KEYCLOAK_CLIENT_ID=login-client \
	-e ADEPT_VERIFY_SSL=false

.PHONY: test test-unit test-integration test-e2e test-uat test-uat-container \
        test-stdio test-stdio-docker test-stdio-integration test-stdio-e2e \
        test-all test-all-with-container install logs-dir

## Create logs directory
logs-dir:
	@mkdir -p $(LOGDIR)

## Install package with test dependencies
install:
	pip install -e ".[claude,chatgpt,proxy,dev]"

# ---------------------------------------------------------------------------
# Host-mode targets (fast, local .venv)
# ---------------------------------------------------------------------------

## Run unit tests — no network, no ADEPT stack required
test-unit: logs-dir
	$(PYTEST) $(UNIT_ARGS) 2>&1 | tee $(LOGDIR)/unit_$(TIMESTAMP).log

## Run integration tests — requires running ADEPT stack, no LLM
test-integration: logs-dir
	$(PYTEST) $(INTEG_ARGS) 2>&1 | tee $(LOGDIR)/integration_$(TIMESTAMP).log

## Run E2E tests — requires running ADEPT stack + LLM inference
test-e2e: logs-dir
	$(PYTEST) $(E2E_ARGS) 2>&1 | tee $(LOGDIR)/e2e_$(TIMESTAMP).log

## Run UAT tests — host mode (localhost:8083, API key auth, no nginx)
test-uat: logs-dir
	$(PYTEST) $(UAT_ARGS) 2>&1 | tee $(LOGDIR)/uat_host_$(TIMESTAMP).log

## Run unit → integration → e2e → uat sequentially (default)
test: test-unit test-integration test-e2e test-uat

## Run STDIO transport tests — unit level (no Docker needed)
test-stdio: logs-dir
	$(PYTEST) tests/connectors/claude/test_stdio_transport.py -v --tb=short -m "not stdio_docker" 2>&1 | tee $(LOGDIR)/stdio_$(TIMESTAMP).log

## Run STDIO Docker tests — requires Docker, ADEPT network, deps-base image
test-stdio-docker: logs-dir
	$(PYTEST) tests/connectors/claude/test_stdio_transport.py -v --tb=short -m stdio_docker 2>&1 | tee $(LOGDIR)/stdio_docker_$(TIMESTAMP).log

## Run STDIO integration tests — requires Docker + running ADEPT stack (no LLM)
test-stdio-integration: logs-dir
	$(PYTEST) tests/connectors/claude/test_stdio_integration.py -v --tb=short -m stdio_integration 2>&1 | tee $(LOGDIR)/stdio_integration_$(TIMESTAMP).log

## Run STDIO E2E tests — requires Docker + running ADEPT stack + LLM inference
test-stdio-e2e: logs-dir
	$(PYTEST) tests/connectors/claude/test_stdio_e2e.py -v --tb=short -m stdio_e2e 2>&1 | tee $(LOGDIR)/stdio_e2e_$(TIMESTAMP).log

## Run all tiers including container-based UAT and STDIO tests
test-all: test-unit test-stdio test-stdio-docker test-stdio-integration test-integration test-e2e test-stdio-e2e test-uat test-uat-container

# ---------------------------------------------------------------------------
# Container-mode targets (validates nginx HTTPS path)
# ---------------------------------------------------------------------------
# Pattern: docker create (single network) → docker network connect (second
# network) → docker start -a (attach and capture output).
#
# Why this pattern:
#   - docker run only accepts one --network flag
#   - UAT needs both adept_application_network (Keycloak) and
#     adept_frontend_network (nginx_proxy)
#   - docker create + network connect + docker start solves this
#
# Why /app/.venv (not a custom venv):
#   - deps-base image ships with /app/.venv containing pytest, httpx,
#     pydantic-settings, fastmcp — everything needed for adept_connectors
#   - Creating a venv with --user flag fails because /.cache/pip is
#     not writable by appuser (UID 1200)
#   - PYTHONPATH=/app/src makes adept_connectors importable from the
#     read-only mount without pip install
# ---------------------------------------------------------------------------

## Run UAT through nginx HTTPS in a container (ROPC password auth, dual-network)
test-uat-container: logs-dir
	@echo "=== Container-based UAT through nginx HTTPS (ROPC password auth) ==="
	@LOGFILE="$(LOGDIR)/uat_container_nginx_$(TIMESTAMP).log"; \
	CID=$$(docker create \
	  --rm \
	  --network=$(APP_NET) \
	  $(SRC_MOUNT) $(TEST_MOUNT) $(TOML_MOUNT) \
	  $(CONTAINER_UAT_ENV) \
	  $(DEPS_IMAGE) /bin/bash -c \
	  'PYTHONPATH=/app/src:/app/tests $(CONTAINER_PYTEST) /app/tests/integration/test_uat.py -v --tb=short -m uat 2>&1' \
	) && \
	docker network connect $(FRONT_NET) "$$CID" && \
	docker start -a "$$CID" 2>&1 | tee "$$LOGFILE"; \
	echo "=== Log: $$LOGFILE ==="

# ---------------------------------------------------------------------------
# Convenience: run all tiers with container-based UAT and nohup
# ---------------------------------------------------------------------------

## Run all tiers in background with nohup (for unattended execution)
test-all-nohup: logs-dir
	@echo "=== All tiers (nohup, logs in $(LOGDIR)/) ==="
	nohup $(PYTEST) $(UNIT_ARGS) > $(LOGDIR)/unit_$(TIMESTAMP).log 2>&1 && \
	nohup $(PYTEST) $(INTEG_ARGS) > $(LOGDIR)/integration_$(TIMESTAMP).log 2>&1 && \
	nohup $(PYTEST) $(E2E_ARGS) > $(LOGDIR)/e2e_$(TIMESTAMP).log 2>&1 && \
	nohup $(PYTEST) $(UAT_ARGS) > $(LOGDIR)/uat_host_$(TIMESTAMP).log 2>&1 && \
	echo "=== All host-mode tiers complete. Logs in $(LOGDIR)/ ==="
