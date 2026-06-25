#!/bin/sh
# install-external-ca-certs.sh — Install external CA certificates into the Python
# certifi bundle, then exec the orchestration_service main process.
#
# Hybrid-cloud MCP servers (EMSL sandbox, partner labs, etc.) may use TLS
# certificates signed by private CAs. This script injects those CA certs into
# the Python certifi bundle so that httpx/fastmcp verify=True works
# transparently — no code changes needed.
#
# CA cert discovery (checked in order):
#   1. EXTRA_CA_CERTS_DIR env var — directory of .crt/.pem files (default: /usr/local/share/ca-certificates)
#   2. EMSL_SANDBOX_CA_CERT env var — single file path (backward compat)
#
# The script is idempotent — checks for markers before appending.
# Graceful no-op if no CA certs are found.
#
# Usage (in docker-compose.core.yaml):
#   command: ["/bin/sh", "/app/scripts/install-external-ca-certs.sh"]

set -e

EXTRA_CA_DIR="${EXTRA_CA_CERTS_DIR:-/usr/local/share/ca-certificates}"
CERTIFI_BUNDLE=""
INSTALLED=0

install_ca_cert() {
    cert_file="$1"
    label="$2"

    # Lazy-resolve certifi bundle path on first call
    if [ -z "$CERTIFI_BUNDLE" ]; then
        CERTIFI_BUNDLE=$(python3 -c "import certifi; print(certifi.where())" 2>/dev/null || true)
        if [ -z "$CERTIFI_BUNDLE" ]; then
            echo "[install-ca-certs] WARNING: certifi not found, skipping CA injection"
            return 1
        fi
    fi

    # Skip if already installed (idempotent marker)
    if grep -q "$label" "$CERTIFI_BUNDLE" 2>/dev/null; then
        echo "[install-ca-certs] $label already in certifi bundle (skipped)"
        return 0
    fi

    echo "" >> "$CERTIFI_BUNDLE"
    echo "# $label" >> "$CERTIFI_BUNDLE"
    cat "$cert_file" >> "$CERTIFI_BUNDLE"
    INSTALLED=$((INSTALLED + 1))
    echo "[install-ca-certs] $label appended to certifi bundle"
}

# 1. Scan EXTRA_CA_CERTS_DIR for .crt and .pem files
if [ -d "$EXTRA_CA_DIR" ]; then
    for cert in "$EXTRA_CA_DIR"/*.crt "$EXTRA_CA_DIR"/*.pem; do
        [ -f "$cert" ] || continue
        basename=$(basename "$cert")
        install_ca_cert "$cert" "External CA: $basename"
    done
fi

# 2. Backward compat: EMSL_SANDBOX_CA_CERT single-file path
EMSL_CA="${EMSL_SANDBOX_CA_CERT:-}"
if [ -n "$EMSL_CA" ] && [ -f "$EMSL_CA" ]; then
    install_ca_cert "$EMSL_CA" "EMSL Sandbox CA"
fi

# 3. System CA store update (best-effort, may fail without root)
if [ "$INSTALLED" -gt 0 ]; then
    if command -v update-ca-certificates >/dev/null 2>&1; then
        update-ca-certificates 2>/dev/null || true
    fi
    echo "[install-ca-certs] $INSTALLED CA cert(s) installed"
else
    echo "[install-ca-certs] No external CA certs found, continuing with defaults"
fi

# Exec the main process (replaces this shell with the Python process)
exec python -m agentic_framework_pkg.orchestration_service.main
