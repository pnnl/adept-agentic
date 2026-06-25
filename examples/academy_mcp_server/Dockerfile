FROM agentic-framework-deps-base:latest

USER root
WORKDIR /app

# Install Academy and other dependencies not in base image
COPY requirements.txt /tmp/requirements.txt
RUN /app/.venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# Copy application code and fix permissions
COPY . /app/academy_mcp_server
RUN chmod -R a+rX /app/academy_mcp_server

# Drop back to non-root (matches os-base appuser UID/GID 1200:1200)
USER appuser

# Expose port
EXPOSE 9004

# Run server as standalone package
CMD ["/app/.venv/bin/python", "-c", "import uvicorn; uvicorn.run('academy_mcp_server.main:app', host='0.0.0.0', port=9004)"]
