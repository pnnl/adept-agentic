#!/usr/bin/env bash
# =============================================================================
# install-aws-server.sh — Install an AWS MCP server into the container at runtime
# =============================================================================
# Usage: install-aws-server <package-name>
# Example: install-aws-server awslabs.s3-tables-mcp-server
set -euo pipefail

PACKAGE="${1:?Usage: install-aws-server <package-name>}"

echo "Installing AWS MCP server: ${PACKAGE}"
pip install --no-cache-dir "${PACKAGE}" 2>&1
echo "Successfully installed: ${PACKAGE}"
