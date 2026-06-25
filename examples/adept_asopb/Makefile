# examples/adept_asopb/Makefile — ASOPB canonical package test targets
#
# Two execution modes:
#   Container (recommended): Uses adept-release-scanner image with source overlay
#   Host: Requires conda activate adept-session (pytest-asyncio, pydantic)
#
# Container mode mounts canonical source over the vendored copy baked into the
# image, so tests always run against the latest code without image rebuilds.

SHELL := /bin/bash
PROJECT_ROOT := $(shell cd ../.. && pwd)
ASOPB_SRC := $(CURDIR)/src
ASOPB_TESTS := $(CURDIR)/tests
LOG_DIR := $(PROJECT_ROOT)/logs
IMAGE_NAME := adept-release-scanner
IMAGE_TAG := latest

# Mount canonical source into container, overriding the vendored copy
ASOPB_MOUNTS = \
	-v $(ASOPB_SRC)/asopb:/app/asopb_src/asopb:ro \
	-v $(ASOPB_TESTS):/app/asopb_tests:ro

.PHONY: help test test-container test-host test-ingester test-ingester-container \
        test-domains test-domains-container test-redteam test-redteam-container \
        test-profiles-container test-scoring-container test-token-budget-container \
        test-langfuse-container test-langfuse-report-container test-langfuse-sink-container \
        test-all test-all-container docker-build docker-test \
        lint lint-host format format-host validate-domains validate-domains-host \
        validate-pipeline validate-pipeline-host validate-pipeline-container \
        scan-full-8domain \
        test-observability test-observability-unit test-observability-cli

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-28s %s\n", $$1, $$2}'

# ─── Container-Based Targets (canonical) ─────────────────────────────────────

test: test-container ## Run all ASOPB tests (alias for test-container)

test-container: ## Run all ASOPB tests inside scanner container (canonical)
	@mkdir -p $(LOG_DIR)
	@LOG=$(LOG_DIR)/asopb_test_all_$$(date +%Y%m%d_%H%M%S).log; \
	echo "==> Running ASOPB tests (container) → $$LOG"; \
	docker run --rm --user $$(id -u):$$(id -g) --entrypoint bash \
		$(ASOPB_MOUNTS) \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		-c 'PYTHONPATH=/app/asopb_src python3 -m pytest /app/asopb_tests/ -v --tb=short' \
		2>&1 | tee "$$LOG"; EXIT=$$?; \
	echo ""; \
	echo "==> Log: $$LOG (exit $$EXIT)"; \
	exit $$EXIT

test-ingester-container: ## Run PromptfooIngester tests inside scanner container
	@mkdir -p $(LOG_DIR)
	@LOG=$(LOG_DIR)/asopb_test_ingester_$$(date +%Y%m%d_%H%M%S).log; \
	echo "==> Running PromptfooIngester tests (container) → $$LOG"; \
	docker run --rm --user $$(id -u):$$(id -g) --entrypoint bash \
		$(ASOPB_MOUNTS) \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		-c 'PYTHONPATH=/app/asopb_src python3 -m pytest /app/asopb_tests/test_promptfoo_ingester.py -v --tb=short' \
		2>&1 | tee "$$LOG"; EXIT=$$?; \
	echo ""; \
	echo "==> Log: $$LOG (exit $$EXIT)"; \
	exit $$EXIT

test-domains-container: ## Run domain evaluator tests inside scanner container
	@mkdir -p $(LOG_DIR)
	@LOG=$(LOG_DIR)/asopb_test_domains_$$(date +%Y%m%d_%H%M%S).log; \
	echo "==> Running domain evaluator tests (container) → $$LOG"; \
	docker run --rm --user $$(id -u):$$(id -g) --entrypoint bash \
		$(ASOPB_MOUNTS) \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		-c 'PYTHONPATH=/app/asopb_src python3 -m pytest /app/asopb_tests/test_domains.py -v --tb=short' \
		2>&1 | tee "$$LOG"; EXIT=$$?; \
	echo ""; \
	echo "==> Log: $$LOG (exit $$EXIT)"; \
	exit $$EXIT

test-redteam-container: ## Run red-team framework tests inside scanner container
	@mkdir -p $(LOG_DIR)
	@LOG=$(LOG_DIR)/asopb_test_redteam_$$(date +%Y%m%d_%H%M%S).log; \
	echo "==> Running red-team tests (container) → $$LOG"; \
	docker run --rm --user $$(id -u):$$(id -g) --entrypoint bash \
		$(ASOPB_MOUNTS) \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		-c 'PYTHONPATH=/app/asopb_src python3 -m pytest /app/asopb_tests/test_redteam.py /app/asopb_tests/test_promptfoo_ingester.py -v --tb=short' \
		2>&1 | tee "$$LOG"; EXIT=$$?; \
	echo ""; \
	echo "==> Log: $$LOG (exit $$EXIT)"; \
	exit $$EXIT

test-profiles-container: ## Run ProfileRegistry + ScanProfile tests inside scanner container
	@mkdir -p $(LOG_DIR)
	@LOG=$(LOG_DIR)/asopb_test_profiles_$$(date +%Y%m%d_%H%M%S).log; \
	echo "==> Running ProfileRegistry tests (container) → $$LOG"; \
	docker run --rm --user $$(id -u):$$(id -g) --entrypoint bash \
		$(ASOPB_MOUNTS) \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		-c 'PYTHONPATH=/app/asopb_src python3 -m pytest /app/asopb_tests/test_profiles.py -v --tb=short' \
		2>&1 | tee "$$LOG"; EXIT=$$?; \
	echo ""; \
	echo "==> Log: $$LOG (exit $$EXIT)"; \
	exit $$EXIT

test-scoring-container: ## Run scoring + pipeline weight tests inside scanner container
	@mkdir -p $(LOG_DIR)
	@LOG=$(LOG_DIR)/asopb_test_scoring_$$(date +%Y%m%d_%H%M%S).log; \
	echo "==> Running scoring tests (container) → $$LOG"; \
	docker run --rm --user $$(id -u):$$(id -g) --entrypoint bash \
		$(ASOPB_MOUNTS) \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		-c 'PYTHONPATH=/app/asopb_src python3 -m pytest /app/asopb_tests/test_scoring.py /app/asopb_tests/test_profiles.py -v --tb=short' \
		2>&1 | tee "$$LOG"; EXIT=$$?; \
	echo ""; \
	echo "==> Log: $$LOG (exit $$EXIT)"; \
	exit $$EXIT

test-token-budget-container: ## Run token budget gate tests inside scanner container
	@mkdir -p $(LOG_DIR)
	@LOG=$(LOG_DIR)/asopb_test_token_budget_$$(date +%Y%m%d_%H%M%S).log; \
	echo "==> Running token budget tests (container) → $$LOG"; \
	docker run --rm --user $$(id -u):$$(id -g) --entrypoint bash \
		$(ASOPB_MOUNTS) \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		-c 'PYTHONPATH=/app/asopb_src python3 -m pytest /app/asopb_tests/test_token_budget.py -v --tb=short' \
		2>&1 | tee "$$LOG"; EXIT=$$?; \
	echo ""; \
	echo "==> Log: $$LOG (exit $$EXIT)"; \
	exit $$EXIT

test-langfuse-container: ## Run Langfuse integration tests inside scanner container
	@mkdir -p $(LOG_DIR)
	@LOG=$(LOG_DIR)/asopb_test_langfuse_$$(date +%Y%m%d_%H%M%S).log; \
	echo "==> Running Langfuse integration tests (container) → $$LOG"; \
	docker run --rm --user $$(id -u):$$(id -g) --entrypoint bash \
		$(ASOPB_MOUNTS) \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		-c 'PYTHONPATH=/app/asopb_src python3 -m pytest /app/asopb_tests/test_langfuse_integration.py /app/asopb_tests/test_langfuse_report.py -v --tb=short' \
		2>&1 | tee "$$LOG"; EXIT=$$?; \
	echo ""; \
	echo "==> Log: $$LOG (exit $$EXIT)"; \
	exit $$EXIT

test-langfuse-report-container: ## Run Langfuse report generator tests inside scanner container
	@mkdir -p $(LOG_DIR)
	@LOG=$(LOG_DIR)/asopb_test_langfuse_report_$$(date +%Y%m%d_%H%M%S).log; \
	echo "==> Running Langfuse report generator tests (container) → $$LOG"; \
	docker run --rm --user $$(id -u):$$(id -g) --entrypoint bash \
		$(ASOPB_MOUNTS) \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		-c 'PYTHONPATH=/app/asopb_src python3 -m pytest /app/asopb_tests/test_langfuse_report.py -v --tb=short' \
		2>&1 | tee "$$LOG"; EXIT=$$?; \
	echo ""; \
	echo "==> Log: $$LOG (exit $$EXIT)"; \
	exit $$EXIT

test-langfuse-sink-container: ## Run Langfuse sink (promptfoo bridge) tests inside scanner container
	@mkdir -p $(LOG_DIR)
	@LOG=$(LOG_DIR)/asopb_test_langfuse_sink_$$(date +%Y%m%d_%H%M%S).log; \
	echo "==> Running Langfuse sink tests (container) → $$LOG"; \
	docker run --rm --user $$(id -u):$$(id -g) --entrypoint bash \
		$(ASOPB_MOUNTS) \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		-c 'PYTHONPATH=/app/asopb_src python3 -m pytest /app/asopb_tests/test_langfuse_sink.py -v --tb=short' \
		2>&1 | tee "$$LOG"; EXIT=$$?; \
	echo ""; \
	echo "==> Log: $$LOG (exit $$EXIT)"; \
	exit $$EXIT

test-all-container: ## Run ALL ASOPB tests + verify import paths (container, comprehensive)
	@mkdir -p $(LOG_DIR)
	@LOG=$(LOG_DIR)/asopb_test_all_comprehensive_$$(date +%Y%m%d_%H%M%S).log; \
	echo "==> Running ASOPB comprehensive test suite (container) → $$LOG"; \
	docker run --rm --user $$(id -u):$$(id -g) --entrypoint bash \
		$(ASOPB_MOUNTS) \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		-c 'echo "=== Import validation ===" && PYTHONPATH=/app/asopb_src python3 /app/asopb_tests/validate_imports.py && echo "" && echo "=== Full test suite ===" && PYTHONPATH=/app/asopb_src python3 -m pytest /app/asopb_tests/ -v --tb=short' \
		2>&1 | tee "$$LOG"; EXIT=$$?; \
	echo ""; \
	echo "==> Log: $$LOG (exit $$EXIT)"; \
	exit $$EXIT

# ─── Host-Based Targets (convenience, requires conda) ────────────────────────

test-host: ## Run all ASOPB tests on host (requires: conda activate adept-session)
	@mkdir -p $(LOG_DIR)
	@LOG=$(LOG_DIR)/asopb_test_host_$$(date +%Y%m%d_%H%M%S).log; \
	echo "==> Running ASOPB tests (host — requires pytest-asyncio) → $$LOG"; \
	echo "    NOTE: Run 'conda activate adept-session' first"; \
	PYTHONPATH=$(ASOPB_SRC) python3 -m pytest $(ASOPB_TESTS)/ -v --tb=short \
		2>&1 | tee "$$LOG"; EXIT=$$?; \
	echo ""; \
	echo "==> Log: $$LOG (exit $$EXIT)"; \
	exit $$EXIT

test-ingester: test-ingester-container ## Run PromptfooIngester tests (alias for container)

test-domains: test-domains-container ## Run domain tests (alias for container)

test-redteam: test-redteam-container ## Run red-team tests (alias for container)

test-all: test-all-container ## Run comprehensive tests (alias for container)

# ─── Docker Image Build/Test (self-contained ASOPB image) ─────────────────────

# ─── Integration Tests (require scanner image + sample repos) ─────────────────

test-integration-container: ## Run integration tests: evaluator → scanner → domain scoring pipeline
	@mkdir -p $(LOG_DIR)
	@LOG=$(LOG_DIR)/asopb_test_integration_$$(date +%Y%m%d_%H%M%S).log; \
	echo "==> Running ASOPB integration tests (container) → $$LOG"; \
	docker run --rm --user $$(id -u):$$(id -g) --entrypoint bash \
		$(ASOPB_MOUNTS) \
		-v $(PROJECT_ROOT):/project:ro \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		-c 'PYTHONPATH=/app/asopb_src python3 -m pytest /app/asopb_tests/ -v --tb=short -k "integration"' \
		2>&1 | tee "$$LOG"; EXIT=$$?; \
	echo ""; \
	echo "==> Log: $$LOG (exit $$EXIT)"; \
	exit $$EXIT

test-e2e-container: ## Run E2E tests: full eval pipeline against sample repo (requires promptfoo output fixtures)
	@mkdir -p $(LOG_DIR)
	@LOG=$(LOG_DIR)/asopb_test_e2e_$$(date +%Y%m%d_%H%M%S).log; \
	echo "==> Running ASOPB E2E tests (container) → $$LOG"; \
	docker run --rm --user $$(id -u):$$(id -g) --entrypoint bash \
		$(ASOPB_MOUNTS) \
		-v $(PROJECT_ROOT):/project:ro \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		-c 'PYTHONPATH=/app/asopb_src python3 -m pytest /app/asopb_tests/ -v --tb=short -k "e2e"' \
		2>&1 | tee "$$LOG"; EXIT=$$?; \
	echo ""; \
	echo "==> Log: $$LOG (exit $$EXIT)"; \
	exit $$EXIT

# ─── Docker Image Build/Test (self-contained ASOPB image) ─────────────────────

docker-build: ## Build the standalone ASOPB Docker image
	@echo "==> Building asopb:latest image"
	docker build -t asopb:latest -f $(CURDIR)/Dockerfile $(CURDIR)

docker-test: docker-build ## Build image and run tests inside it
	@mkdir -p $(LOG_DIR)
	@LOG=$(LOG_DIR)/asopb_docker_test_$$(date +%Y%m%d_%H%M%S).log; \
	echo "==> Running ASOPB tests (self-contained image) → $$LOG"; \
	docker run --rm --user $$(id -u):$$(id -g) \
		asopb:latest \
		pytest tests/ -v --tb=short \
		2>&1 | tee "$$LOG"; EXIT=$$?; \
	echo ""; \
	echo "==> Log: $$LOG (exit $$EXIT)"; \
	exit $$EXIT

# ─── Linting and Formatting (borrows pyproject.toml config) ──────────────────

lint: lint-host ## Run all linters (alias for lint-host)

lint-host: ## Run ruff + black --check on ASOPB source (host, requires conda)
	@mkdir -p $(LOG_DIR)
	@LOG=$(LOG_DIR)/asopb_lint_$$(date +%Y%m%d_%H%M%S).log; \
	echo "==> Running ASOPB linters → $$LOG"; \
	( \
		echo "--- ruff check ---" && \
		ruff check $(ASOPB_SRC)/asopb/ --config $(CURDIR)/pyproject.toml && \
		echo "" && \
		echo "--- black --check ---" && \
		black --check $(ASOPB_SRC)/asopb/ --config $(CURDIR)/pyproject.toml --diff && \
		echo "" && \
		echo "--- mypy ---" && \
		mypy $(ASOPB_SRC)/asopb/ --config-file $(CURDIR)/pyproject.toml --ignore-missing-imports \
	) 2>&1 | tee "$$LOG"; EXIT=$$?; \
	echo ""; \
	echo "==> Log: $$LOG (exit $$EXIT)"; \
	exit $$EXIT

format: format-host ## Format ASOPB source (alias for format-host)

format-host: ## Apply black + isort formatting (host, requires conda)
	@echo "==> Formatting ASOPB source"
	black $(ASOPB_SRC)/asopb/ --config $(CURDIR)/pyproject.toml
	isort $(ASOPB_SRC)/asopb/ --profile black --line-length 100

lint-container: ## Run linters inside scanner container
	@mkdir -p $(LOG_DIR)
	@LOG=$(LOG_DIR)/asopb_lint_container_$$(date +%Y%m%d_%H%M%S).log; \
	echo "==> Running ASOPB linters (container) → $$LOG"; \
	docker run --rm --user $$(id -u):$$(id -g) --entrypoint bash \
		$(ASOPB_MOUNTS) \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		-c 'pip install -q ruff black mypy 2>/dev/null && ruff check /app/asopb_src/asopb/ --target-version py311 && black --check /app/asopb_src/asopb/ --line-length 100 --diff' \
		2>&1 | tee "$$LOG"; EXIT=$$?; \
	echo ""; \
	echo "==> Log: $$LOG (exit $$EXIT)"; \
	exit $$EXIT

# ─── Domain Evaluator Validation ─────────────────────────────────────────────

validate-domains: validate-domains-host ## Run domain evaluator contract tests (alias)

validate-domains-host: ## Run domain evaluator contract tests (host, requires conda)
	@mkdir -p $(LOG_DIR)
	@LOG=$(LOG_DIR)/asopb_validate_domains_$$(date +%Y%m%d_%H%M%S).log; \
	echo "==> Running ASOPB domain evaluator contract tests → $$LOG"; \
	PYTHONPATH=$(ASOPB_SRC) python3 -m pytest \
		$(ASOPB_TESTS)/test_domain_evaluators.py \
		$(ASOPB_TESTS)/test_domains.py \
		-v --tb=short \
		2>&1 | tee "$$LOG"; EXIT=$$?; \
	echo ""; \
	echo "==> Log: $$LOG (exit $$EXIT)"; \
	exit $$EXIT

validate-domains-container: ## Run domain evaluator contract tests (container)
	@mkdir -p $(LOG_DIR)
	@LOG=$(LOG_DIR)/asopb_validate_domains_container_$$(date +%Y%m%d_%H%M%S).log; \
	echo "==> Running ASOPB domain evaluator contract tests (container) → $$LOG"; \
	docker run --rm --user $$(id -u):$$(id -g) --entrypoint bash \
		$(ASOPB_MOUNTS) \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		-c 'PYTHONPATH=/app/asopb_src python3 -m pytest /app/asopb_tests/test_domain_evaluators.py /app/asopb_tests/test_domains.py -v --tb=short' \
		2>&1 | tee "$$LOG"; EXIT=$$?; \
	echo ""; \
	echo "==> Log: $$LOG (exit $$EXIT)"; \
	exit $$EXIT

# ─── Pipeline Integration Tests (Phase C) ───────────────────────────────────

validate-pipeline: validate-pipeline-host ## Run pipeline integration tests (alias)

validate-pipeline-host: ## Pipeline integration: evaluator → registry → 8 domains → ASPI with red-team (host)
	@mkdir -p $(LOG_DIR)
	@LOG=$(LOG_DIR)/asopb_validate_pipeline_$$(date +%Y%m%d_%H%M%S).log; \
	echo "==> Running ASOPB pipeline integration tests → $$LOG"; \
	PYTHONPATH=$(ASOPB_SRC) python3 -m pytest \
		$(ASOPB_TESTS)/test_pipeline_integration.py \
		$(ASOPB_TESTS)/test_promptfoo_integration.py \
		-v --tb=short \
		2>&1 | tee "$$LOG"; EXIT=$$?; \
	echo ""; \
	echo "==> Log: $$LOG (exit $$EXIT)"; \
	exit $$EXIT

validate-pipeline-container: ## Pipeline integration tests (container)
	@mkdir -p $(LOG_DIR)
	@LOG=$(LOG_DIR)/asopb_validate_pipeline_container_$$(date +%Y%m%d_%H%M%S).log; \
	echo "==> Running ASOPB pipeline integration tests (container) → $$LOG"; \
	docker run --rm --user $$(id -u):$$(id -g) --entrypoint bash \
		$(ASOPB_MOUNTS) \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		-c 'PYTHONPATH=/app/asopb_src python3 -m pytest /app/asopb_tests/test_pipeline_integration.py /app/asopb_tests/test_promptfoo_integration.py -v --tb=short' \
		2>&1 | tee "$$LOG"; EXIT=$$?; \
	echo ""; \
	echo "==> Log: $$LOG (exit $$EXIT)"; \
	exit $$EXIT

scan-full-8domain: ## Run full ASOPB 8-domain evaluation with optional promptfoo red-team (host)
	@mkdir -p $(LOG_DIR)
	@LOG=$(LOG_DIR)/asopb_scan_full_8domain_$$(date +%Y%m%d_%H%M%S).log; \
	echo "==> Running full 8-domain ASOPB evaluation → $$LOG"; \
	PYTHONPATH=$(ASOPB_SRC) python3 $(ASOPB_TESTS)/run_full_8domain_eval.py \
		--promptfoo-dir $(PROJECT_ROOT)/scripts/release/logs \
		2>&1 | tee "$$LOG"; EXIT=$$?; \
	echo ""; \
	echo "==> Log: $$LOG (exit $$EXIT)"; \
	exit $$EXIT

# ─── Observability / Token Utilization Targets ──────────────────────────────

test-observability: test-observability-unit test-observability-cli ## Run all observability tests (unit + CLI smoke)

test-observability-unit: ## Run observability unit tests (no network required)
	@mkdir -p $(LOG_DIR)
	@LOG=$(LOG_DIR)/asopb_test_observability_unit_$$(date +%Y%m%d_%H%M%S).log; \
	echo "==> Running observability unit tests (host) → $$LOG"; \
	PYTHONPATH=$(ASOPB_SRC) python3 -m pytest \
		$(ASOPB_TESTS)/observability/ -v --tb=short \
		--ignore=$(ASOPB_TESTS)/observability/test_langfuse_integration.py \
		--ignore=$(ASOPB_TESTS)/observability/test_cli_smoke.py \
		2>&1 | tee "$$LOG"; EXIT=$$?; \
	echo ""; \
	echo "==> Log: $$LOG (exit $$EXIT)"; \
	exit $$EXIT

test-observability-cli: ## Run CLI smoke tests against live Langfuse (requires LANGFUSE_PUBLIC_KEY + SECRET_KEY)
	@mkdir -p $(LOG_DIR)
	@LOG=$(LOG_DIR)/asopb_test_observability_cli_$$(date +%Y%m%d_%H%M%S).log; \
	echo "==> Running observability CLI smoke tests (host, live Langfuse) → $$LOG"; \
	if [ -z "$$LANGFUSE_PUBLIC_KEY" ] || [ -z "$$LANGFUSE_SECRET_KEY" ]; then \
		echo "ERROR: LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY must be set"; \
		echo "  export LANGFUSE_PUBLIC_KEY=pk-lf-..."; \
		echo "  export LANGFUSE_SECRET_KEY=sk-lf-..."; \
		echo "  export LANGFUSE_HOST=http://localhost:3001  # optional"; \
		exit 1; \
	fi; \
	PYTHONPATH=$(ASOPB_SRC) python3 -m pytest \
		$(ASOPB_TESTS)/observability/test_cli_smoke.py \
		-v --tb=short -m integration \
		2>&1 | tee "$$LOG"; EXIT=$$?; \
	echo ""; \
	echo "==> Log: $$LOG (exit $$EXIT)"; \
	exit $$EXIT

# ─── CI / Background Targets (nohup-wrapped, canonical project pattern) ──────

ci-test: ## Run full ASOPB test suite (nohup, background, container)
	@mkdir -p $(LOG_DIR)
	@echo "==> Launching ASOPB tests (background, container)"
	@nohup docker run --rm --user $$(id -u):$$(id -g) --entrypoint bash \
		$(ASOPB_MOUNTS) \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		-c 'PYTHONPATH=/app/asopb_src python3 -m pytest /app/asopb_tests/ -v --tb=short' \
		> $(LOG_DIR)/asopb_ci_test_$$(date +%Y%m%d_%H%M%S).log 2>&1 &
	@echo "    PID=$$!  Log: $(LOG_DIR)/asopb_ci_test_*.log"

ci-lint: ## Run linters (nohup, background, container)
	@mkdir -p $(LOG_DIR)
	@echo "==> Launching ASOPB linters (background, container)"
	@nohup docker run --rm --user $$(id -u):$$(id -g) --entrypoint bash \
		$(ASOPB_MOUNTS) \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		-c 'pip install -q ruff black 2>/dev/null && ruff check /app/asopb_src/asopb/ --target-version py311 && black --check /app/asopb_src/asopb/ --line-length 100 --diff' \
		> $(LOG_DIR)/asopb_ci_lint_$$(date +%Y%m%d_%H%M%S).log 2>&1 &
	@echo "    PID=$$!  Log: $(LOG_DIR)/asopb_ci_lint_*.log"

ci-validate-domains: ## Run domain contract tests (nohup, background, container)
	@mkdir -p $(LOG_DIR)
	@echo "==> Launching ASOPB domain validation (background, container)"
	@nohup docker run --rm --user $$(id -u):$$(id -g) --entrypoint bash \
		$(ASOPB_MOUNTS) \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		-c 'PYTHONPATH=/app/asopb_src python3 -m pytest /app/asopb_tests/test_domain_evaluators.py /app/asopb_tests/test_domains.py -v --tb=short' \
		> $(LOG_DIR)/asopb_ci_validate_domains_$$(date +%Y%m%d_%H%M%S).log 2>&1 &
	@echo "    PID=$$!  Log: $(LOG_DIR)/asopb_ci_validate_domains_*.log"

ci-all: ## Run full CI pipeline: lint + test + domain validation (nohup, sequential)
	@mkdir -p $(LOG_DIR)
	@LOG=$(LOG_DIR)/asopb_ci_all_$$(date +%Y%m%d_%H%M%S).log; \
	echo "==> Launching ASOPB full CI pipeline (background) → $$LOG"; \
	nohup bash -c '\
		echo "=== LINT ===" && \
		docker run --rm --user $$(id -u):$$(id -g) --entrypoint bash \
			$(ASOPB_MOUNTS) \
			$(IMAGE_NAME):$(IMAGE_TAG) \
			-c "pip install -q ruff black 2>/dev/null && ruff check /app/asopb_src/asopb/ --target-version py311 && black --check /app/asopb_src/asopb/ --line-length 100 --diff" && \
		echo "" && echo "=== TEST ===" && \
		docker run --rm --user $$(id -u):$$(id -g) --entrypoint bash \
			$(ASOPB_MOUNTS) \
			$(IMAGE_NAME):$(IMAGE_TAG) \
			-c "PYTHONPATH=/app/asopb_src python3 -m pytest /app/asopb_tests/ -v --tb=short" && \
		echo "" && echo "=== DOMAIN VALIDATION ===" && \
		docker run --rm --user $$(id -u):$$(id -g) --entrypoint bash \
			$(ASOPB_MOUNTS) \
			$(IMAGE_NAME):$(IMAGE_TAG) \
			-c "PYTHONPATH=/app/asopb_src python3 -m pytest /app/asopb_tests/test_domain_evaluators.py -v --tb=short" \
	' > "$$LOG" 2>&1 &
	@echo "    PID=$$!  Log: $$LOG"
