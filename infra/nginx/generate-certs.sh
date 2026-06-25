#!/bin/sh
# Generate self-signed certificates for api.agentic.local
#
# Environment variables:
#   NGINX_EXTRA_SANS - Comma-separated list of additional SANs to include.
#                      DNS names and IP addresses are auto-detected.
#                      Example: NGINX_EXTRA_SANS=myhost.example.com,10.0.1.50

set -e

CERT_DIR="/etc/nginx/certs"
DOMAIN="api.agentic.local"

# Create certs directory if it doesn't exist
mkdir -p "$CERT_DIR"

# Check if certificate already exists and is valid
if [ -f "$CERT_DIR/$DOMAIN.crt" ] && [ -f "$CERT_DIR/$DOMAIN.key" ]; then
    # Check if certificate is still valid (not expired)
    if openssl x509 -checkend 86400 -noout -in "$CERT_DIR/$DOMAIN.crt" 2>/dev/null; then
        # If NGINX_EXTRA_SANS changed, regenerate even if cert is valid
        if [ -z "$NGINX_EXTRA_SANS" ]; then
            echo "Certificate for $DOMAIN already exists and is valid"
            exit 0
        fi
        # Check if current cert already has the requested SANs
        CURRENT_SANS=$(openssl x509 -in "$CERT_DIR/$DOMAIN.crt" -text -noout 2>/dev/null | grep -A1 "Subject Alternative Name" | tail -1)
        MISSING_SAN=""
        IFS=',' ; for san in $NGINX_EXTRA_SANS; do
            san=$(echo "$san" | xargs)  # trim whitespace
            if ! echo "$CURRENT_SANS" | grep -qi "$san"; then
                MISSING_SAN="yes"
                break
            fi
        done
        unset IFS
        if [ -z "$MISSING_SAN" ]; then
            echo "Certificate for $DOMAIN already exists, is valid, and includes all requested SANs"
            exit 0
        else
            echo "Certificate missing requested SAN ($san), regenerating..."
        fi
    else
        echo "Certificate for $DOMAIN exists but is expired, regenerating..."
    fi
fi

echo "Generating self-signed certificate for $DOMAIN..."

# Generate private key
openssl genrsa -out "$CERT_DIR/$DOMAIN.key" 2048

# Build the extra SANs entries from NGINX_EXTRA_SANS env var
EXTRA_SANS=""
DNS_IDX=4
IP_IDX=3
if [ -n "$NGINX_EXTRA_SANS" ]; then
    IFS=',' ; for san in $NGINX_EXTRA_SANS; do
        san=$(echo "$san" | xargs)  # trim whitespace
        [ -z "$san" ] && continue
        # Detect IP addresses vs DNS names
        if echo "$san" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
            EXTRA_SANS="${EXTRA_SANS}IP.${IP_IDX} = ${san}\n"
            IP_IDX=$((IP_IDX + 1))
        else
            EXTRA_SANS="${EXTRA_SANS}DNS.${DNS_IDX} = ${san}\n"
            DNS_IDX=$((DNS_IDX + 1))
        fi
    done
    unset IFS
fi

# Generate certificate signing request configuration
cat > "$CERT_DIR/$DOMAIN.conf" <<EOF
[req]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
req_extensions = v3_req

[dn]
C=US
ST=Local
L=Development
O=Agentic Framework
OU=Development
CN=$DOMAIN

[v3_req]
basicConstraints = CA:FALSE
keyUsage = nonRepudiation, digitalSignature, keyEncipherment
subjectAltName = @alt_names

[alt_names]
DNS.1 = $DOMAIN
DNS.2 = localhost
DNS.3 = *.agentic.local
IP.1 = 127.0.0.1
IP.2 = 0.0.0.0
$(printf '%b' "$EXTRA_SANS")
EOF

# Generate certificate
openssl req -new -x509 -key "$CERT_DIR/$DOMAIN.key" \
    -out "$CERT_DIR/$DOMAIN.crt" \
    -days 365 \
    -config "$CERT_DIR/$DOMAIN.conf" \
    -extensions v3_req

# Set appropriate permissions
chmod 600 "$CERT_DIR/$DOMAIN.key"
chmod 644 "$CERT_DIR/$DOMAIN.crt"
chown nginx:nginx "$CERT_DIR/$DOMAIN.key" "$CERT_DIR/$DOMAIN.crt" 2>/dev/null || true

# Clean up config file
rm -f "$CERT_DIR/$DOMAIN.conf"

echo "Certificate generated successfully:"
echo "  Certificate: $CERT_DIR/$DOMAIN.crt"
echo "  Private key: $CERT_DIR/$DOMAIN.key"

# Display certificate info
echo -e "\nCertificate information:"
openssl x509 -in "$CERT_DIR/$DOMAIN.crt" -text -noout | grep -A 2 "Subject:"
openssl x509 -in "$CERT_DIR/$DOMAIN.crt" -text -noout | grep -A 1 "Not Before"
openssl x509 -in "$CERT_DIR/$DOMAIN.crt" -text -noout | grep -A 5 "Subject Alternative Name"