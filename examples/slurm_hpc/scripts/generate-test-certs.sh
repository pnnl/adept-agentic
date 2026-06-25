#!/usr/bin/env bash
# Generate self-signed test certificates for slurm_hpc TLS proxy tests.
# Does NOT require SLURM_HOST_IP — uses Docker network hostnames as SANs.
# Idempotent: skips if valid certs already exist (< 24h before expiry).
set -euo pipefail

CERT_DIR="${1:-certs}"
mkdir -p "$CERT_DIR"

if [ -f "$CERT_DIR/slurm.crt" ] && openssl x509 -checkend 86400 -noout -in "$CERT_DIR/slurm.crt" 2>/dev/null; then
    echo "Test certs exist and are valid. Delete $CERT_DIR/ to regenerate."
    exit 0
fi

echo "Creating CA key + certificate..."
openssl genrsa -out "$CERT_DIR/ca.key" 4096 2>/dev/null
openssl req -x509 -new -nodes -key "$CERT_DIR/ca.key" \
    -sha256 -days 365 -out "$CERT_DIR/ca.crt" \
    -subj "/C=US/ST=WA/O=Slurm HPC Test/CN=Slurm HPC Test CA"

echo "Creating server key + certificate..."
openssl genrsa -out "$CERT_DIR/slurm.key" 2048 2>/dev/null
openssl req -new -key "$CERT_DIR/slurm.key" \
    -out "$CERT_DIR/slurm.csr" \
    -subj "/C=US/ST=WA/O=Slurm HPC Test/CN=slurm_nginx_proxy"

cat > "$CERT_DIR/_ext.cnf" <<EOF
[v3_ext]
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
subjectAltName=DNS:slurm_nginx_proxy,DNS:localhost,IP:127.0.0.1,IP:172.17.0.1
EOF

openssl x509 -req -in "$CERT_DIR/slurm.csr" \
    -CA "$CERT_DIR/ca.crt" -CAkey "$CERT_DIR/ca.key" \
    -CAcreateserial -out "$CERT_DIR/slurm.crt" \
    -days 365 -sha256 -extfile "$CERT_DIR/_ext.cnf" -extensions v3_ext

rm -f "$CERT_DIR/slurm.csr" "$CERT_DIR/_ext.cnf" "$CERT_DIR/ca.srl"
chmod 600 "$CERT_DIR/ca.key" "$CERT_DIR/slurm.key"
chmod 644 "$CERT_DIR/ca.crt" "$CERT_DIR/slurm.crt"

echo "Test certs generated in $CERT_DIR/"
