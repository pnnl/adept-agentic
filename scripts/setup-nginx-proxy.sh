#!/bin/bash
# Setup script for NGINX proxy with api.agentic.local domain

set -e

echo "🚀 Setting up NGINX Public Proxy for Agentic Framework"

# Function to check if running as root/sudo
check_permissions() {
    if [ "$EUID" -ne 0 ]; then 
        echo "⚠️ This script requires sudo privileges to modify /etc/hosts"
        echo "Please run with: sudo $0"
        exit 1
    fi
}

# Function to add domain to /etc/hosts
setup_hosts_file() {
    local domain="api.agentic.local"
    local hosts_file="/etc/hosts"
    
    echo "📝 Configuring /etc/hosts for $domain..."
    
    # Check if domain already exists
    if grep -q "$domain" "$hosts_file"; then
        echo "✅ $domain already exists in $hosts_file"
    else
        # Add domain to hosts file
        echo "127.0.0.1 $domain" >> "$hosts_file"
        echo "✅ Added $domain to $hosts_file"
    fi
    
    # Verify the entry
    echo "🔍 Current $domain entries in $hosts_file:"
    grep "$domain" "$hosts_file" || echo "❌ No entries found"
}

# Function to create directories
setup_directories() {
    echo "📁 Creating certificate directories..."
    
    # Create local certs directory with proper permissions
    mkdir -p ./certs
    chmod 755 ./certs
    
    echo "✅ Certificate directory created: ./certs"
}

# Function to display usage information
show_usage_info() {
    echo ""
    echo "🎉 NGINX Proxy Setup Complete!"
    echo ""
    echo "Next Steps:"
    echo "1. Start services: make start"
    echo "2. Test NGINX proxy: make validate-nginx-proxy"
    echo "3. Use CLI with HTTPS: agentic chat (will use https://api.agentic.local/v1)"
    echo ""
    echo "Service URLs:"
    echo "  - Main API: https://api.agentic.local/v1/"
    echo "  - Authentication: https://api.agentic.local/auth/"
    echo "  - Health Check: https://api.agentic.local/health"
    echo ""
    echo "Notes:"
    echo "  - The CLI will automatically use the NGINX proxy endpoint"
    echo "  - Self-signed certificates are used for development"
    echo "  - SSL verification is disabled for *.agentic.local domains"
    echo ""
}

# Main execution
main() {
    echo "Starting NGINX proxy setup..."
    
    # Check if we need sudo for /etc/hosts modification
    if [ ! -w /etc/hosts ]; then
        check_permissions
    fi
    
    # Setup components
    setup_hosts_file
    setup_directories
    
    # Show usage information
    show_usage_info
    
    echo "✅ Setup complete! You can now start the services with 'make start'"
}

# Execute main function
main "$@"