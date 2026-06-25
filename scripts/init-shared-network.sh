#!/bin/bash
# Setup docker compose networks for ADEPT stack
#
# NOTE: This script is Docker Compose specific. For Kubernetes deployments:
# - Networks are managed via NetworkPolicies and Service mesh
# - This script is not used; network segmentation is defined in K8s manifests
# - See docs/kubernetes/ or infra/helm/ for K8s networking configuration
#
set -e  # Exit on error

echo "🚀 Creating shared Docker networks for ADEPT stack and 3rd-party integrations..."
echo ""

# Legacy network (deprecated but kept for backward compatibility)
LEGACY_NETWORK=agentic_framework_network
echo "🏗️  Creating legacy network: ${LEGACY_NETWORK} (deprecated)..."
docker network create ${LEGACY_NETWORK} --driver bridge 2>/dev/null || echo "   ✓ Network ${LEGACY_NETWORK} already exists"

# Three-tier network architecture (Session 50)
echo "🏗️  Creating three-tier network architecture..."

echo "   Creating frontend network (user-facing services)..."
docker network create adept_frontend_network --driver bridge 2>/dev/null || echo "   ✓ Network adept_frontend_network already exists"

echo "   Creating application network (business logic)..."
docker network create adept_application_network --driver bridge 2>/dev/null || echo "   ✓ Network adept_application_network already exists"

echo "   Creating data network (persistence tier)..."
docker network create adept_data_network --driver bridge 2>/dev/null || echo "   ✓ Network adept_data_network already exists"

# Sandbox isolation network (only orchestration_service + sandbox_mcp_server)
echo "🏗️  Creating sandbox isolation network..."
echo "   Creating adept_sandbox_network (sandbox ↔ orchestration only)..."
docker network create adept_sandbox_network --driver bridge 2>/dev/null || echo "   ✓ Network adept_sandbox_network already exists"

# 3rd-party integration network (Langfuse, RAGFlow, and other external services)
echo "🏗️  Creating 3rd-party integration network..."
echo "   Creating adept_integration_network (shared by Langfuse, RAGFlow, etc.)..."
docker network create adept_integration_network --driver bridge 2>/dev/null || echo "   ✓ Network adept_integration_network already exists"

echo ""
echo "✅ All Docker networks created successfully"

