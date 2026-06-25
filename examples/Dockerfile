# Dockerfile for ADEPT Examples
#
# This Dockerfile creates a standalone container for running ADEPT examples
# with all dependencies (OpenAI client, LangGraph, ADEPT framework).
#
# BUILD MODES:
# 1. Standalone Mode (minimal - just examples dependencies)
# 2. Full Mode (with ADEPT framework installed)
#
# USAGE:
#   # Build standalone mode
#   docker build -t adept-examples:standalone --target standalone examples/
#
#   # Build full mode with ADEPT framework
#   docker build -t adept-examples:full --target full -f examples/Dockerfile .
#
#   # Run example
#   docker run --rm --network=agentic_framework_network \
#       -e ADEPT_SERVICE_API_TOKEN="sk-service-..." \
#       adept-examples:standalone \
#       python /app/examples/openai_client_service_token_example.py
#
# RELATED:
#   - examples/requirements.txt - Dependencies for standalone mode
#   - examples/README.md - Usage documentation
#   - pyproject.toml - Full ADEPT framework dependencies

# =============================================================================
# BASE STAGE: Python runtime
# =============================================================================

FROM python:3.11-slim AS base

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create examples directory
RUN mkdir -p /app/examples /app/src

# =============================================================================
# STANDALONE STAGE: Minimal dependencies for examples
# =============================================================================

FROM base AS standalone

LABEL description="ADEPT Examples (Standalone Mode)"
LABEL mode="standalone"
LABEL dependencies="openai,httpx,langgraph,litellm"

# Copy examples requirements
COPY requirements.txt /app/examples/requirements.txt

# Install example dependencies only
RUN pip install --no-cache-dir -r /app/examples/requirements.txt

# Copy example scripts
COPY *.py /app/examples/
COPY scripts/ /app/examples/scripts/

# Set Python path
ENV PYTHONPATH=/app

# Default command (shows available examples)
CMD ["python", "-c", "print('ADEPT Examples (Standalone Mode)\\n\\nAvailable examples:\\n- openai_client_service_token_example.py\\n- langgraph_adept_quickstart.py\\n- langgraph_adept_integration.py\\n\\nUsage:\\n  docker run ... python /app/examples/openai_client_service_token_example.py')"]

# =============================================================================
# FULL STAGE: ADEPT framework + examples
# =============================================================================

FROM base AS full

LABEL description="ADEPT Examples (Full Mode with Framework)"
LABEL mode="full"
LABEL dependencies="adept-framework,openai,langgraph,litellm"

# Copy ADEPT framework source
COPY src/ /app/src/
COPY pyproject.toml /app/pyproject.toml
COPY README.md /app/README.md

# Copy examples
COPY examples/requirements.txt /app/examples/requirements.txt
COPY examples/*.py /app/examples/
COPY examples/scripts/ /app/examples/scripts/

# Install ADEPT framework (editable mode)
RUN pip install --no-cache-dir -e /app

# Install example dependencies (may overlap with ADEPT dependencies)
RUN pip install --no-cache-dir -r /app/examples/requirements.txt

# Set Python path
ENV PYTHONPATH=/app/src:/app

# Default command (shows available examples with framework features)
CMD ["python", "-c", "print('ADEPT Examples (Full Mode)\\n\\nADEPT Framework: Installed ✅\\nSession Tracking: Available ✅\\n\\nAvailable examples:\\n- openai_client_service_token_example.py (with session tracking)\\n- langgraph_adept_quickstart.py\\n- langgraph_adept_integration.py\\n\\nUsage:\\n  docker run ... python /app/examples/openai_client_service_token_example.py')"]

# =============================================================================
# USAGE EXAMPLES
# =============================================================================
#
# Build and Run Standalone Mode:
# -------------------------------
# docker build -t adept-examples:standalone --target standalone examples/
#
# docker run --rm --network=agentic_framework_network \
#     -e ADEPT_SERVICE_API_TOKEN="sk-service-..." \
#     -e AGENT_GATEWAY_URL="http://agent_gateway:8081/v1" \
#     adept-examples:standalone \
#     python /app/examples/openai_client_service_token_example.py
#
# Build and Run Full Mode:
# ------------------------
# docker build -t adept-examples:full --target full -f examples/Dockerfile .
#
# docker run --rm --network=agentic_framework_network \
#     -e ADEPT_SERVICE_API_TOKEN="sk-service-..." \
#     -e AGENT_GATEWAY_URL="http://agent_gateway:8081/v1" \
#     -e POSTGRES_URL="postgresql://admin:admin@postgres:5432/postgres" \
#     adept-examples:full \
#     python /app/examples/openai_client_service_token_example.py
#
# LangGraph Examples:
# -------------------
# docker run --rm --network=agentic_framework_network \
#     -e KEYCLOAK_USERNAME="notebook-user" \
#     -e KEYCLOAK_PASSWORD="notebook-password" \
#     -e KEYCLOAK_URL="http://keycloak:8180" \
#     -e AGENT_GATEWAY_URL="http://agent_gateway:8081/v1" \
#     adept-examples:standalone \
#     python /app/examples/langgraph_adept_quickstart.py
