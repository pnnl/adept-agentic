FROM agentic-framework-deps-base:latest

USER appuser
WORKDIR /app

# Copy SDK source code first (needed for CLI entry points)
COPY --chown=appuser:appgroup src/agentic_framework_sdk /app/src/agentic_framework_sdk

# Copy bootstrap container code
COPY --chown=appuser:appgroup examples/demo-bootstrap/ ./examples/demo-bootstrap/

# Add SDK to PYTHONPATH and install CLI dependencies
ENV PYTHONPATH="/app/src"
RUN /app/.venv/bin/pip install --no-cache-dir click>=8.0.0 rich>=13.0.0 prompt-toolkit>=3.0.0

# Create agentic entry point wrapper script
RUN echo '#!/app/.venv/bin/python' > /app/.venv/bin/agentic && \
    echo 'import sys' >> /app/.venv/bin/agentic && \
    echo 'sys.path.insert(0, "/app/src")' >> /app/.venv/bin/agentic && \
    echo 'from agentic_framework_sdk.cli.main import cli' >> /app/.venv/bin/agentic && \
    echo 'if __name__ == "__main__":' >> /app/.venv/bin/agentic && \
    echo '    cli()' >> /app/.venv/bin/agentic && \
    chmod +x /app/.venv/bin/agentic

# Verify SDK is importable
RUN PYTHONPATH=/app/src /app/.venv/bin/python -c "import agentic_framework_sdk; print('SDK version:', agentic_framework_sdk.__version__)"

# Install certbot for Let's Encrypt (via apt requires root temporarily)
USER root
RUN apt-get update && \
    apt-get install -y certbot python3-certbot-nginx && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*
USER appuser

# Set PATH to include venv binaries
ENV PATH="/app/.venv/bin:$PATH"

# Expose port for health checks
EXPOSE 9100

# Verify agentic CLI is functional
RUN agentic --help >/dev/null 2>&1

# Set entrypoint to python with bootstrap script
ENTRYPOINT ["/app/.venv/bin/python", "/app/examples/demo-bootstrap/bootstrap_main.py"]

# Default command shows help
CMD ["--help"]
