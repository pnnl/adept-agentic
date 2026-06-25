#!/bin/bash
# generate-ca-and-certs.sh — Generate a local CA and server certificate for the
# Slurm HPC nginx proxy TLS termination.
#
# Creates:
#   certs/ca.key       — CA private key (keep secure, never distribute)
#   certs/ca.crt       — CA certificate (distribute to ADEPT host for trust store)
#   certs/slurm.key    — Server private key
#   certs/slurm.crt    — Server certificate signed by the CA
#
# The CA cert (ca.crt) must be copied to the ADEPT host and mounted into the
# orchestration_service container so that httpx/fastmcp can verify the server
# cert without any code changes (transparent trust via install-external-ca-certs.sh).
#
# Environment:
#   SLURM_HOST_IP    — (REQUIRED) The host's routable IP address for SAN entry.
#                      This is the IP that remote clients (ADEPT EC2) use to reach this host.
#   SLURM_EXTRA_DNS  — Optional extra DNS SAN entries (comma-separated)
#   SLURM_EXTRA_IPS  — Optional extra IP SAN entries (comma-separated)
#
# Usage:
#   SLURM_HOST_IP=10.0.1.50 bash scripts/generate-ca-and-certs.sh
#   # or via Makefile:
#   SLURM_HOST_IP=10.0.1.50 make generate-certs
#
# To regenerate server cert only (keep CA), delete slurm.crt + slurm.key and re-run.

set -euo pipefail

SLURM_HOST_IP="${SLURM_HOST_IP:-}"
if [ -z "$SLURM_HOST_IP" ]; then
    echo "ERROR: SLURM_HOST_IP is required."
    echo "  This is the host's routable IP that remote clients use to reach this server."
    echo "  Example: SLURM_HOST_IP=10.0.1.50 $0"
    echo "  Auto-detect: SLURM_HOST_IP=\$(hostname -I | awk '{print \$1}') $0"
    exit 1
fi

CERT_DIR="$(cd "$(dirname "$0")/.." && pwd)/certs"
mkdir -p "$CERT_DIR"

# Skip if certs exist and are valid (not expiring within 24h)
if [ -f "$CERT_DIR/slurm.crt" ] && openssl x509 -checkend 86400 -noout -in "$CERT_DIR/slurm.crt" 2>/dev/null; then
    echo "Certs exist and are valid. To regenerate, delete certs/ and re-run."
    exit 0
fi

# 1. Generate CA key + cert (if not already present)
if [ ! -f "$CERT_DIR/ca.key" ]; then
    echo "Generating CA key and certificate..."
    openssl genrsa -out "$CERT_DIR/ca.key" 4096
    openssl req -x509 -new -nodes -key "$CERT_DIR/ca.key" \
        -sha256 -days 1825 -out "$CERT_DIR/ca.crt" \
        -subj "/C=US/ST=WA/O=Slurm HPC/CN=Slurm HPC CA"
    echo "CA generated: $CERT_DIR/ca.crt (valid 5 years)"
fi

# 2. Generate server key + CSR
echo "Generating server key and CSR..."
openssl genrsa -out "$CERT_DIR/slurm.key" 2048
openssl req -new -key "$CERT_DIR/slurm.key" \
    -out "$CERT_DIR/slurm.csr" \
    -subj "/C=US/ST=WA/O=Slurm HPC/CN=slurm_nginx_proxy"

# 3. Sign server cert with CA (SAN extensions for host IP + internal addresses)
#    Build SAN dynamically: host IP first, then fixed internal entries, then extras.
DNS_COUNT=2
IP_COUNT=4

SAN_BLOCK="[alt_names]
DNS.1=slurm_nginx_proxy
DNS.2=localhost
IP.1=${SLURM_HOST_IP}
IP.2=127.0.0.1
IP.3=172.17.0.1
IP.4=10.89.0.1"

# Append extra DNS entries (comma-separated)
if [ -n "${SLURM_EXTRA_DNS:-}" ]; then
    IFS=',' read -ra EXTRA_DNS <<< "$SLURM_EXTRA_DNS"
    for dns in "${EXTRA_DNS[@]}"; do
        DNS_COUNT=$((DNS_COUNT + 1))
        SAN_BLOCK="${SAN_BLOCK}
DNS.${DNS_COUNT}=$(echo "$dns" | xargs)"
    done
fi

# Append extra IP entries (comma-separated)
if [ -n "${SLURM_EXTRA_IPS:-}" ]; then
    IFS=',' read -ra EXTRA_IPS <<< "$SLURM_EXTRA_IPS"
    for ip in "${EXTRA_IPS[@]}"; do
        IP_COUNT=$((IP_COUNT + 1))
        SAN_BLOCK="${SAN_BLOCK}
IP.${IP_COUNT}=$(echo "$ip" | xargs)"
    done
fi

echo "SAN entries:"
echo "$SAN_BLOCK" | grep -E "^(DNS|IP)\."

cat > "$CERT_DIR/slurm.ext" <<EOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
subjectAltName=@alt_names
${SAN_BLOCK}
EOF

openssl x509 -req -in "$CERT_DIR/slurm.csr" \
    -CA "$CERT_DIR/ca.crt" -CAkey "$CERT_DIR/ca.key" \
    -CAcreateserial -out "$CERT_DIR/slurm.crt" \
    -days 365 -sha256 -extfile "$CERT_DIR/slurm.ext"

# 4. Cleanup intermediates
rm -f "$CERT_DIR/slurm.csr" "$CERT_DIR/slurm.ext" "$CERT_DIR/ca.srl"

# 5. Set permissions
chmod 600 "$CERT_DIR/ca.key" "$CERT_DIR/slurm.key"
chmod 644 "$CERT_DIR/ca.crt" "$CERT_DIR/slurm.crt"

echo ""
echo "Certificates generated in: $CERT_DIR"
echo "  ca.crt     — CA certificate (copy to ADEPT host for trust store installation)"
echo "  ca.key     — CA private key (keep secure)"
echo "  slurm.crt  — Server certificate (used by nginx)"
echo "  slurm.key  — Server private key (used by nginx)"
echo ""
echo "Next step: Copy ca.crt to ADEPT host at examples/slurm_hpc/certs/ca.crt"
