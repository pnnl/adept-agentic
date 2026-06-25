#!/bin/sh
# Docker entrypoint for NGINX proxy in Swarm mode with dynamic service names

set -e

echo "Starting NGINX Proxy for stack: ${STACK_NAME}"

# Generate self-signed certificates if they don't exist
if [ ! -f /etc/nginx/certs/server.crt ] || [ ! -f /etc/nginx/certs/server.key ]; then
    echo "Generating self-signed certificates..."
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout /etc/nginx/certs/server.key \
        -out /etc/nginx/certs/server.crt \
        -subj "/C=US/ST=State/L=City/O=Organization/CN=api.agentic.local"
fi

# Create nginx configuration with proper service names for Swarm
echo "Processing NGINX configuration template..."
cat > /etc/nginx/nginx.conf <<EOF
user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log warn;
pid /var/run/nginx.pid;

events {
    worker_connections 1024;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    
    log_format main '\$remote_addr - \$remote_user [\$time_local] "\$request" '
                    '\$status \$body_bytes_sent "\$http_referer" '
                    '"\$http_user_agent" "\$http_x_forwarded_for"';
    
    access_log /var/log/nginx/access.log main;
    
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;
    
    # Docker's internal DNS resolver
    resolver 127.0.0.11 valid=30s;
    
    # HTTPS Server
    server {
        listen 443 ssl;
        listen [::]:443 ssl;
        server_name api.agentic.local;
        
        ssl_certificate /etc/nginx/certs/server.crt;
        ssl_certificate_key /etc/nginx/certs/server.key;
        
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers HIGH:!aNULL:!MD5;
        ssl_prefer_server_ciphers on;
        
        # Agent Gateway API
        location /v1/ {
            proxy_pass http://${STACK_NAME}_gateway:8081;
            proxy_set_header Host \$host;
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \$scheme;
        }
        
        # Keycloak Authentication
        location /auth/ {
            proxy_pass http://${STACK_NAME}_keycloak:8180/;
            proxy_set_header Host \$host;
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \$scheme;
        }
        
        # Gateway Registry
        location /internal/registry/ {
            proxy_pass http://${STACK_NAME}_gateway_registry:8086/v1/;
            proxy_set_header Host \$host;
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \$scheme;
        }
        
        # Health check
        location /health {
            access_log off;
            return 200 "healthy\\n";
            add_header Content-Type text/plain;
        }
    }
    
    # HTTP Server - Redirect to HTTPS
    server {
        listen 80;
        listen [::]:80;
        server_name api.agentic.local;
        
        # Health check endpoint (available on HTTP)
        location /health {
            access_log off;
            return 200 "healthy\\n";
            add_header Content-Type text/plain;
        }
        
        # Redirect all other traffic to HTTPS
        location / {
            return 301 https://\$server_name\$request_uri;
        }
    }
}
EOF

echo "Configuration processed for stack: ${STACK_NAME}"

# Test configuration
echo "Testing NGINX configuration..."
nginx -t

# Start nginx
echo "Starting NGINX..."
exec nginx -g "daemon off;"