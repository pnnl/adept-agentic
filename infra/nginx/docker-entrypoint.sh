#!/bin/sh
# Docker entrypoint for NGINX proxy with certificate management

set -e

echo "Starting NGINX Public Proxy setup..."

# Generate certificates if they don't exist
echo "Checking certificates..."
/usr/local/bin/generate-certs.sh

# Process configuration templates
echo "Processing NGINX configuration templates..."
# Use envsubst to substitute environment variables in template
envsubst '${NGINX_RESOLVER} ${NGINX_PUBLIC_FQDN}' < /etc/nginx/templates/api.local.conf.template > /etc/nginx/conf.d/api.local.conf

# Test NGINX configuration
echo "Testing NGINX configuration..."
nginx -t

# Display startup information
echo "NGINX Public Proxy Configuration:"
echo "  Domain: api.agentic.local"
echo "  HTTP Port: 80 (redirects to HTTPS)"
echo "  HTTPS Port: 443"
echo "  Upstreams:"
echo "    - Keycloak: keycloak:8180"
echo "    - Agent Gateway: agent_gateway:8081"
echo "    - Orchestration Service: orchestration_service:8084"
echo ""
echo "Routes:"
echo "  - https://api.agentic.local/auth/* → Keycloak authentication"
echo "  - https://api.agentic.local/v1/* → Agent Gateway API"
echo "  - https://api.agentic.local/health → Health check"
echo ""

# Check if we can reach upstream services
echo "Checking upstream service connectivity..."

# Check Keycloak
if wget --spider --timeout=5 --tries=1 http://keycloak:8180/health/ready 2>/dev/null; then
    echo "  ✅ Keycloak is reachable"
else
    echo "  ⚠️ Keycloak is not yet available (this is normal during startup)"
fi

# Check Agent Gateway
if wget --spider --timeout=5 --tries=1 http://agent_gateway:8081/health 2>/dev/null; then
    echo "  ✅ Agent Gateway is reachable"
else
    echo "  ⚠️ Agent Gateway is not yet available (this is normal during startup)"
fi

echo ""
echo "🚀 Starting NGINX..."

# Execute the original NGINX entrypoint
exec "$@"