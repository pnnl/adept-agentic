# =============================================================================
# Makefile — Slurm HPC Example Stack for ADEPT
# =============================================================================
# Full lifecycle management for the Slurm cluster + MCP server.
#
# Quick start:  make setup
# Manual flow:  make build && make start && make bootstrap-jwt && make restart-mcp && make register-tools
# =============================================================================

# --- Configuration ---
CONTAINER_ENGINE ?= docker
COMPOSE_CMD = $(CONTAINER_ENGINE) compose -f docker-compose.yaml
PROJECT_ROOT := $(shell cd ../.. && pwd)
SLURM_VERSION ?= 25.11.2
ADMIN_USER ?= admin
ADMIN_PASS ?= admin

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
    elif [ -n "$$CONDA_PREFIX" ] && [ -x "$$CONDA_PREFIX/bin/agentic" ]; then \
        echo "$$CONDA_PREFIX/bin/agentic"; \
    elif conda_prefix=$$(conda env list 2>/dev/null | awk '/adept-session/{print $$NF}') && \
         [ -n "$$conda_prefix" ] && [ -x "$$conda_prefix/bin/agentic" ]; then \
        echo "$$conda_prefix/bin/agentic"; \
    elif command -v agentic >/dev/null 2>&1; then \
        echo "agentic"; \
    else \
        echo ""; \
    fi \
)

.PHONY: all setup build build-all build-backend build-mcp pull \
        build-no-cache build-backend-no-cache build-mcp-no-cache \
        start stop restart teardown rebuild rebuild-quick status logs health \
        start-backend stop-backend restart-backend rebuild-backend \
        start-mcp stop-mcp restart-mcp rebuild-mcp logs-mcp health-mcp \
        start-proxy stop-proxy restart-proxy logs-proxy health-proxy \
        start-spire stop-spire start-oidc stop-oidc start-secure bootstrap-spire \
        start-federation stop-federation bootstrap-federation \
        test-federation test-jwt-bridge nohup-test-federation \
        generate-certs generate-test-certs \
        bootstrap-jwt generate-schemas check-schemas register-tools deregister-tools verify-tools \
        validate-cluster validate-mcp validate-all \
        ensure-test-image ensure-log-dir \
        test-lint test-imports test-unit test-certs test-tls test-integration test-e2e \
        test-schema test-deployment test-mcp-client \
        test-spiffe test-identity-mapper test-globus test-security test-infrastructure-health validate-registration-lifecycle test-all \
        test-hpc-unit test-hpc-integration test-hpc-e2e test-hpc-cross-service test-hpc-agentic-e2e test-workspace-e2e test-hpc-all \
        nohup-test-all nohup-test-unit nohup-test-security nohup-test-integration nohup-test-deployment nohup-test-mcp-client \
        nohup-test-lint nohup-test-imports nohup-test-e2e \
        nohup-test-hpc-unit nohup-test-hpc-integration nohup-test-hpc-e2e nohup-test-hpc-cross-service nohup-test-hpc-agentic-e2e nohup-test-workspace-e2e nohup-test-hpc-all \
        check-prerequisites init-network init-env init-dirs preflight help

# =============================================================================
# Convenience Targets
# =============================================================================

all: help

## Full end-to-end setup: preflight, build, start, bootstrap JWT, register tools
setup: preflight build start wait-healthy bootstrap-jwt restart-mcp register-tools verify-tools
	@echo -e "$(GREEN)=== Slurm HPC stack fully operational ===$(NC)"

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
		echo -e "$(GREEN).env created — edit as needed$(NC)"; \
	fi

## Create required host directories
init-dirs:
	@mkdir -p $(PROJECT_ROOT)/data/slurm_workspace

## Full pre-flight: prerequisites, directories, env, network
preflight: check-prerequisites init-dirs init-env init-network
	@echo -e "$(GREEN)Pre-flight complete$(NC)"

# =============================================================================
# Build Targets
# =============================================================================

## Build Slurm backend image only (slurm-hpc:SLURM_VERSION)
build-backend: init-network
	@echo -e "$(YELLOW)Building Slurm backend image ($(SLURM_VERSION))...$(NC)"
	$(COMPOSE_CMD) build slurmdbd
	@echo -e "$(GREEN)Backend image built$(NC)"

## Build Slurm MCP server image only (slurm-mcp:latest)
build-mcp: init-network
	@echo -e "$(YELLOW)Building Slurm MCP server image...$(NC)"
	$(COMPOSE_CMD) build slurm_mcp_server
	@echo -e "$(GREEN)MCP server image built$(NC)"

## Pull external images (mariadb, nginx)
pull:
	@echo -e "$(YELLOW)Pulling external images...$(NC)"
	$(CONTAINER_ENGINE) pull mariadb:11
	$(CONTAINER_ENGINE) pull nginx:alpine
	@echo -e "$(GREEN)External images pulled$(NC)"

## Build all custom images (backend + MCP server)
build: build-backend build-mcp
	@echo -e "$(GREEN)All images built$(NC)"

## Build all + pull external images
build-all: pull build
	@echo -e "$(GREEN)All images ready$(NC)"

## Build all images without cache
build-no-cache: init-network
	$(COMPOSE_CMD) build --no-cache slurmdbd
	$(COMPOSE_CMD) build --no-cache slurm_mcp_server

## Build backend image without cache
build-backend-no-cache: init-network
	$(COMPOSE_CMD) build --no-cache slurmdbd

## Build MCP server image without cache
build-mcp-no-cache: init-network
	$(COMPOSE_CMD) build --no-cache slurm_mcp_server

## Build Apptainer SIF image locally (for agent-driven upload to HPC clusters)
## Output: $(PROJECT_ROOT)/data/containers/adept-cobrapy.sif
## Uses quay.io/singularity/singularity:v4.1.0 (pre-pulled on RC host)
build-sif:
	@echo -e "$(GREEN)Building adept-cobrapy.sif locally...$(NC)"
	@mkdir -p $(PROJECT_ROOT)/data/containers
	$(CONTAINER_ENGINE) run --rm --privileged \
		-v $(PWD)/demos/apptainer:/build:ro \
		-v $(PROJECT_ROOT)/data/containers:/output \
		-w /build \
		quay.io/singularity/singularity:v4.1.0 \
		build /output/adept-cobrapy.sif /build/cobrapy.def
	@echo -e "$(GREEN)SIF built:$(NC)"
	@ls -lh $(PROJECT_ROOT)/data/containers/adept-cobrapy.sif

## Force-rebuild SIF (removes cached image first)
build-sif-no-cache:
	@rm -f $(PROJECT_ROOT)/data/containers/adept-cobrapy.sif
	$(MAKE) build-sif

# =============================================================================
# Lifecycle Targets
# =============================================================================

## Start all services
start: init-dirs init-network
	@echo -e "$(YELLOW)Starting Slurm HPC stack...$(NC)"
	$(COMPOSE_CMD) up -d
	@echo -e "$(GREEN)All services started$(NC)"

## Stop all services
stop:
	$(COMPOSE_CMD) stop

## Restart all services
restart: stop start

## Full rebuild (no cache) with re-registration (aligned with biofoundation/vfm)
rebuild: stop build-no-cache start wait-healthy deregister-tools register-tools verify-tools
	@echo -e "$(GREEN)DONE: Slurm HPC stack rebuilt and re-registered$(NC)"

## Quick rebuild with cache (code-only changes)
rebuild-quick: stop build start wait-healthy
	@echo -e "$(GREEN)DONE: Slurm HPC stack rebuilt (cached) and restarted$(NC)"
	@echo "  Next: make deregister-tools && make register-tools && make verify-tools"

## Full teardown (containers, networks, volumes) — deregisters tools first
teardown: deregister-tools
	@echo -e "$(RED)Tearing down Slurm HPC stack (all data will be lost)...$(NC)"
	$(COMPOSE_CMD) down -v --remove-orphans

## Show service status
status:
	$(COMPOSE_CMD) ps

## Show logs for all services
logs:
	$(COMPOSE_CMD) logs --tail=50

## Show service health
health:
	@echo "=== Service Health ==="
	@$(CONTAINER_ENGINE) inspect --format='{{.Name}}: {{.State.Health.Status}}' \
		slurm_mysql slurmctld slurm_mcp_server slurm_nginx_proxy 2>/dev/null || \
		echo "Some containers not running"

## Wait for slurmctld to be healthy
wait-healthy:
	@echo -e "$(YELLOW)Waiting for Slurm cluster to be healthy...$(NC)"
	@MAX_WAIT=180; WAITED=0; \
	while ! $(CONTAINER_ENGINE) exec slurmctld scontrol ping 2>/dev/null | grep -q "UP"; do \
		if [ "$$WAITED" -ge "$$MAX_WAIT" ]; then \
			echo -e "$(RED)ERROR: slurmctld not healthy after $${MAX_WAIT}s$(NC)"; \
			exit 1; \
		fi; \
		sleep 3; \
		WAITED=$$((WAITED + 3)); \
		echo "  Waiting... ($${WAITED}s)"; \
	done
	@echo -e "$(GREEN)Slurm cluster is healthy$(NC)"

# =============================================================================
# Per-Service Targets
# =============================================================================

# --- Backend (mysql, slurmdbd, slurmctld, slurmrestd, c1, c2) ---
start-backend:
	$(COMPOSE_CMD) up -d mysql slurmdbd slurmctld slurmrestd c1 c2

stop-backend:
	$(COMPOSE_CMD) stop mysql slurmdbd slurmctld slurmrestd c1 c2

restart-backend: stop-backend start-backend

# --- MCP Server ---
start-mcp:
	$(COMPOSE_CMD) up -d slurm_mcp_server

stop-mcp:
	$(COMPOSE_CMD) stop slurm_mcp_server

## Restart MCP server (needed after bootstrap-jwt to pick up credentials)
restart-mcp:
	@echo -e "$(YELLOW)Restarting Slurm MCP server with JWT credentials...$(NC)"
	$(COMPOSE_CMD) stop slurm_mcp_server
	$(COMPOSE_CMD) up -d slurm_mcp_server
	@echo -e "$(GREEN)MCP server restarted$(NC)"

rebuild-mcp:
	$(COMPOSE_CMD) stop slurm_mcp_server
	$(COMPOSE_CMD) build slurm_mcp_server
	$(COMPOSE_CMD) up -d slurm_mcp_server

## Rebuild + restart backend services
rebuild-backend:
	$(COMPOSE_CMD) stop mysql slurmdbd slurmctld slurmrestd c1 c2
	$(COMPOSE_CMD) build slurmdbd
	$(COMPOSE_CMD) up -d mysql slurmdbd slurmctld slurmrestd c1 c2

logs-mcp:
	$(COMPOSE_CMD) logs --tail=50 -f slurm_mcp_server

health-mcp:
	@$(CONTAINER_ENGINE) exec slurm_mcp_server curl -sf http://localhost:8002/health && echo " MCP: healthy" || echo " MCP: unhealthy"

# --- Nginx Proxy ---
start-proxy:
	$(COMPOSE_CMD) up -d slurm_nginx_proxy

stop-proxy:
	$(COMPOSE_CMD) stop slurm_nginx_proxy

restart-proxy: stop-proxy start-proxy

logs-proxy:
	$(COMPOSE_CMD) logs --tail=50 -f slurm_nginx_proxy

health-proxy:
	@curl -sf http://localhost:$${SLURM_PROXY_PORT:-9820}/health >/dev/null && echo " Proxy HTTP: healthy" || echo " Proxy HTTP: unhealthy"
	@if [ -f certs/ca.crt ]; then \
		curl -sf --cacert certs/ca.crt https://localhost:$${SLURM_PROXY_HTTPS_PORT:-9821}/health >/dev/null && \
		echo " Proxy HTTPS: healthy" || \
		echo " Proxy HTTPS: not responding"; \
	else \
		echo " Proxy HTTPS: skipped (no certs/ca.crt)"; \
	fi

# =============================================================================
# TLS / HTTPS
# =============================================================================

## Generate CA + server certificates for TLS (requires SLURM_HOST_IP)
generate-certs:
	@echo -e "$(YELLOW)Generating CA + server certificates...$(NC)"
	@bash scripts/generate-ca-and-certs.sh
	@echo -e "$(GREEN)Certs generated in certs/$(NC)"
	@echo -e "$(GREEN)For cross-host: copy certs/ca.crt to ADEPT host at examples/slurm_hpc/certs/ca.crt$(NC)"

## Generate self-signed test certificates (no SLURM_HOST_IP required)
generate-test-certs:
	@echo -e "$(YELLOW)Generating self-signed test certificates...$(NC)"
	@bash scripts/generate-test-certs.sh certs
	@echo -e "$(GREEN)Done.$(NC)"

# =============================================================================
# Bootstrap & Registration
# =============================================================================

## Extract HMAC key from Slurm cluster and generate service JWT
bootstrap-jwt:
	@echo -e "$(YELLOW)Bootstrapping JWT credentials...$(NC)"
	./scripts/bootstrap-jwt.sh

## Generate tool_registry.json from FastMCP introspection
generate-schemas:
	@echo -e "$(YELLOW)Generating tool_registry.json from FastMCP introspection...$(NC)"
	python3 scripts/generate-registration-schemas.py

## Check for schema drift between tool_registry.json and live MCP app
check-schemas:
	@python3 scripts/generate-registration-schemas.py --check

## Register Slurm tools with ADEPT gateway (reads from tool_registry.json)
register-tools: generate-schemas
	@echo -e "$(YELLOW)Registering Slurm tools with ADEPT...$(NC)"
	./scripts/register-slurm-tools.sh register

## Remove Slurm tools from ADEPT gateway
deregister-tools:
	./scripts/register-slurm-tools.sh deregister

## Verify tool registration in Redis
verify-tools:
	./scripts/register-slurm-tools.sh verify

# =============================================================================
# Validation Targets
# =============================================================================

## Validate Slurm backend cluster
validate-cluster:
	@echo -e "$(YELLOW)=== Validating Slurm Cluster ===$(NC)"
	@echo "--- Checking containers ---"
	@$(CONTAINER_ENGINE) ps --format "table {{.Names}}\t{{.Status}}" | grep -E "slurm_mysql|slurmdbd|slurmctld|slurmrestd|^c[12]" || echo "Some containers not running"
	@echo ""
	@echo "--- Munge auth test ---"
	@$(CONTAINER_ENGINE) exec slurmctld munge -n | $(CONTAINER_ENGINE) exec -i slurmdbd unmunge >/dev/null 2>&1 && echo "  Munge: OK" || echo "  Munge: FAILED"
	@echo ""
	@echo "--- Slurmctld ping ---"
	@$(CONTAINER_ENGINE) exec slurmctld scontrol ping
	@echo ""
	@echo "--- Node status ---"
	@$(CONTAINER_ENGINE) exec slurmctld scontrol show nodes | head -20
	@echo ""
	@echo "--- Test job submission ---"
	@$(CONTAINER_ENGINE) exec slurmctld bash -c 'echo "#!/bin/bash\nhostname\ndate" | sbatch --job-name=test --output=/data/test_%j.out --wrap="hostname && date"' 2>/dev/null && echo "  Job submitted successfully" || echo "  Job submission: manual test needed"
	@echo ""
	@echo -e "$(GREEN)=== Cluster validation complete ===$(NC)"

## Validate MCP server
validate-mcp:
	@echo -e "$(YELLOW)=== Validating Slurm MCP Server ===$(NC)"
	@echo "--- Health check ---"
	@curl -sf http://localhost:8002/health && echo "" && echo "  MCP health: OK" || echo "  MCP health: FAILED (is it running?)"
	@echo ""
	@echo "--- Proxy health check ---"
	@curl -sf http://localhost:9820/health && echo "" && echo "  Proxy health: OK" || echo "  Proxy health: FAILED"
	@echo ""
	@echo -e "$(GREEN)=== MCP validation complete ===$(NC)"

## Run all validation
validate-all: validate-cluster validate-mcp verify-tools
	@echo -e "$(GREEN)=== All validations complete ===$(NC)"

# =============================================================================
# Test Targets (pytest-based)
# =============================================================================

# Docker image for running tests (uses MCP server image which has all deps)
TEST_IMAGE = slurm-mcp:latest
# Override ENTRYPOINT (default is python -m slurm_mcp) so we can run pytest
TEST_RUN = $(CONTAINER_ENGINE) run --rm --entrypoint python

# DRY test variables (aligned with biofoundation/vfm/academy patterns)
TEST_VOLS = -v "$(shell pwd)/slurm_mcp_server":/app/slurm_mcp_server:ro \
            -v "$(shell pwd)/tests":/app/tests:ro \
            -v "$(shell pwd)/scripts":/app/scripts:ro
TEST_ENV  = -w /app -e PYTHONPATH=/app/slurm_mcp_server -e HOME=/tmp
NET_APP   = --network=adept_application_network
TEST_SVC_ENV = -e SLURM_MCP_URL=http://slurm_mcp_server:8002 \
               -e SLURM_PROXY_URL=http://slurm_nginx_proxy:80

# Composed commands (offline vs network)
TEST_RUN_OFFLINE = $(TEST_RUN) $(TEST_VOLS) $(TEST_ENV)
TEST_RUN_NET     = $(TEST_RUN) $(NET_APP) $(TEST_VOLS) $(TEST_ENV) $(TEST_SVC_ENV)

# Log directory for nohup runners
LOG_DIR = $(shell pwd)/logs
TIMESTAMP = $(shell date +%Y%m%d_%H%M%S)
ensure-log-dir:
	@mkdir -p $(LOG_DIR)

## Ensure the test image (slurm-mcp:latest) exists, build if missing
ensure-test-image:
	@$(CONTAINER_ENGINE) image inspect $(TEST_IMAGE) >/dev/null 2>&1 || { \
		echo -e "$(YELLOW)Test image $(TEST_IMAGE) not found — building...$(NC)"; \
		$(MAKE) build-mcp; \
	}

## Run linting and code quality tests (no services needed)
test-lint: ensure-test-image
	@echo -e "$(YELLOW)=== Running lint tests ===$(NC)"
	$(TEST_RUN) \
		-v "$(shell pwd)/slurm_mcp_server":/app/slurm_mcp_server:ro \
		-v "$(shell pwd)/tests":/app/tests:ro \
		-w /app \
		-e PYTHONPATH=/app/slurm_mcp_server \
		$(TEST_IMAGE) \
		-m pytest tests/test_lint.py -v --tb=short
	@echo -e "$(GREEN)=== Lint tests complete ===$(NC)"

## Run module import tests (no services needed)
test-imports: ensure-test-image
	@echo -e "$(YELLOW)=== Running import tests ===$(NC)"
	$(TEST_RUN) \
		-v "$(shell pwd)/slurm_mcp_server":/app/slurm_mcp_server:ro \
		-v "$(shell pwd)/tests":/app/tests:ro \
		-w /app \
		-e PYTHONPATH=/app/slurm_mcp_server \
		$(TEST_IMAGE) \
		-m pytest tests/test_imports.py -v --tb=short
	@echo -e "$(GREEN)=== Import tests complete ===$(NC)"

## Run unit tests (no services needed)
test-unit: ensure-test-image
	@echo -e "$(YELLOW)=== Running unit tests ===$(NC)"
	$(TEST_RUN) \
		-v "$(shell pwd)/slurm_mcp_server":/app/slurm_mcp_server:ro \
		-v "$(shell pwd)/tests":/app/tests:ro \
		-v "$(shell pwd)/scripts":/app/scripts:ro \
		-w /app \
		-e PYTHONPATH=/app/slurm_mcp_server \
		$(TEST_IMAGE) \
		-m pytest tests/unit/ -v --tb=short
	@echo -e "$(GREEN)=== Unit tests complete ===$(NC)"

## Run integration tests (requires MCP server running)
test-integration: ensure-test-image init-network
	@echo -e "$(YELLOW)=== Running integration tests ===$(NC)"
	$(TEST_RUN) \
		--network=adept_application_network \
		--user $(shell id -u):$(shell id -g) \
		--group-add $(shell stat -c '%g' /var/run/docker.sock) \
		-v /etc/passwd:/etc/passwd:ro \
		-v /var/run/docker.sock:/var/run/docker.sock \
		-v "$(shell pwd)/ssh_keys":/app/.ssh:ro \
		-v "$(shell pwd)/slurm_mcp_server":/app/slurm_mcp_server:ro \
		-v "$(shell pwd)/tests":/app/tests:ro \
		-w /app \
		-e HOME=/tmp \
		-e PYTHONPATH=/app/slurm_mcp_server \
		-e SLURM_MCP_URL=http://slurm_mcp_server:8002 \
		-e SLURM_PROXY_URL=http://slurm_nginx_proxy:80 \
		-e SLURM_MCP_RUNNING=1 \
		-e SLURM_CLUSTER_RUNNING=1 \
		-e TAHOMA_PASSWORD=$(TAHOMA_PASSWORD) \
		-e SHARED_UPLOAD_DIR=/tmp/shared_uploads \
		$(TEST_IMAGE) \
		-m pytest tests/integration/ -v --tb=short -p no:cacheprovider
	@echo -e "$(GREEN)=== Integration tests complete ===$(NC)"

## Run E2E tests (requires full stack running + Docker socket for cluster health tests)
test-e2e: ensure-test-image init-network
	@echo -e "$(YELLOW)=== Running E2E tests ===$(NC)"
	$(TEST_RUN) \
		--network=adept_application_network \
		--group-add $(shell stat -c '%g' /var/run/docker.sock) \
		-v /var/run/docker.sock:/var/run/docker.sock \
		-v "$(shell pwd)/slurm_mcp_server":/app/slurm_mcp_server:ro \
		-v "$(shell pwd)/tests":/app/tests:ro \
		-w /app \
		-e PYTHONPATH=/app/slurm_mcp_server \
		-e SLURM_MCP_URL=http://slurm_mcp_server:8002 \
		-e SLURM_PROXY_URL=http://slurm_nginx_proxy:80 \
		-e SLURM_CLUSTER_RUNNING=1 \
		$(TEST_IMAGE) \
		-m pytest tests/test_slurm_mcp_e2e.py -v --tb=short
	@echo -e "$(GREEN)=== E2E tests complete ===$(NC)"

## Run certificate generation tests (no services needed, requires openssl + bash)
test-certs: ensure-test-image
	@echo -e "$(YELLOW)=== Running certificate generation tests ===$(NC)"
	$(TEST_RUN) \
		-v "$(shell pwd)/slurm_mcp_server":/app/slurm_mcp_server:ro \
		-v "$(shell pwd)/tests":/app/tests:ro \
		-v "$(shell pwd)/scripts":/app/scripts:ro \
		-w /app \
		-e PYTHONPATH=/app/slurm_mcp_server \
		$(TEST_IMAGE) \
		-m pytest tests/unit/test_generate_certs.py -v --tb=short
	@echo -e "$(GREEN)=== Certificate tests complete ===$(NC)"

## Run schema discovery tests (no services needed — validates @app.tool registration)
test-schema: ensure-test-image
	@echo -e "$(YELLOW)=== Running schema discovery tests ===$(NC)"
	$(TEST_RUN_OFFLINE) \
		$(TEST_IMAGE) \
		-m pytest tests/test_schema_discovery.py -v --tb=short
	@echo -e "$(GREEN)=== Schema discovery tests complete ===$(NC)"

## Run deployment health tests (requires MCP server running)
test-deployment: ensure-test-image init-network
	@echo -e "$(YELLOW)=== Running deployment health tests ===$(NC)"
	$(TEST_RUN_NET) \
		-e SLURM_MCP_RUNNING=1 \
		$(TEST_IMAGE) \
		-m pytest tests/test_slurm_deployment.py -v --tb=short
	@echo -e "$(GREEN)=== Deployment health tests complete ===$(NC)"

## Run MCP client protocol tests using official FastMCP Client (requires MCP server running)
test-mcp-client: ensure-test-image init-network
	@echo -e "$(YELLOW)=== Running MCP client protocol tests ===$(NC)"
	$(CONTAINER_ENGINE) run --rm --entrypoint /bin/sh \
		$(NET_APP) $(TEST_VOLS) $(TEST_ENV) $(TEST_SVC_ENV) \
		-e SLURM_MCP_RUNNING=1 \
		$(TEST_IMAGE) \
		-c "pip install -q pytest-asyncio 2>/dev/null && python -m pytest tests/test_mcp_client_protocol.py -v --tb=short"
	@echo -e "$(GREEN)=== MCP client protocol tests complete ===$(NC)"

nohup-test-mcp-client: ensure-test-image ensure-log-dir
	@echo -e "$(YELLOW)Starting MCP client tests in background...$(NC)"
	@nohup $(MAKE) test-mcp-client > $(LOG_DIR)/test_mcp_client_$(TIMESTAMP).log 2>&1 &
	@echo -e "$(GREEN)Log: $(LOG_DIR)/test_mcp_client_$(TIMESTAMP).log$(NC)"

## Run TLS proxy integration tests (requires stack + certs)
test-tls: ensure-test-image init-network generate-test-certs
	@echo -e "$(YELLOW)=== Restarting nginx proxy to pick up TLS certs ===$(NC)"
	@docker restart slurm_nginx_proxy >/dev/null 2>&1 && sleep 2 || true
	@echo -e "$(YELLOW)=== Running TLS proxy tests ===$(NC)"
	$(TEST_RUN) \
		--network=adept_application_network \
		--group-add $(shell stat -c '%g' /var/run/docker.sock) \
		-v /var/run/docker.sock:/var/run/docker.sock \
		-v "$(shell pwd)/slurm_mcp_server":/app/slurm_mcp_server:ro \
		-v "$(shell pwd)/tests":/app/tests:ro \
		-v "$(shell pwd)/certs":/app/certs:ro \
		-w /app \
		-e PYTHONPATH=/app/slurm_mcp_server \
		-e SLURM_PROXY_URL=http://slurm_nginx_proxy:80 \
		-e SLURM_PROXY_HTTPS_URL=https://slurm_nginx_proxy:443 \
		-e SLURM_CA_CERT=/app/certs/ca.crt \
		$(TEST_IMAGE) \
		-m pytest tests/integration/test_tls_proxy.py -v --tb=short
	@echo -e "$(GREEN)=== TLS proxy tests complete ===$(NC)"

## Run SPIFFE auth unit tests (no services needed)
test-spiffe: ensure-test-image
	@echo -e "$(YELLOW)=== Running SPIFFE auth tests ===$(NC)"
	$(TEST_RUN_OFFLINE) \
		$(TEST_IMAGE) \
		-m pytest tests/unit/test_spiffe_auth.py -v --tb=short
	@echo -e "$(GREEN)=== SPIFFE auth tests complete ===$(NC)"

## Run identity mapper unit tests (no services needed)
test-identity-mapper: ensure-test-image
	@echo -e "$(YELLOW)=== Running identity mapper tests ===$(NC)"
	$(TEST_RUN_OFFLINE) \
		$(TEST_IMAGE) \
		-m pytest tests/unit/test_identity_mapper.py -v --tb=short
	@echo -e "$(GREEN)=== Identity mapper tests complete ===$(NC)"

## Run Globus token exchange unit tests (no services needed, needs core src)
test-globus: ensure-test-image
	@echo -e "$(YELLOW)=== Running Globus token exchange tests ===$(NC)"
	$(TEST_RUN) \
		$(TEST_VOLS) \
		-v "$(PROJECT_ROOT)/src":/app/src:ro \
		-w /app -e PYTHONPATH=/app/slurm_mcp_server:/app/src -e HOME=/tmp \
		-e GLOBUS_ENABLED=false \
		$(TEST_IMAGE) \
		-m pytest tests/unit/test_globus_token_exchange.py -v --tb=short
	@echo -e "$(GREEN)=== Globus token exchange tests complete ===$(NC)"

## Run all security integration tests (SPIFFE + identity mapper + Globus)
test-security: test-spiffe test-identity-mapper test-globus
	@echo -e "$(GREEN)=== All security unit tests passed ===$(NC)"

## Infrastructure health: tool visibility in ADEPT core Redis (dual-network: app + data)
## Slurm HPC has no own Redis — only validates tools are registered in ADEPT core
test-infrastructure-health: ensure-test-image
	@echo -e "$(YELLOW)=== Running infrastructure health tests (dual-network) ===$(NC)"
	@CID=$$($(CONTAINER_ENGINE) create --rm \
		$(NET_APP) $(TEST_VOLS) $(TEST_ENV) $(TEST_SVC_ENV) \
		--entrypoint python $(TEST_IMAGE) \
		-m pytest tests/test_infrastructure_health.py -v --tb=short) && \
	$(CONTAINER_ENGINE) network connect adept_data_network $$CID 2>/dev/null; \
	$(CONTAINER_ENGINE) start -a $$CID
	@echo -e "$(GREEN)=== Infrastructure health tests complete ===$(NC)"

## Full registration lifecycle validation (9-step: health → deregister → register → verify → E2E)
validate-registration-lifecycle:
	@$(PROJECT_ROOT)/scripts/diagnostics/test_tool_registration_lifecycle.sh \
		--stack slurm_hpc \
		--container slurm_mcp_server \
		--health-port 8002 \
		--tool-count 27 \
		--tools "slurm_hpc_submit_job,slurm_hpc_get_job_details,slurm_hpc_cancel_job,slurm_hpc_ping,slurm_hpc_list_jobs,slurm_hpc_cluster_summary,slurm_hpc_deception_ping,slurm_hpc_deception_submit_job,slurm_hpc_deception_get_job_details,slurm_hpc_deception_cancel_job,slurm_hpc_deception_list_jobs,slurm_hpc_deception_get_cluster_summary,slurm_hpc_tahoma_ping,slurm_hpc_tahoma_submit_job,slurm_hpc_tahoma_get_job_details,slurm_hpc_tahoma_cancel_job,slurm_hpc_tahoma_list_jobs,slurm_hpc_tahoma_get_cluster_summary,slurm_hpc_hpc_list_clusters,slurm_hpc_hpc_check_ssh_key,slurm_hpc_hpc_generate_ssh_key,slurm_hpc_hpc_test_ssh_connectivity,slurm_hpc_hpc_get_provisioning_instructions,slurm_hpc_workspace_list_files,slurm_hpc_workspace_upload_file,slurm_hpc_workspace_download_file,slurm_hpc_workspace_read_file" \
		--register-cmd "./scripts/register-slurm-tools.sh register" \
		--deregister-cmd "./scripts/register-slurm-tools.sh deregister" \
		--stack-dir examples/slurm_hpc

## Run all tests (lint + imports + unit + certs + schema + security + federation)
test-all: test-lint test-imports test-unit test-certs test-schema test-security test-federation
	@echo -e "$(GREEN)=== All offline tests passed ===$(NC)"
	@echo -e "$(YELLOW)For integration/E2E tests, run: make test-integration test-e2e test-tls$(NC)"

# =============================================================================
# SPIFFE/OIDC Profile Targets
# =============================================================================

## Start with SPIRE workload identity (SPIFFE/SPIRE sidecar)
start-spire:
	$(COMPOSE_CMD) --profile spire up -d slurm_spire_server slurm_spire_agent
	@echo -e "$(GREEN)SPIRE services started. Run: ./scripts/bootstrap-spire.sh$(NC)"

## Stop SPIRE services
stop-spire:
	$(COMPOSE_CMD) --profile spire stop slurm_spire_server slurm_spire_agent

## Start with OIDC authentication (oauth2_proxy + Keycloak)
start-oidc:
	$(COMPOSE_CMD) --profile oidc up -d slurm_oauth2_proxy
	@echo -e "$(GREEN)oauth2_proxy started. Set SLURM_OIDC_ENABLED=true and restart proxy.$(NC)"

## Stop OIDC services
stop-oidc:
	$(COMPOSE_CMD) --profile oidc stop slurm_oauth2_proxy

## Start with all security layers (SPIRE + OIDC)
start-secure: start start-spire start-oidc
	@echo -e "$(GREEN)Full secure stack started (SPIRE + OIDC)$(NC)"

## Bootstrap SPIRE (generate join token + register workload entries)
bootstrap-spire:
	./scripts/bootstrap-spire.sh

## Start federation (ADEPT SPIRE server + agent for pnnl.adept trust domain)
start-federation: start-spire
	$(COMPOSE_CMD) --profile federation up -d adept_spire_server adept_spire_agent
	@echo -e "$(GREEN)Federation services started. Run: make bootstrap-federation$(NC)"

## Stop federation services
stop-federation:
	$(COMPOSE_CMD) --profile federation stop adept_spire_server adept_spire_agent

## Bootstrap trust bundle federation (bidirectional pnnl.adept <-> pnnl.adept.slurm)
bootstrap-federation: bootstrap-spire
	./scripts/bootstrap-federation.sh

## Run federation unit tests (offline — config validation + JWT bridge)
## Note: federation config tests need spire/ scripts/ docker-compose.yaml mounted
test-federation: ensure-test-image
	@echo -e "$(YELLOW)=== Running federation tests ===$(NC)"
	$(TEST_RUN) \
		$(TEST_VOLS) \
		-v "$(shell pwd)/spire":/app/spire:ro \
		-v "$(shell pwd)/scripts":/app/scripts:ro \
		-v "$(shell pwd)/docker-compose.yaml":/app/docker-compose.yaml:ro \
		$(TEST_ENV) \
		$(TEST_IMAGE) \
		-m pytest tests/unit/test_jwt_bridge.py tests/unit/test_federation_config.py -v --tb=short
	@echo -e "$(GREEN)=== Federation tests complete ===$(NC)"

## Run JWT bridge unit tests (offline)
test-jwt-bridge: ensure-test-image
	@echo -e "$(YELLOW)=== Running JWT bridge tests ===$(NC)"
	$(TEST_RUN_OFFLINE) \
		$(TEST_IMAGE) \
		-m pytest tests/unit/test_jwt_bridge.py -v --tb=short
	@echo -e "$(GREEN)=== JWT bridge tests complete ===$(NC)"

nohup-test-federation: ensure-test-image ensure-log-dir
	@echo "Running federation tests in background → $(LOG_DIR)/test_federation_$(TIMESTAMP).log"
	@nohup $(MAKE) test-federation > $(LOG_DIR)/test_federation_$(TIMESTAMP).log 2>&1 &

# =============================================================================
# Nohup Test Runners (background execution with timestamped logs)
# =============================================================================
# HPC Cluster Tests (Deception + Tahoma)
# =============================================================================

## Run HPC transport and tool unit tests (offline, mocked Fabric)
test-hpc-unit: ensure-test-image
	@echo -e "$(YELLOW)=== Running HPC unit tests ===$(NC)"
	$(TEST_RUN) \
		-v "$(shell pwd)/slurm_mcp_server":/app/slurm_mcp_server:ro \
		-v "$(shell pwd)/tests":/app/tests:ro \
		-v "$(shell pwd)/pytest.ini":/app/pytest.ini:ro \
		-w /app \
		-e PYTHONPATH=/app/slurm_mcp_server \
		$(TEST_IMAGE) \
		-m pytest tests/unit/test_slurm_parsers.py tests/unit/test_fabric_transport.py \
			tests/unit/test_ssh_keys.py tests/unit/test_deception_tools.py \
			tests/unit/test_tahoma_tools.py tests/unit/test_tahoma_rest_transport.py \
			tests/unit/test_session_workspace.py tests/unit/test_workspace_tools.py -v --tb=short
	@echo -e "$(GREEN)=== HPC unit tests complete ===$(NC)"

## Run HPC SSH connectivity integration tests (requires PNNL network access)
test-hpc-integration: ensure-test-image
	@echo -e "$(YELLOW)=== Running HPC connectivity tests ===$(NC)"
	$(TEST_RUN) \
		-v "$(shell pwd)/slurm_mcp_server":/app/slurm_mcp_server:ro \
		-v "$(shell pwd)/tests":/app/tests:ro \
		-v "$(shell pwd)/pytest.ini":/app/pytest.ini:ro \
		-v "$(HOME)/.ssh":/home/testuser/.ssh:ro \
		-w /app \
		-e PYTHONPATH=/app/slurm_mcp_server \
		$(TEST_IMAGE) \
		-m pytest tests/integration/test_hpc_connectivity.py -v --tb=short
	@echo -e "$(GREEN)=== HPC connectivity tests complete ===$(NC)"

## Run HPC E2E job lifecycle tests (requires DECEPTION_E2E_ENABLED=true + network)
test-hpc-e2e: ensure-test-image init-network
	@echo -e "$(YELLOW)=== Running HPC E2E tests (opt-in) ===$(NC)"
	@echo -e "$(YELLOW)  Reachability: deception.pnl.gov$(NC)"
	@python3 -c "import socket; socket.create_connection(('deception.pnl.gov', 22), timeout=3); print('    REACHABLE')" 2>/dev/null || echo "    UNREACHABLE (tests will skip)"
	$(TEST_RUN) \
		--network=adept_application_network \
		--user $(shell id -u):$(shell id -g) \
		-v /etc/passwd:/etc/passwd:ro \
		-v "$(shell pwd)/slurm_mcp_server":/app/slurm_mcp_server:ro \
		-v "$(shell pwd)/tests":/app/tests:ro \
		-v "$(shell pwd)/pytest.ini":/app/pytest.ini:ro \
		-v "$(shell pwd)/ssh_keys":/app/.ssh:ro \
		-w /app \
		-e HOME=/tmp \
		-e PYTHONPATH=/app/slurm_mcp_server \
		-e DECEPTION_E2E_ENABLED=$(DECEPTION_E2E_ENABLED) \
		-e TAHOMA_E2E_ENABLED=$(TAHOMA_E2E_ENABLED) \
		-e TAHOMA_PASSWORD=$(TAHOMA_PASSWORD) \
		$(TEST_IMAGE) \
		-m pytest tests/e2e/test_deception_job_lifecycle.py -v --tb=short
	@echo -e "$(GREEN)=== HPC E2E tests complete ===$(NC)"

## Run workspace tools E2E tests (built-in + Deception + Tahoma, opt-in per cluster)
test-workspace-e2e: ensure-test-image init-network
	@echo -e "$(YELLOW)=== Running workspace tools E2E tests ===$(NC)"
	@echo -e "$(YELLOW)  Reachability: deception.pnl.gov$(NC)"
	@python3 -c "import socket; socket.create_connection(('deception.pnl.gov', 22), timeout=3); print('    REACHABLE')" 2>/dev/null || echo "    UNREACHABLE (Deception tests will skip)"
	@echo -e "$(YELLOW)  Reachability: tahoma.emsl.pnl.gov$(NC)"
	@python3 -c "import socket; socket.create_connection(('tahoma.emsl.pnl.gov', 22), timeout=3); print('    REACHABLE')" 2>/dev/null || echo "    UNREACHABLE (Tahoma tests will skip)"
	$(TEST_RUN) \
		--network=adept_application_network \
		--user $(shell id -u):$(shell id -g) \
		-v /etc/passwd:/etc/passwd:ro \
		-v /var/run/docker.sock:/var/run/docker.sock \
		--group-add $(shell stat -c '%g' /var/run/docker.sock) \
		-v "$(shell pwd)/slurm_mcp_server":/app/slurm_mcp_server:ro \
		-v "$(shell pwd)/tests":/app/tests:ro \
		-v "$(shell pwd)/pytest.ini":/app/pytest.ini:ro \
		-v "$(shell pwd)/ssh_keys":/app/.ssh:ro \
		-w /app \
		-e HOME=/tmp \
		-e PYTHONPATH=/app/slurm_mcp_server \
		-e SLURM_CLUSTER_RUNNING=$(SLURM_CLUSTER_RUNNING) \
		-e DECEPTION_E2E_ENABLED=$(DECEPTION_E2E_ENABLED) \
		-e TAHOMA_E2E_ENABLED=$(TAHOMA_E2E_ENABLED) \
		-e TAHOMA_PASSWORD=$(TAHOMA_PASSWORD) \
		-e SHARED_UPLOAD_DIR=/tmp/shared_uploads \
		$(TEST_IMAGE) \
		-m pytest tests/e2e/test_workspace_tools_e2e.py -v --tb=short
	@echo -e "$(GREEN)=== Workspace tools E2E tests complete ===$(NC)"

nohup-test-workspace-e2e: ensure-test-image ensure-log-dir
	@echo "Running workspace E2E tests in background → $(LOG_DIR)/test_workspace_e2e_$(TIMESTAMP).log"
	@nohup $(MAKE) test-workspace-e2e > $(LOG_DIR)/test_workspace_e2e_$(TIMESTAMP).log 2>&1 &
	@echo "PID: $$!"

## Run HPC cross-service E2E tests (requires local Slurm stack + CROSS_SERVICE_E2E_ENABLED=true)
test-hpc-cross-service: ensure-test-image init-network
	@echo -e "$(YELLOW)=== Running HPC cross-service E2E tests ===$(NC)"
	$(TEST_RUN) \
		--network slurm_backend_network \
		-v "$(shell pwd)/slurm_mcp_server":/app/slurm_mcp_server:ro \
		-v "$(shell pwd)/tests":/app/tests:ro \
		-v "$(shell pwd)/pytest.ini":/app/pytest.ini:ro \
		-v "$(PROJECT_ROOT)/data/slurm_workspace":/data \
		-w /app \
		-e PYTHONPATH=/app/slurm_mcp_server \
		-e SLURM_API_URL=$(SLURM_API_URL) \
		-e SLURM_SERVICE_JWT=$(SLURM_SERVICE_JWT) \
		-e SLURM_WORKSPACE=/data \
		-e CROSS_SERVICE_E2E_ENABLED=$(CROSS_SERVICE_E2E_ENABLED) \
		$(TEST_IMAGE) \
		-m pytest tests/e2e/test_cross_service_job_lifecycle.py -v --tb=short
	@echo -e "$(GREEN)=== HPC cross-service E2E tests complete ===$(NC)"

## Run agentic sandbox-to-Deception E2E (ADEPT gateway + LLM + SSH, requires AGENTIC_SANDBOX_DECEPTION_E2E=true)
## Requires: config/e2e_credentials.json (gitignored) + credentials mount for Keycloak client secret
ADEPT_CREDS_DIR ?= $(PROJECT_ROOT)/.env-keycloak-credentials-dir
test-hpc-agentic-e2e: ensure-test-image init-network
	@echo -e "$(YELLOW)=== Running agentic sandbox→Deception E2E tests ===$(NC)"
	$(TEST_RUN) \
		--network=adept_application_network \
		--user $(shell id -u):$(shell id -g) \
		-v /etc/passwd:/etc/passwd:ro \
		-v "$(shell pwd)/ssh_keys":/app/.ssh:ro \
		-v "$(shell pwd)/config":/app/config:ro \
		-v "$(shell pwd)/slurm_mcp_server":/app/slurm_mcp_server:ro \
		-v "$(shell pwd)/tests":/app/tests:ro \
		-v "$(shell pwd)/pytest.ini":/app/pytest.ini:ro \
		-v "$(ADEPT_CREDS_DIR)":/app/credentials:ro \
		-w /app \
		-e HOME=/tmp \
		-e PYTHONPATH=/app/slurm_mcp_server \
		-e AGENTIC_SANDBOX_DECEPTION_E2E=$(AGENTIC_SANDBOX_DECEPTION_E2E) \
		-e AGENT_GATEWAY_URL=http://agent_gateway:8081/v1 \
		-e KEYCLOAK_URL=http://keycloak:8180 \
		$(TEST_IMAGE) \
		-m pytest tests/e2e/test_agentic_sandbox_to_deception.py -v -s --tb=long --log-cli-level=INFO
	@echo -e "$(GREEN)=== Agentic sandbox→Deception E2E tests complete ===$(NC)"

nohup-test-hpc-agentic-e2e: ensure-test-image ensure-log-dir
	@echo "Running agentic E2E tests in background → $(LOG_DIR)/test_hpc_agentic_e2e_$(TIMESTAMP).log"
	@nohup $(MAKE) test-hpc-agentic-e2e > $(LOG_DIR)/test_hpc_agentic_e2e_$(TIMESTAMP).log 2>&1 &
	@echo "PID: $$!"

## Run all HPC tests: unit + integration + e2e + cross-service (auto-skip if unreachable)
test-hpc-all: test-hpc-unit test-hpc-integration test-hpc-e2e test-workspace-e2e test-hpc-cross-service
	@echo -e "$(GREEN)=== All HPC tests complete ===$(NC)"

nohup-test-hpc-unit: ensure-test-image ensure-log-dir
	@echo "Running HPC unit tests in background → $(LOG_DIR)/test_hpc_unit_$(TIMESTAMP).log"
	@nohup $(MAKE) test-hpc-unit > $(LOG_DIR)/test_hpc_unit_$(TIMESTAMP).log 2>&1 &
	@echo "PID: $$!"

nohup-test-hpc-integration: ensure-test-image ensure-log-dir
	@echo "Running HPC integration tests in background → $(LOG_DIR)/test_hpc_integration_$(TIMESTAMP).log"
	@nohup $(MAKE) test-hpc-integration > $(LOG_DIR)/test_hpc_integration_$(TIMESTAMP).log 2>&1 &
	@echo "PID: $$!"

nohup-test-hpc-e2e: ensure-test-image ensure-log-dir
	@echo "Running HPC E2E tests in background → $(LOG_DIR)/test_hpc_e2e_$(TIMESTAMP).log"
	@nohup $(MAKE) test-hpc-e2e > $(LOG_DIR)/test_hpc_e2e_$(TIMESTAMP).log 2>&1 &
	@echo "PID: $$!"

nohup-test-hpc-cross-service: ensure-test-image ensure-log-dir
	@echo "Running HPC cross-service E2E in background → $(LOG_DIR)/test_hpc_cross_service_$(TIMESTAMP).log"
	@nohup $(MAKE) test-hpc-cross-service > $(LOG_DIR)/test_hpc_cross_service_$(TIMESTAMP).log 2>&1 &
	@echo "PID: $$!"

nohup-test-hpc-all: ensure-test-image ensure-log-dir
	@echo "Running all HPC tests in background → $(LOG_DIR)/test_hpc_all_$(TIMESTAMP).log"
	@nohup $(MAKE) test-hpc-all > $(LOG_DIR)/test_hpc_all_$(TIMESTAMP).log 2>&1 &
	@echo "PID: $$!"

# =============================================================================
# Nohup Runners (Background)
# =============================================================================

nohup-test-all: ensure-test-image ensure-log-dir
	@echo "Running all offline tests in background → $(LOG_DIR)/test_all_$(TIMESTAMP).log"
	@nohup $(MAKE) test-all > $(LOG_DIR)/test_all_$(TIMESTAMP).log 2>&1 &
	@echo "PID: $$!"

nohup-test-unit: ensure-test-image ensure-log-dir
	@echo "Running unit tests in background → $(LOG_DIR)/test_unit_$(TIMESTAMP).log"
	@nohup $(MAKE) test-unit > $(LOG_DIR)/test_unit_$(TIMESTAMP).log 2>&1 &

nohup-test-security: ensure-test-image ensure-log-dir
	@echo "Running security tests in background → $(LOG_DIR)/test_security_$(TIMESTAMP).log"
	@nohup $(MAKE) test-security > $(LOG_DIR)/test_security_$(TIMESTAMP).log 2>&1 &

nohup-test-integration: ensure-test-image ensure-log-dir
	@echo "Running integration tests in background → $(LOG_DIR)/test_integration_$(TIMESTAMP).log"
	@nohup $(MAKE) test-integration > $(LOG_DIR)/test_integration_$(TIMESTAMP).log 2>&1 &

nohup-test-deployment: ensure-test-image ensure-log-dir
	@echo "Running deployment health tests in background → $(LOG_DIR)/test_deployment_$(TIMESTAMP).log"
	@nohup $(MAKE) test-deployment > $(LOG_DIR)/test_deployment_$(TIMESTAMP).log 2>&1 &

nohup-test-lint: ensure-test-image ensure-log-dir
	@echo "Running lint tests in background → $(LOG_DIR)/test_lint_$(TIMESTAMP).log"
	@nohup $(MAKE) test-lint > $(LOG_DIR)/test_lint_$(TIMESTAMP).log 2>&1 &
	@echo "PID: $$!"

nohup-test-imports: ensure-test-image ensure-log-dir
	@echo "Running import tests in background → $(LOG_DIR)/test_imports_$(TIMESTAMP).log"
	@nohup $(MAKE) test-imports > $(LOG_DIR)/test_imports_$(TIMESTAMP).log 2>&1 &
	@echo "PID: $$!"

nohup-test-e2e: ensure-test-image ensure-log-dir
	@echo "Running E2E tests in background → $(LOG_DIR)/test_e2e_$(TIMESTAMP).log"
	@nohup $(MAKE) test-e2e > $(LOG_DIR)/test_e2e_$(TIMESTAMP).log 2>&1 &
	@echo "PID: $$!"

# =============================================================================
# Agent-Driven Compute Lifecycle Demo
# =============================================================================

## Run full COBRApy/Gurobi lifecycle via ADEPT Responses API (agent-mediated)
perform-demo: ensure-log-dir
	@echo "$(GREEN)Starting ADEPT Compute Lifecycle Demo (agent-driven)$(NC)"
	@echo "  User:    $(or $(USER),rigo160)"
	@echo "  Model:   $(or $(MODEL),demos/models/simple_pathway.xml)"
	@echo "  Gateway: $(or $(GATEWAY_URL),http://localhost:8083)"
	@echo "  Timeout: $(or $(TIMEOUT),600)s"
	@echo ""
	python3 demos/perform_demo.py \
		--user "$(or $(USER),rigo160)" \
		$(if $(PASSWORD),--password "$(PASSWORD)",) \
		--model "$(or $(MODEL),demos/models/simple_pathway.xml)" \
		--gateway-url "$(or $(GATEWAY_URL),http://localhost:8083)" \
		--timeout "$(or $(TIMEOUT),600)" \
		2>&1 | tee $(LOG_DIR)/perform_demo_$(TIMESTAMP).log
	@echo ""
	@echo "$(GREEN)Log saved: $(LOG_DIR)/perform_demo_$(TIMESTAMP).log$(NC)"

## Run perform-demo in background with nohup
nohup-perform-demo: ensure-log-dir
	@echo "Running perform-demo in background → $(LOG_DIR)/perform_demo_$(TIMESTAMP).log"
	@nohup python3 demos/perform_demo.py \
		--user "$(or $(USER),rigo160)" \
		$(if $(PASSWORD),--password "$(PASSWORD)",) \
		--model "$(or $(MODEL),demos/models/simple_pathway.xml)" \
		--gateway-url "$(or $(GATEWAY_URL),http://localhost:8083)" \
		--timeout "$(or $(TIMEOUT),600)" \
		> $(LOG_DIR)/perform_demo_$(TIMESTAMP).log 2>&1 &
	@echo "PID: $$!"

## Post-run analysis: cross-reference Docker logs + Langfuse traces
analyze-demo: ensure-log-dir
	@echo "$(GREEN)Analyzing demo run (cross-referencing Docker + Langfuse)...$(NC)"
	python3 demos/analyze_demo_run.py \
		--since "$(or $(SINCE),60)" \
		--log-dir "$(LOG_DIR)" \
		--format "$(or $(FORMAT),text)" \
		2>&1 | tee $(LOG_DIR)/analyze_demo_$(TIMESTAMP).log

## Run v2 multi-agent demo (LLM-as-judge, 3 personas: executor/judge/observer)
perform-demo-v2: ensure-log-dir
	@echo "$(GREEN)Starting ADEPT Compute Lifecycle Demo v2 (multi-agent + LLM-as-judge)$(NC)"
	@echo "  User:    $(or $(USER),rigo160)"
	@echo "  Model:   $(or $(MODEL),demos/models/simple_pathway.xml)"
	@echo "  Gateway: $(or $(GATEWAY_URL),http://localhost:8083)"
	@echo "  Mode:    $(or $(MODE),auto)"
	@echo "  Timeout: $(or $(TIMEOUT),600)s"
	@echo ""
	python3 demos/perform_demo_v2.py \
		--user "$(or $(USER),rigo160)" \
		$(if $(PASSWORD),--password "$(PASSWORD)",) \
		--model "$(or $(MODEL),demos/models/simple_pathway.xml)" \
		--gateway-url "$(or $(GATEWAY_URL),http://localhost:8083)" \
		--timeout "$(or $(TIMEOUT),600)" \
		--mode "$(or $(MODE),auto)" \
		2>&1 | tee $(LOG_DIR)/perform_demo_v2_$(TIMESTAMP).log
	@echo ""
	@echo "$(GREEN)Log saved: $(LOG_DIR)/perform_demo_v2_$(TIMESTAMP).log$(NC)"

## Run perform-demo-v2 in background with nohup
nohup-perform-demo-v2: ensure-log-dir
	@echo "Running perform-demo-v2 in background → $(LOG_DIR)/perform_demo_v2_$(TIMESTAMP).log"
	@nohup python3 demos/perform_demo_v2.py \
		--user "$(or $(USER),rigo160)" \
		$(if $(PASSWORD),--password "$(PASSWORD)",) \
		--model "$(or $(MODEL),demos/models/simple_pathway.xml)" \
		--gateway-url "$(or $(GATEWAY_URL),http://localhost:8083)" \
		--timeout "$(or $(TIMEOUT),600)" \
		--mode "$(or $(MODE),auto)" \
		> $(LOG_DIR)/perform_demo_v2_$(TIMESTAMP).log 2>&1 &
	@echo "PID: $$!"

## Post-run analysis as JSON (for downstream tooling)
analyze-demo-json: ensure-log-dir
	python3 demos/analyze_demo_run.py \
		--since "$(or $(SINCE),60)" \
		--log-dir "$(LOG_DIR)" \
		--format json \
		> $(LOG_DIR)/analyze_demo_$(TIMESTAMP).json
	@echo "$(GREEN)JSON analysis saved: $(LOG_DIR)/analyze_demo_$(TIMESTAMP).json$(NC)"

# =============================================================================
# Help
# =============================================================================

## Show this help
help:
	@echo "Slurm HPC Example Stack for ADEPT"
	@echo ""
	@echo "Usage: make <target>"
	@echo ""
	@echo "Setup & Lifecycle:"
	@echo "  setup            Full end-to-end setup (preflight + build + start + bootstrap + register)"
	@echo "  preflight        Run all pre-flight checks (prerequisites + dirs + env + network)"
	@echo "  start            Start all services"
	@echo "  stop             Stop all services"
	@echo "  restart          Restart all services"
	@echo "  teardown         Remove everything (containers, volumes, networks)"
	@echo "  status           Show container status"
	@echo "  logs             Show recent logs"
	@echo "  health           Show service health"
	@echo ""
	@echo "Build:"
	@echo "  build            Build all custom images (backend + MCP server)"
	@echo "  build-all        Build all custom images + pull external images"
	@echo "  build-backend    Build Slurm backend image only"
	@echo "  build-mcp        Build MCP server image only"
	@echo "  pull             Pull external images (mariadb, nginx)"
	@echo "  build-sif        Build Apptainer SIF locally (for agent upload to HPC)"
	@echo "  build-no-cache         Rebuild all images without cache"
	@echo "  build-backend-no-cache Rebuild backend image without cache"
	@echo "  build-mcp-no-cache     Rebuild MCP server image without cache"
	@echo ""
	@echo "Per-Service:"
	@echo "  start-mcp        Start MCP server only"
	@echo "  restart-mcp      Restart MCP server (after bootstrap-jwt)"
	@echo "  rebuild-mcp      Rebuild + restart MCP server"
	@echo "  rebuild-backend  Rebuild + restart backend services"
	@echo "  logs-mcp         Follow MCP server logs"
	@echo "  health-mcp       Check MCP server health"
	@echo "  health-proxy     Check proxy health (HTTP + HTTPS if certs present)"
	@echo ""
	@echo "TLS / HTTPS:"
	@echo "  generate-certs   Generate CA + server certs (requires SLURM_HOST_IP)"
	@echo ""
	@echo "Bootstrap & Registration:"
	@echo "  bootstrap-jwt    Extract HMAC key + generate service JWT"
	@echo "  register-tools   Register 27 Slurm tools with ADEPT"
	@echo "  deregister-tools Remove Slurm tools from ADEPT"
	@echo "  verify-tools     Check tool registration in Redis"
	@echo ""
	@echo "Tests (Offline — no services needed):"
	@echo "  test-all         Run all offline tests (lint + imports + unit + certs + schema + security)"
	@echo "  test-lint        Run linting and code quality tests"
	@echo "  test-imports     Run module import tests"
	@echo "  test-unit        Run unit tests"
	@echo "  test-certs       Run certificate generation tests"
	@echo "  test-schema      Run MCP tool schema discovery tests"
	@echo "  test-spiffe      Run SPIFFE auth module tests"
	@echo "  test-identity-mapper  Run identity mapper tests"
	@echo "  test-globus      Run Globus token exchange tests"
	@echo "  test-security    Run all security tests (SPIFFE + identity + Globus)"
	@echo ""
	@echo "Infrastructure Health:"
	@echo "  test-infrastructure-health  Tool visibility in ADEPT core Redis (dual-network)"
	@echo "  validate-registration-lifecycle  Full 9-step registration lifecycle (live ADEPT)"
	@echo ""
	@echo "Tests (Online — requires running services):"
	@echo "  test-deployment   Run deployment health tests (requires MCP server)"
	@echo "  test-tls         Run TLS proxy tests (requires stack + certs)"
	@echo "  test-integration Run integration tests (requires MCP server running)"
	@echo "  test-e2e         Run E2E tests (requires full stack running)"
	@echo ""
	@echo "HPC Cluster Tests (Deception + Tahoma):"
	@echo "  test-hpc-unit          HPC transport + tools unit tests (offline)"
	@echo "  test-hpc-integration   HPC SSH connectivity tests (requires PNNL network)"
	@echo "  test-hpc-e2e           HPC job lifecycle E2E (requires DECEPTION_E2E_ENABLED=true)"
	@echo "  test-workspace-e2e    Workspace tools E2E (built-in/Deception/Tahoma, opt-in per cluster)"
	@echo "  test-hpc-cross-service Cross-service E2E (sandbox->shared vol->Slurm submit+monitor)"
	@echo "  test-hpc-all           Run all HPC tests (integration/e2e auto-skip if unreachable)"
	@echo ""
	@echo "Nohup Runners (background with timestamped logs/):"
	@echo "  nohup-test-all              All offline tests in background"
	@echo "  nohup-test-unit             Unit tests in background"
	@echo "  nohup-test-lint             Lint tests in background"
	@echo "  nohup-test-imports          Import tests in background"
	@echo "  nohup-test-security         Security tests in background"
	@echo "  nohup-test-integration      Integration tests in background"
	@echo "  nohup-test-e2e              E2E tests in background"
	@echo "  nohup-test-hpc-unit         HPC unit tests in background"
	@echo "  nohup-test-hpc-integration  HPC integration tests in background"
	@echo "  nohup-test-hpc-e2e          HPC E2E tests in background"
	@echo "  nohup-test-hpc-cross-service HPC cross-service E2E in background"
	@echo "  nohup-test-hpc-all          All HPC tests in background"
	@echo ""
	@echo "Security Profiles:"
	@echo "  start-spire      Start SPIRE server + agent (--profile spire)"
	@echo "  stop-spire       Stop SPIRE services"
	@echo "  start-oidc       Start oauth2_proxy (--profile oidc)"
	@echo "  stop-oidc        Stop oauth2_proxy"
	@echo "  start-secure     Start full stack + SPIRE + OIDC"
	@echo "  bootstrap-spire  Bootstrap SPIRE (join token + workload entries)"
	@echo ""
	@echo "Federation (pnnl.adept <-> pnnl.adept.slurm):"
	@echo "  start-federation     Start ADEPT SPIRE server + agent (--profile federation)"
	@echo "  stop-federation      Stop ADEPT SPIRE services"
	@echo "  bootstrap-federation Bootstrap bidirectional trust bundle exchange"
	@echo "  test-federation      Run federation + JWT bridge unit tests"
	@echo "  test-jwt-bridge      Run JWT bridge unit tests only"
	@echo ""
	@echo "Validation:"
	@echo "  validate-cluster Validate Slurm backend (munge, nodes, jobs)"
	@echo "  validate-mcp     Validate MCP server + proxy health"
	@echo "  validate-all     Run all validations"
	@echo ""
	@echo "Configuration:"
	@echo "  CONTAINER_ENGINE  Container runtime (default: docker)"
	@echo "  SLURM_VERSION     Slurm version (default: 25.11.2)"
