#!/usr/bin/env bash
# Generate self-signed TLS certificates for the {{DISPLAY_NAME}} nginx proxy.
#
# Usage: ./generate-certs.sh [output_dir]
# Default output: ./certs/

set -euo pipefail

CERT_DIR="${1:-$(dirname "$0")/../certs}"
mkdir -p "$CERT_DIR"

echo "Generating self-signed TLS certificate..."

openssl req -x509 -nodes \
    -days 365 \
    -newkey rsa:2048 \
    -keyout "$CERT_DIR/server.key" \
    -out "$CERT_DIR/server.crt" \
    -subj "/CN={{NAME}}-mcp/O=ADEPT/C=US" \
    -addext "subjectAltName=DNS:{{NAME}}_nginx_proxy,DNS:localhost,IP:127.0.0.1"

chmod 644 "$CERT_DIR/server.crt"
chmod 600 "$CERT_DIR/server.key"

echo "Certificates written to $CERT_DIR/"
echo "  $CERT_DIR/server.crt"
echo "  $CERT_DIR/server.key"
