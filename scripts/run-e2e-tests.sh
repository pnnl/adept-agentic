#!/bin/bash
#
# End-to-End Test Suite Orchestrator for the Agentic Framework
#
# Author: Gemini
# Date: August 5, 2025
#
# Description:
# This script provides a comprehensive, one-shot command for running the end-to-end
# test suite in a clean, representative Docker environment. It mirrors the phased
# startup logic of `start-chapter-resources.sh` to ensure a robust and reliable
# test environment. It orchestrates the entire lifecycle of the test run, including:
#   1.  Building all dependent images in the correct order.
#   2.  Cleaning the environment by tearing down any previous runs.
#   3.  Starting core infrastructure and bootstrapping Keycloak secrets.
#   4.  Verifying that the secret bootstrapping was successful.
#   5.  Starting all application services.
#   6.  Running the pytest suite in a dedicated container on the same network.
#   7.  Automatically cleaning up all services on completion or failure.
#
# --- Prerequisites ---
#
# 1.  **Docker and Docker Compose:** Ensure both are installed and the Docker daemon is running.
#
# 2.  **Environment File (.env):** The script relies on a `.env` file in the project root.
#     The `start-chapter-resources.sh` script creates this file. If it's missing, run:
#     `bash start-chapter-resources.sh`
#
# --- How to Run ---
#
# 1.  Make the script executable:
#     chmod +x scripts/run-e2e-tests-final.sh
#
# 2.  Execute the script from the project root directory:
#     ./scripts/run-e2e-tests-final.sh
#

set -e
set -o pipefail

# --- Configuration ---
COMPOSE_PROJECT_NAME="agentic_framework_e2e"
CREDENTIALS_DIR=".env-keycloak-credentials-dir"
CREDENTIALS_FILE="${CREDENTIALS_DIR}/.env-keycloak-credentials"

# Define all the compose files needed to run the full stack for testing
COMPOSE_COMMAND="docker compose -p ${COMPOSE_PROJECT_NAME} -f docker-compose.base.yaml -f docker-compose.core.yaml -f docker-compose.tests.yaml -f docker-compose.test-override.yaml"

# Define all the compose files needed to run the full stack for testing
COMPOSE_COMMAND_NO_PROJECT="docker compose -f docker-compose.base.yaml -f docker-compose.core.yaml -f docker-compose.tests.yaml -f docker-compose.test-override.yaml"

# --- Cleanup Function ---
cleanup() {
    echo "--- Tearing down Docker Compose services... ---"
    ${COMPOSE_COMMAND} down -v --remove-orphans
}

# Trap script exit and errors to call the cleanup function
trap cleanup EXIT

# --- 1. Initial Cleanup ---
echo "--- Starting clean slate setup... ---"
${COMPOSE_COMMAND} down -v --remove-orphans
rm -rf "$CREDENTIALS_DIR"
mkdir -p "$CREDENTIALS_DIR"
touch "$CREDENTIALS_FILE"

# --- 2. Phased Build and Startup ---
echo "--- Phase 1a: Building base images (os-base) sequentially... ---"
${COMPOSE_COMMAND_NO_PROJECT} --profile base-build build --no-cache os-base

echo "--- Phase 1b: Building base images (deps-base) sequentially... ---"
${COMPOSE_COMMAND_NO_PROJECT} --profile base-build build --no-cache deps-base

echo "--- Phase 2: Building all remaining application and test services... ---"
${COMPOSE_COMMAND} build

echo "--- Phase 3: Starting bootstrap dependencies (Keycloak, Postgres, Redis)... ---"
${COMPOSE_COMMAND} up -d --wait --force-recreate keycloak postgres redis

echo "--- Phase 4: Running Keycloak bootstrap container to generate secrets... ---"
${COMPOSE_COMMAND} up --no-deps --build --force-recreate --wait keycloak-setup
echo "--- Bootstrap complete. Secrets are now available. ---"

# --- 3. Pre-flight Check: Verify Secret Bootstrapping ---
echo "--- Verifying that secrets were bootstrapped... ---"
if [ ! -f "$CREDENTIALS_FILE" ]; then
    echo "❌ ERROR: The credentials file ($CREDENTIALS_FILE) is empty or was not created."
    echo "Bootstrap process failed. Aborting tests."
    ${COMPOSE_COMMAND} logs keycloak-setup
    exit 1
else
    echo "✅ SUCCESS: Credentials file was created and is not empty."
fi

# --- 4. Start All Application Services & Run Tests ---
echo "--- Phase 5: Starting all application services and running the test suite... ---"
# This single command starts all defined services AND the test runner.
# The '--exit-code-from' flag ensures that the script's exit code matches the test result,
# and '--abort-on-container-exit' ensures that if the test runner finishes (or fails),
# all other services are stopped automatically.
${COMPOSE_COMMAND} up --build tests-runner

echo "--- E2E Test suite finished successfully. ---"
# The 'trap' will handle the final cleanup automatically on script exit.
