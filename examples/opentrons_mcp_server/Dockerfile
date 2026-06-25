FROM agentic-framework-deps-base

USER root
WORKDIR /app

# Copy application code and fix permissions
COPY . /app/opentrons_mcp_server
RUN chmod -R a+rX /app/opentrons_mcp_server

# Drop back to non-root
USER 1000

# Expose port
EXPOSE 9003

# Run server as standalone package
CMD ["/app/.venv/bin/python", "-c", "import uvicorn; uvicorn.run('opentrons_mcp_server.main:app', host='0.0.0.0', port=9003)"]
