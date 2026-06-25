#!/bin/bash
# Container-based unit test script for observability integration
# Session 18 - Testing observability factory integration

set -e

echo "=================================================="
echo "Observability Integration Testing Script"
echo "Session 18 - Post-integration validation"
echo "=================================================="

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check prerequisites
echo -e "${YELLOW}Checking prerequisites...${NC}"

# Check if Langfuse is running
if docker ps --format "{{.Names}}" | grep -q "langfuse-web"; then
    echo -e "${GREEN}✓ Langfuse services are running${NC}"
else
    echo -e "${RED}✗ Langfuse services not running. Run 'make langfuse-start' first${NC}"
    exit 1
fi

# Check if observability backend is configured
if grep -q "^OBSERVABILITY_BACKEND=langfuse" .env; then
    echo -e "${GREEN}✓ Observability backend configured${NC}"
else
    echo -e "${YELLOW}! Observability backend not set to langfuse${NC}"
fi

# Check if Langfuse credentials exist (support both naming conventions)
if (grep -q "^LANGFUSE_PUBLIC_KEY=" .env || grep -q "^LANGFUSE_INIT_PROJECT_PUBLIC_KEY=" .env) && \
   (grep -q "^LANGFUSE_SECRET_KEY=" .env || grep -q "^LANGFUSE_INIT_PROJECT_SECRET_KEY=" .env); then
    echo -e "${GREEN}✓ Langfuse credentials found${NC}"
else
    echo -e "${RED}✗ Langfuse credentials missing. Run 'make langfuse-bootstrap' first${NC}"
    exit 1
fi

echo ""
echo "=================================================="
echo "Running Container-Based Unit Tests"
echo "=================================================="

# Run observability unit tests with clean output
echo -e "${YELLOW}Running observability module unit tests...${NC}"
docker run --rm \
    --network=agentic_framework_network \
    -v "$(pwd)/src":/app/src \
    -v "$(pwd)/tests":/app/tests \
    -v "$(pwd)/.env":/app/.env:ro \
    -w /app \
    -e OBSERVABILITY_BACKEND=langfuse \
    -e LANGFUSE_PUBLIC_KEY="${LANGFUSE_PUBLIC_KEY}" \
    -e LANGFUSE_SECRET_KEY="${LANGFUSE_SECRET_KEY}" \
    -e LANGFUSE_INIT_PROJECT_PUBLIC_KEY="${LANGFUSE_INIT_PROJECT_PUBLIC_KEY}" \
    -e LANGFUSE_INIT_PROJECT_SECRET_KEY="${LANGFUSE_INIT_PROJECT_SECRET_KEY}" \
    -e LANGFUSE_HOST="${LANGFUSE_HOST:-http://langfuse-web:3000}" \
    -e OTEL_EXPORTER_OTLP_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT:-http://langfuse-web:3000}" \
    -e OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="${OTEL_EXPORTER_OTLP_TRACES_ENDPOINT:-http://langfuse-web:3000/v1/traces}" \
    -e OTEL_EXPORTER_OTLP_PROTOCOL="${OTEL_EXPORTER_OTLP_PROTOCOL:-http/protobuf}" \
    agentic-framework-deps-base \
    /bin/bash -c "
        pip install pytest pytest-asyncio langfuse 2>&1 | grep -v 'Requirement already satisfied' && \
        pytest tests/unit/agentic_framework_pkg/core/test_observability.py -v \
            --tb=short \
            -m 'not integration' \
            2>&1 | grep -v 'Requirement already satisfied'
    "

echo ""
echo "=================================================="
echo "Running Integration Tests with Logger Config"
echo "=================================================="

# Test logger_config integration
echo -e "${YELLOW}Testing logger_config integration...${NC}"
docker run --rm \
    --network=agentic_framework_network \
    -v "$(pwd)/src":/app/src \
    -v "$(pwd)/tests":/app/tests \
    -v "$(pwd)/.env":/app/.env:ro \
    -w /app \
    -e OBSERVABILITY_BACKEND=langfuse \
    -e LANGFUSE_PUBLIC_KEY="${LANGFUSE_PUBLIC_KEY}" \
    -e LANGFUSE_SECRET_KEY="${LANGFUSE_SECRET_KEY}" \
    -e LANGFUSE_INIT_PROJECT_PUBLIC_KEY="${LANGFUSE_INIT_PROJECT_PUBLIC_KEY}" \
    -e LANGFUSE_INIT_PROJECT_SECRET_KEY="${LANGFUSE_INIT_PROJECT_SECRET_KEY}" \
    -e LANGFUSE_HOST="${LANGFUSE_HOST:-http://langfuse-web:3000}" \
    -e OTEL_EXPORTER_OTLP_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT:-http://langfuse-web:3000}" \
    -e OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="${OTEL_EXPORTER_OTLP_TRACES_ENDPOINT:-http://langfuse-web:3000/v1/traces}" \
    -e OTEL_EXPORTER_OTLP_PROTOCOL="${OTEL_EXPORTER_OTLP_PROTOCOL:-http/protobuf}" \
    agentic-framework-deps-base \
    /bin/bash -c "
        pip install pytest 2>&1 | grep -v 'Requirement already satisfied' && \
        python -c '
from agentic_framework_pkg.logger_config import get_logger
from agentic_framework_pkg.core.observability import SmartLogger
import os

os.environ[\"OBSERVABILITY_BACKEND\"] = \"langfuse\"

logger = get_logger(\"integration_test\")
print(f\"Logger type: {type(logger).__name__}\")
print(f\"Is SmartLogger: {isinstance(logger, SmartLogger)}\")

# Test logging
logger.info(\"Integration test message\")
logger.debug(\"Debug message\")
logger.error(\"Test error message\")

print(\"✓ Logger config integration successful\")
'
    "

echo ""
echo "=================================================="
echo "Testing Decorator Functionality"
echo "=================================================="

# Test decorators
echo -e "${YELLOW}Testing observability decorators...${NC}"
docker run --rm \
    --network=agentic_framework_network \
    -v "$(pwd)/src":/app/src \
    -v "$(pwd)/tests":/app/tests \
    -v "$(pwd)/.env":/app/.env:ro \
    -w /app \
    -e OBSERVABILITY_BACKEND=langfuse \
    -e LANGFUSE_PUBLIC_KEY="${LANGFUSE_PUBLIC_KEY}" \
    -e LANGFUSE_SECRET_KEY="${LANGFUSE_SECRET_KEY}" \
    -e LANGFUSE_INIT_PROJECT_PUBLIC_KEY="${LANGFUSE_INIT_PROJECT_PUBLIC_KEY}" \
    -e LANGFUSE_INIT_PROJECT_SECRET_KEY="${LANGFUSE_INIT_PROJECT_SECRET_KEY}" \
    -e LANGFUSE_HOST="${LANGFUSE_HOST:-http://langfuse-web:3000}" \
    -e OTEL_EXPORTER_OTLP_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT:-http://langfuse-web:3000}" \
    -e OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="${OTEL_EXPORTER_OTLP_TRACES_ENDPOINT:-http://langfuse-web:3000/v1/traces}" \
    -e OTEL_EXPORTER_OTLP_PROTOCOL="${OTEL_EXPORTER_OTLP_PROTOCOL:-http/protobuf}" \
    agentic-framework-deps-base \
    /bin/bash -c "
        pip install pytest pytest-asyncio 2>&1 | grep -v 'Requirement already satisfied' && \
        python -c '
import asyncio
from agentic_framework_pkg.core.observability import (
    observe,
    observable_tool,
    mcp_tool_instrumentor
)

@observe(name=\"test_function\")
def sync_function(x: int) -> int:
    return x * 2

@observable_tool(name=\"test_tool\")
async def async_tool(query: str) -> dict:
    return {\"result\": query.upper()}

@mcp_tool_instrumentor(tool_name=\"mcp_test\")
async def mcp_tool(data: str) -> dict:
    return {\"processed\": data}

# Test sync function
result = sync_function(21)
assert result == 42, f\"Expected 42, got {result}\"
print(\"✓ @observe decorator works\")

# Test async tool
async def test():
    tool_result = await async_tool(\"hello\")
    assert tool_result[\"result\"] == \"HELLO\"
    print(\"✓ @observable_tool decorator works\")

    mcp_result = await mcp_tool(\"test\")
    assert mcp_result[\"processed\"] == \"test\"
    print(\"✓ @mcp_tool_instrumentor decorator works\")

asyncio.run(test())
'
    "

echo ""
echo "=================================================="
echo "Checking Service Integration Points"
echo "=================================================="

# Check if services are using the observability module
echo -e "${YELLOW}Verifying service integrations...${NC}"

# Check orchestration service
if docker exec orchestration_service python -c "
from agentic_framework_pkg.logger_config import get_logger
logger = get_logger('test')
print(f'Logger type: {type(logger).__name__}')
" 2>/dev/null; then
    echo -e "${GREEN}✓ Orchestration service can import observability${NC}"
else
    echo -e "${YELLOW}! Orchestration service needs rebuild${NC}"
fi

# Check MCP server
if docker exec mcp_server python -c "
from agentic_framework_pkg.logger_config import get_logger
logger = get_logger('test')
print(f'Logger type: {type(logger).__name__}')
" 2>/dev/null; then
    echo -e "${GREEN}✓ MCP server can import observability${NC}"
else
    echo -e "${YELLOW}! MCP server needs rebuild${NC}"
fi

echo ""
echo "=================================================="
echo "Summary"
echo "=================================================="

echo -e "${GREEN}Observability integration testing preparation complete!${NC}"
echo ""
echo "Next steps:"
echo "1. Rebuild services with observability integration:"
echo "   make rebuild-orchestrator"
echo "   make rebuild-mcp"
echo ""
echo "2. Run full test suite after rebuild:"
echo "   ./scripts/test_observability_integration.sh"
echo ""
echo "3. Check Langfuse UI for traces:"
echo "   http://localhost:3001"
echo ""
echo "4. Run UAT/E2E tests with observability:"
echo "   make validate-e2e 2>&1 | grep -v 'Requirement already satisfied'"