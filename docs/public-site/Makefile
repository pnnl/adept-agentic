.PHONY: build serve deploy validate validate-content validate-build clean install \
       docker-build docker-serve docker-nginx stage scan

IMAGE_NAME ?= adept-docs
IMAGE_TAG ?= latest
PORT ?= 8000

# Scanner configuration (leverages scripts/release/ infrastructure)
PROJECT_ROOT := $(shell git rev-parse --show-toplevel)
SCANNER_IMAGE ?= adept-release-scanner:latest
SCAN_PASSES ?= lightweight
SCAN_GATE ?= 90
STAGE_DIR := /tmp/adept-docs-stage

# --- Local Development ---

install:
	pip install -r requirements.txt

build: install
	mkdocs build --strict

serve: install
	mkdocs serve --dev-addr 127.0.0.1:$(PORT)

clean:
	rm -rf site/ $(STAGE_DIR)

# --- Validation (Full Pipeline) ---

validate: validate-build validate-content
	@echo "All validation checks passed."

validate-build: install
	mkdocs build --strict
	@echo "MkDocs build passed (zero warnings, strict mode)."

validate-content: validate-build stage scan
	@echo "Content safety validation passed (ASOPB scan + pattern checks)."

# Stage the built site into a scannable tree (mirrors release staging pattern)
stage: validate-build
	@rm -rf $(STAGE_DIR)
	@mkdir -p $(STAGE_DIR)
	@cp -r site/ $(STAGE_DIR)/site/
	@cp -r docs/ $(STAGE_DIR)/docs/
	@echo "Staged docs content to $(STAGE_DIR) ($(shell find $(STAGE_DIR) -type f | wc -l) files)"

# Run ASOPB scanner (lightweight passes: regex + secrets) against staged docs
# Uses the same scanner image and pipeline as the full release scan
scan: stage
	@echo "Running ASOPB scan (passes: $(SCAN_PASSES), gate: $(SCAN_GATE))..."
	@$(PROJECT_ROOT)/scripts/release/scan_path.sh $(STAGE_DIR) $(SCAN_PASSES) $(SCAN_GATE)

# --- Docker ---

docker-build:
	docker build --target builder -t $(IMAGE_NAME):$(IMAGE_TAG) .

docker-serve:
	docker build --target dev -t $(IMAGE_NAME)-dev:$(IMAGE_TAG) .
	docker run --rm -p $(PORT):8000 -v $(CURDIR)/docs:/docs/docs:ro $(IMAGE_NAME)-dev:$(IMAGE_TAG)

docker-nginx:
	docker build --target serve -t $(IMAGE_NAME)-nginx:$(IMAGE_TAG) .
	docker run --rm -p 8080:80 $(IMAGE_NAME)-nginx:$(IMAGE_TAG)

# --- CI/CD ---

deploy: validate
	mkdocs gh-deploy --force --clean
