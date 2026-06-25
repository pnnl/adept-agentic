# Lightweight MCP server for SLURM cluster management
# Runs as non-root user with health check support

FROM python:3.12.13-slim-bookworm

LABEL org.opencontainers.image.title="slurm-mcp-server" \
      org.opencontainers.image.description="FastMCP server for SLURM HPC cluster management" \
      maintainer="ADEPT Framework"

# Install Docker CLI for E2E tests that exec into Slurm containers
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg && \
    install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list && \
    apt-get update && apt-get install -y --no-install-recommends docker-ce-cli && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Create non-root user with docker group access for E2E tests
RUN groupadd -r mcpuser && useradd -r -g mcpuser -d /app mcpuser && \
    groupadd -f docker && usermod -aG docker mcpuser

WORKDIR /app

# Install Python dependencies (runtime + test)
COPY requirements.txt requirements-test.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-test.txt

# Copy application code
COPY slurm_mcp/ ./slurm_mcp/

# Switch to non-root user
USER mcpuser

# Default port
EXPOSE 8002

HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=15s \
    CMD python -c "import socket; s=socket.create_connection(('localhost',8002),2); s.close()" || exit 1

ENTRYPOINT ["python", "-m", "slurm_mcp"]
CMD ["--transport", "streamable-http", "--port", "8002", "--host", "0.0.0.0"]
