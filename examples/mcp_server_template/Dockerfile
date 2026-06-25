FROM agentic-framework-deps-base

USER root
WORKDIR /app

# Install domain-specific dependencies
COPY requirements.txt /tmp/requirements.txt
RUN /app/.venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# Copy application code
COPY {{NAME}}_mcp/ /app/{{NAME}}_mcp/
RUN chmod -R a+rX /app/{{NAME}}_mcp

# Run as appuser (UID/GID 1200, created in os-base image)
USER appuser

EXPOSE {{MCP_PORT}}

CMD ["/app/.venv/bin/python", "-c", "import uvicorn; uvicorn.run('{{NAME}}_mcp.app:app', host='0.0.0.0', port={{MCP_PORT}})"]
