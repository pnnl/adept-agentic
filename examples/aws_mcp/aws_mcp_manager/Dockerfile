# AWS MCP Server Manager — Meta-MCP server for AWS Labs MCP collection
# Multi-stage: 'base' for testing, 'production' adds pre-installed AWS servers.
#
# Build for testing:    docker build --target base -t aws-mcp-manager:test .
# Build for production: docker build -t aws-mcp-manager:latest .

# =============================================================================
# Stage: base — meta-server + test deps (no pre-installed AWS servers)
# =============================================================================
FROM python:3.12-slim AS base

LABEL org.opencontainers.image.title="aws-mcp-manager" \
      org.opencontainers.image.description="Meta-MCP server managing 65+ AWS MCP servers on demand" \
      maintainer="ADEPT Framework"

# System deps for building native extensions (some AWS MCP servers need them)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r mcpuser && useradd -r -g mcpuser -d /app mcpuser

WORKDIR /app

# Install uv for fast package management (used for on-demand server installs)
RUN pip install --no-cache-dir uv

# Install meta-server dependencies
COPY requirements.txt requirements-test.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-test.txt

# Copy application code — build context is ./aws_mcp_manager (flat files),
# so COPY into ./aws_mcp_manager/ to create the importable Python package.
COPY . ./aws_mcp_manager/

# Inline install script for on-demand server installation
RUN printf '#!/bin/sh\nset -e\nPACKAGE="${1:?Usage: install-aws-server <package>}"\npip install --no-cache-dir "$PACKAGE"\n' > /usr/local/bin/install-aws-server && \
    chmod +x /usr/local/bin/install-aws-server

# Switch to non-root user
USER mcpuser

EXPOSE 8003

HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=20s \
    CMD python -c "import socket; s=socket.create_connection(('localhost',8003),2); s.close()" || exit 1

ENTRYPOINT ["python", "-m", "aws_mcp_manager"]
CMD ["--transport", "streamable-http", "--port", "8003", "--host", "0.0.0.0"]

# =============================================================================
# Stage: production — pre-installs 8 curated AWS MCP servers
# =============================================================================
FROM base AS production

USER root

# Pre-install curated AWS MCP servers using uv for faster resolution.
# Each installed separately so one failure doesn't block others.
RUN uv pip install --system "awslabs.s3-tables-mcp-server" || echo "WARN: s3-tables install failed"
RUN uv pip install --system "awslabs.dynamodb-mcp-server" || echo "WARN: dynamodb install failed"
RUN uv pip install --system "awslabs.cloudwatch-mcp-server" || echo "WARN: cloudwatch install failed"
RUN uv pip install --system "awslabs.ecs-mcp-server" || echo "WARN: ecs install failed"
RUN uv pip install --system "awslabs.lambda-tool-mcp-server" || echo "WARN: lambda-tool install failed"
RUN uv pip install --system "awslabs.iam-mcp-server" || echo "WARN: iam install failed"
RUN uv pip install --system "awslabs.cost-explorer-mcp-server" || echo "WARN: cost-explorer install failed"
RUN uv pip install --system "awslabs.bedrock-kb-retrieval-mcp-server" || echo "WARN: bedrock-kb install failed"

USER mcpuser
