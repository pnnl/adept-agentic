#!/usr/bin/env bash
# =============================================================================
# generate-ca-and-certs.sh — Generate CA + server TLS certificates
# =============================================================================
# Creates a local CA and signs a server certificate for the AWS MCP Manager
# nginx proxy. Supports two deployment patterns:
#
#   1. Same-host:  ADEPT + AWS MCP Manager on the same Docker network
#      → Certs optional (HTTP works), but HTTPS available for consistency
#
#   2. Cross-host: AWS MCP Manager on a remote host (e.g., different EC2/HPC)
#      → Certs required. Copy certs/ca.crt to ADEPT host for trust store.
#
# Usage:
#   AWS_MCP_HOST_IP=10.0.0.1 ./scripts/generate-ca-and-certs.sh
#
# Environment:
#   AWS_MCP_HOST_IP    (required) Routable IP of the AWS MCP Manager host
#   AWS_MCP_EXTRA_DNS  (optional) Comma-separated extra DNS SANs
#   AWS_MCP_EXTRA_IPS  (optional) Comma-separated extra IP SANs
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CERT_DIR="$(cd "$(dirname "$0")/.." && pwd)/certs"
CA_KEY="${CERT_DIR}/ca.key"
CA_CERT="${CERT_DIR}/ca.crt"
SERVER_KEY="${CERT_DIR}/aws_mcp.key"
SERVER_CERT="${CERT_DIR}/aws_mcp.crt"
SERVER_CSR="${CERT_DIR}/aws_mcp.csr"
SERVER_EXT="${CERT_DIR}/aws_mcp.ext"

HOST_IP="${AWS_MCP_HOST_IP:?ERROR: Set AWS_MCP_HOST_IP to the routable IP of this host}"
EXTRA_DNS="${AWS_MCP_EXTRA_DNS:-}"
EXTRA_IPS="${AWS_MCP_EXTRA_IPS:-}"

# Org info
ORG_NAME="AWS MCP Manager"
CA_CN="AWS MCP Manager CA"
SERVER_CN="aws_mcp_nginx_proxy"

# ---------------------------------------------------------------------------
# Skip if certs exist and are valid (>24h remaining)
# ---------------------------------------------------------------------------
if [ -f "$SERVER_CERT" ] && openssl x509 -checkend 86400 -noout -in "$SERVER_CERT" 2>/dev/null; then
    echo "Certs exist and are valid for >24 hours. Skipping generation."
    echo "  CA cert:     ${CA_CERT}"
    echo "  Server cert: ${SERVER_CERT}"
    echo "  Server key:  ${SERVER_KEY}"
    echo ""
    echo "To force regeneration, delete certs/ and re-run."
    exit 0
fi

mkdir -p "$CERT_DIR"

# ---------------------------------------------------------------------------
# Step 1: Generate CA key + certificate (5-year validity)
# ---------------------------------------------------------------------------
if [ ! -f "$CA_KEY" ] || [ ! -f "$CA_CERT" ]; then
    echo "=== Generating CA key and certificate ==="
    openssl genrsa -out "$CA_KEY" 4096
    openssl req -x509 -new -nodes \
        -key "$CA_KEY" \
        -sha256 \
        -days 1825 \
        -out "$CA_CERT" \
        -subj "/C=US/ST=Cloud/L=AWS/O=${ORG_NAME}/CN=${CA_CN}"
    chmod 600 "$CA_KEY"
    chmod 644 "$CA_CERT"
    echo "  CA key:  ${CA_KEY}"
    echo "  CA cert: ${CA_CERT}"
else
    echo "CA key and cert already exist, reusing."
fi

# ---------------------------------------------------------------------------
# Step 2: Build Subject Alternative Names (SANs)
# ---------------------------------------------------------------------------
echo "=== Building SANs ==="

# Fixed entries
SAN_DNS="DNS.1 = ${SERVER_CN}\nDNS.2 = localhost"
SAN_IP="IP.1 = ${HOST_IP}\nIP.2 = 127.0.0.1\nIP.3 = 172.17.0.1\nIP.4 = 10.89.0.1"
DNS_IDX=3
IP_IDX=5

# Add extra DNS entries
if [ -n "$EXTRA_DNS" ]; then
    IFS=',' read -ra EXTRA_DNS_ARR <<< "$EXTRA_DNS"
    for dns in "${EXTRA_DNS_ARR[@]}"; do
        dns=$(echo "$dns" | xargs)  # trim whitespace
        SAN_DNS="${SAN_DNS}\nDNS.${DNS_IDX} = ${dns}"
        ((DNS_IDX++))
    done
fi

# Add extra IP entries
if [ -n "$EXTRA_IPS" ]; then
    IFS=',' read -ra EXTRA_IPS_ARR <<< "$EXTRA_IPS"
    for ip in "${EXTRA_IPS_ARR[@]}"; do
        ip=$(echo "$ip" | xargs)
        SAN_IP="${SAN_IP}\nIP.${IP_IDX} = ${ip}"
        ((IP_IDX++))
    done
fi

echo -e "  DNS SANs:\n$(echo -e "$SAN_DNS" | sed 's/^/    /')"
echo -e "  IP SANs:\n$(echo -e "$SAN_IP" | sed 's/^/    /')"

# ---------------------------------------------------------------------------
# Step 3: Generate server key + CSR
# ---------------------------------------------------------------------------
echo "=== Generating server key and CSR ==="
openssl genrsa -out "$SERVER_KEY" 2048
openssl req -new \
    -key "$SERVER_KEY" \
    -out "$SERVER_CSR" \
    -subj "/C=US/ST=Cloud/L=AWS/O=${ORG_NAME}/CN=${SERVER_CN}"

# ---------------------------------------------------------------------------
# Step 4: Create extensions file with SANs
# ---------------------------------------------------------------------------
cat > "$SERVER_EXT" <<EOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
subjectAltName=@alt_names

[alt_names]
$(echo -e "$SAN_DNS")
$(echo -e "$SAN_IP")
EOF

# ---------------------------------------------------------------------------
# Step 5: Sign server certificate with CA (1-year validity)
# ---------------------------------------------------------------------------
echo "=== Signing server certificate ==="
openssl x509 -req \
    -in "$SERVER_CSR" \
    -CA "$CA_CERT" \
    -CAkey "$CA_KEY" \
    -CAcreateserial \
    -out "$SERVER_CERT" \
    -days 365 \
    -sha256 \
    -extfile "$SERVER_EXT"

# ---------------------------------------------------------------------------
# Step 6: Set permissions and clean up
# ---------------------------------------------------------------------------
chmod 600 "$SERVER_KEY"
chmod 644 "$SERVER_CERT"
rm -f "$SERVER_CSR" "$SERVER_EXT" "${CERT_DIR}/ca.srl"

echo ""
echo "=== Certificate generation complete ==="
echo "  CA cert:     ${CA_CERT}  (copy to ADEPT host for cross-host trust)"
echo "  Server cert: ${SERVER_CERT}"
echo "  Server key:  ${SERVER_KEY}"
echo ""
echo "Verify:"
echo "  openssl x509 -in ${SERVER_CERT} -text -noout | grep -A1 'Subject Alternative Name'"
echo ""
echo "Cross-host setup:"
echo "  1. Copy certs/ca.crt to the ADEPT host"
echo "  2. Mount it in orchestration_service for trust verification"
echo "  3. Register tools using HTTPS: AWS_MCP_PROTO=https make register-tools"
