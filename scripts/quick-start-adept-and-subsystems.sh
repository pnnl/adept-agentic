#!/bin/bash
# Complete stack startup with observability (25-30 minutes)
# Auto-detects AWS EC2 and applies Docker Hub rate limit mitigation
set -e  # Exit on error

echo "🚀 Starting complete ADEPT stack with Langfuse observability..."
echo "⏱️  Estimated time: 25-30 minutes"
echo ""

# Detect AWS EC2 environment
IS_AWS_EC2=false
if curl -s -m 2 http://169.254.169.254/latest/meta-data/instance-id &>/dev/null; then
    IS_AWS_EC2=true
    echo "☁️  AWS EC2 detected - enabling rate limit mitigation"
    echo ""
fi

# AWS-specific: Docker Hub rate limit mitigation
if [[ "$IS_AWS_EC2" == "true" ]]; then
    echo "🔐 Phase 0a: AWS Docker Hub Rate Limit Check..."

    # Check authentication status
    if docker info 2>&1 | grep -q "Username:"; then
        echo "  ✅ Docker Hub authenticated (200 pulls/6h)"
    else
        echo "  ⚠️  Docker Hub not authenticated (100 pulls/6h limit)"
        echo ""
        echo "AWS EC2 shares IPs, making rate limits likely. Recommend:"
        echo "  ./scripts/aws-docker-hub-auth.sh"
        echo ""

        # Check if running in interactive mode (stdin is a terminal)
        if [[ -t 0 ]]; then
            # Interactive mode - prompt user
            read -p "Authenticate with Docker Hub now? (y/N) " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                ./scripts/aws-docker-hub-auth.sh || {
                    echo "⚠️  Authentication failed, continuing anyway..."
                    sleep 2
                }
            else
                echo "⚠️  Proceeding without auth. Build may fail due to rate limits."
                echo "   If build fails, run: ./scripts/aws-docker-hub-auth.sh"
                sleep 3
            fi
        else
            # Non-interactive mode (e.g., nohup, background job)
            echo "⚠️  Non-interactive mode detected (stdin not available)"
            echo "   Skipping authentication prompt."
            echo "   To authenticate, run: ./scripts/aws-docker-hub-auth.sh before this script"
            echo ""
            echo "⚠️  Proceeding without auth. Build may fail due to rate limits."
            echo "   If build fails, run: ./scripts/aws-docker-hub-auth.sh"
            sleep 3
        fi
    fi
    echo ""

    # Pre-cache critical images
    echo "📦 Phase 0b: Pre-caching critical images (AWS optimization)..."
    ./scripts/aws-build-helper.sh --precache || {
        echo "⚠️  Pre-caching had issues, continuing..."
    }
    echo ""
fi

# 0. Pre-flight: Fix permissions for bootstrap volume mounts and check .env symlink
echo "📋 Phase 0c: Pre-flight permission checks and .env symlink validation..."
# Bootstrap containers (UID 105) need write access to these paths
# .env: Langfuse bootstrap appends credentials (NEVER overwrites)
# .env-keycloak-credentials-dir/*: Keycloak bootstrap regenerates files
if [[ -f .env ]]; then
    chmod 644 .env 2>/dev/null && echo "  ✅ Fixed .env permissions (644)" || echo "  ⚠️  Could not fix .env permissions"
fi
if [[ -d .env-keycloak-credentials-dir ]]; then
    chmod 755 .env-keycloak-credentials-dir 2>/dev/null && echo "  ✅ Fixed credentials directory permissions (755)" || true
    chmod 755 .env-keycloak-credentials-dir/* 2>/dev/null && echo "  ✅ Fixed credential files permissions (755)" || true
fi

# Check and create .env symlink for docker-compose
# Docker Compose needs access to .env from deployment/local/docker-compose/ directory
if [[ ! -L deployment/local/docker-compose/.env ]]; then
    echo "  ⚠️  Creating missing .env symlink for docker-compose..."
    mkdir -p deployment/local/docker-compose
    ln -sf ../../../.env deployment/local/docker-compose/.env
    echo "  ✅ .env symlink created"
elif [[ ! -e deployment/local/docker-compose/.env ]]; then
    echo "  ⚠️  .env symlink is broken, recreating..."
    rm -f deployment/local/docker-compose/.env
    ln -sf ../../../.env deployment/local/docker-compose/.env
    echo "  ✅ .env symlink recreated"
else
    echo "  ✅ .env symlink exists and is valid"
fi

# Check and create .env-keycloak-credentials-dir symlink for docker-compose
# Docker Compose needs access to credential directory from deployment/local/docker-compose/
if [[ ! -L deployment/local/docker-compose/.env-keycloak-credentials-dir ]]; then
    echo "  ⚠️  Creating missing .env-keycloak-credentials-dir symlink for docker-compose..."
    mkdir -p deployment/local/docker-compose
    ln -sf ../../../.env-keycloak-credentials-dir deployment/local/docker-compose/.env-keycloak-credentials-dir
    echo "  ✅ .env-keycloak-credentials-dir symlink created"
elif [[ ! -e deployment/local/docker-compose/.env-keycloak-credentials-dir ]]; then
    echo "  ⚠️  .env-keycloak-credentials-dir symlink is broken, recreating..."
    rm -f deployment/local/docker-compose/.env-keycloak-credentials-dir
    ln -sf ../../../.env-keycloak-credentials-dir deployment/local/docker-compose/.env-keycloak-credentials-dir
    echo "  ✅ .env-keycloak-credentials-dir symlink recreated"
else
    echo "  ✅ .env-keycloak-credentials-dir symlink exists and is valid"
fi

# Create required data subdirectories for Docker bind mounts
# These directories must exist before Docker Compose starts services
echo "Ensuring required data subdirectories exist..."
mkdir -p data/{postgres_data,postgres_rag_data,redis_data,uploaded_files,nginx_certs,n8n_data,openwebui_data,mgmt_ui_data,ragflow,ragflow_data,ragflow_sessions,sandbox_workspace,hpc_workspace,langfuse,vector_db_persistence}
echo "  ✅ Created/verified all required data subdirectories"

# Redis data directory needs world-writable permissions (Redis runs as root in container)
if [[ -d data/redis_data ]]; then
    chmod 777 data/redis_data 2>/dev/null && echo "  ✅ Fixed redis_data permissions (777 for Redis persistence)" || true
fi

# Fix data/ directory permissions for Docker containers (postgres UID 999, n8n UID 1000, etc.)
# Containers need write access to bind-mounted directories.
# After a sudo-docker era, files may be owned by container UIDs (999, 1000, 1200)
# with restrictive permissions. Non-sudo chmod will fail on those, so we escalate
# to sudo as a fallback.
if [[ -d data ]]; then
    if chmod -R a+rwX data 2>/dev/null; then
        echo "  ✅ Fixed data/ directory permissions (a+rwX, recursive)"
    else
        echo "  ⚠️  Non-sudo chmod failed — escalating to sudo for container-owned files..."
        if sudo chmod -R a+rwX data 2>/dev/null; then
            echo "  ✅ Fixed data/ directory permissions via sudo (a+rwX, recursive)"
        else
            echo "  ⚠️  sudo chmod also failed — listing problem directories:"
            CURRENT_UID=$(id -u)
            find data -type d ! -perm -o+rwx 2>/dev/null | head -10 | while read -r dir; do
                OWNER_UID=$(stat -c '%u' "$dir" 2>/dev/null)
                echo "     - $dir (UID: $OWNER_UID, perms: $(stat -c '%a' "$dir" 2>/dev/null))"
            done
            echo ""
            echo "  🔧 Manual fix: sudo chmod -R a+rwX data/"
        fi
    fi
fi

# Check and create data symlink for docker-compose
# Docker Compose needs access to data/ from deployment/local/docker-compose/ directory
if [[ ! -L deployment/local/docker-compose/data ]]; then
    echo "  ⚠️  Creating missing data symlink for docker-compose..."
    # Remove existing real directory if present (safety check)
    if [[ -d deployment/local/docker-compose/data ]] && [[ ! -L deployment/local/docker-compose/data ]]; then
        echo "  ⚠️  Found real data/ directory in compose, removing to create symlink..."
        rm -rf deployment/local/docker-compose/data
    fi
    mkdir -p deployment/local/docker-compose
    ln -sf ../../../data deployment/local/docker-compose/data
    echo "  ✅ data symlink created"
elif [[ ! -e deployment/local/docker-compose/data ]]; then
    echo "  ⚠️  data symlink is broken, recreating..."
    rm -f deployment/local/docker-compose/data
    ln -sf ../../../data deployment/local/docker-compose/data
    echo "  ✅ data symlink recreated"
else
    echo "  ✅ data symlink exists and is valid"
fi

# Fix scripts/ directory permissions for Docker containers
# Containers need read/execute access to bind-mounted script files
if [[ -d scripts ]]; then
    if chmod -R a+rx scripts 2>/dev/null; then
        echo "  ✅ Fixed scripts/ directory and file permissions (a+rx, recursive)"
    else
        echo "  ⚠️  Could not fix scripts/ permissions"
    fi
fi

# Validate nginx cert/key pair consistency (prevents key values mismatch on startup)
if [ -f "data/nginx_certs/api.agentic.local.crt" ] && [ -f "data/nginx_certs/api.agentic.local.key" ]; then
    CERT_MOD=$(openssl x509 -noout -modulus -in data/nginx_certs/api.agentic.local.crt 2>/dev/null | md5sum | cut -d' ' -f1)
    KEY_MOD=$(openssl rsa -noout -modulus -in data/nginx_certs/api.agentic.local.key 2>/dev/null | md5sum | cut -d' ' -f1)
    if [ "$CERT_MOD" != "$KEY_MOD" ]; then
        echo "  ⚠️  nginx cert/key mismatch detected — clearing for regeneration"
        rm -f data/nginx_certs/api.agentic.local.crt data/nginx_certs/api.agentic.local.key data/nginx_certs/adept-ca-bundle.pem
        echo "  ✅ Stale certs cleared (nginx will regenerate on start)"
    else
        echo "  ✅ nginx cert/key pair consistent"
    fi
fi

# Gurobi support check (informational only — not a blocking gate)
if [ -n "${SANDBOX_EXEC_USER:-}" ] && [ ! -f "data/uploaded_files/gurobi.lic" ] && [ ! -f "data/gurobi.lic" ]; then
    echo "  ℹ️  SANDBOX_EXEC_USER is set but no gurobi.lic found in data/ or data/uploaded_files/"
    echo "     Gurobi optimization will not be available. See docs/SYSTEMS_ADMINISTRATOR_ONBOARDING.md"
fi

# Auto-populate NGINX_EXTRA_SANS if not already set and host has a non-localhost IP
# This ensures the TLS cert includes the host's IP/FQDN so presigned URL downloads verify
if [[ -f .env ]] && ! grep -q "^NGINX_EXTRA_SANS=." .env; then
    HOST_IP=""
    if [[ "$IS_AWS_EC2" == "true" ]]; then
        HOST_IP=$(curl -s -m 2 http://169.254.169.254/latest/meta-data/local-ipv4 2>/dev/null || true)
    fi
    if [[ -z "$HOST_IP" ]]; then
        HOST_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
    fi
    if [[ -n "$HOST_IP" ]] && [[ "$HOST_IP" != "127.0.0.1" ]]; then
        # Also include the FQDN if it differs from the IP
        HOST_FQDN=$(hostname -f 2>/dev/null || true)
        EXTRA_SANS="$HOST_IP"
        if [[ -n "$HOST_FQDN" ]] && [[ "$HOST_FQDN" != "$HOST_IP" ]] && [[ "$HOST_FQDN" != "localhost" ]]; then
            EXTRA_SANS="$HOST_IP,$HOST_FQDN"
        fi
        sed -i "s|^NGINX_EXTRA_SANS=.*|NGINX_EXTRA_SANS=$EXTRA_SANS|" .env
        grep -q "^NGINX_EXTRA_SANS=" .env || echo "NGINX_EXTRA_SANS=$EXTRA_SANS" >> .env
        echo "  ✅ Set NGINX_EXTRA_SANS=$EXTRA_SANS (TLS cert will include host identity)"
    else
        echo "  ℹ️  No external IP detected, NGINX_EXTRA_SANS unchanged (localhost-only)"
    fi
fi
echo ""

# 1. Clean slate
echo "🧹 Phase 1: Complete cleanup..."
make stop && make langfuse-stop || true
make langfuse-destroy || true  # Ensure Langfuse volumes are cleaned

# Remove all containers to release volume locks
echo "Removing all containers to release volume locks..."
docker ps -a --format "{{.Names}}" | xargs -r docker rm -f 2>/dev/null || true

# Remove docker-compose volumes (may have cached old workspace paths)
echo "Removing docker-compose volumes with cached paths..."
docker volume ls -q | grep -E "(docker-compose|adept-)" | xargs -r docker volume rm 2>/dev/null || true

make erase

# 2. Infrastructure
echo "🏗️  Phase 2: Building infrastructure..."
# NOTE: Networks are now auto-created by docker-compose (Session 50 Phase 1)
# Three-tier network segmentation: frontend_net, application_net, data_net
#docker network create agentic_framework_network || true
make init-shared-docker-compose-network

# AWS-specific: Use retry logic for builds
if [[ "$IS_AWS_EC2" == "true" ]]; then
    echo "Building with automatic retry (AWS optimization)..."
    ./scripts/aws-build-helper.sh --build || {
        echo ""
        echo "❌ Build failed even with AWS retry logic"
        echo ""
        echo "Troubleshooting:"
        echo "1. Check rate limit: ./scripts/aws-build-helper.sh --check"
        echo "2. Authenticate: ./scripts/aws-docker-hub-auth.sh"
        echo "3. Wait 10-30 min and retry, or see: docs/AWS_DOCKER_HUB_MITIGATION.md"
        echo ""
        exit 1
    }
else
    make build  # Standard build for non-AWS environments
fi

# 3. Langfuse observability
echo "📊 Phase 3: Building and starting Langfuse observability..."
echo "   Checking Langfuse credentials..."
# Verify LangFuse credentials exist before starting services to prevent drift
if ! grep -q "^LANGFUSE_PUBLIC_KEY=pk-lf-" .env 2>/dev/null || \
   ! grep -q "^LANGFUSE_SECRET_KEY=sk-lf-" .env 2>/dev/null; then
    echo "⚠️  Missing or invalid LANGFUSE credentials in .env, regenerating..."
    make langfuse-regenerate
else
    echo "✅ LangFuse credentials present in .env"
fi
echo "   Building Langfuse images..."
make langfuse-build  # Build internalized images
echo "   Starting Langfuse services..."
make langfuse-start
echo "⏳ Waiting for Langfuse services to initialize..."
sleep 30  # Increased wait time for services to be ready
echo "   Initializing Langfuse with credentials and organization..."
make langfuse-init-complete  # Generate credentials AND initialize database

# These are explict, but we will want the to use the ’start’ target
# 4. Core services
#make rebuild-registry
#make rebuild-gateway
#make rebuild-orchestrator
#sleep 20

# 5. MCP servers
#make rebuild-mcp
#make rebuild-sandbox-mcp
#make rebuild-hpc-mcp

# 6. UI services
#make rebuild-streamlit-app-v2

# 4. Start ADEPT stack
echo "🎯 Phase 4: Starting ADEPT stack..."

# Fix keycloak credential directory permissions (needed for keycloak-setup bootstrap)
if [[ -d .env-keycloak-credentials-dir ]]; then
    chmod 755 .env-keycloak-credentials-dir 2>/dev/null || true
    chmod 666 .env-keycloak-credentials-dir/* 2>/dev/null && echo "📋 Fixed keycloak credentials permissions" || true
fi

# Re-create and fix permissions on data directories after cleanup
# This ensures all bind mount directories exist with correct permissions before starting services
echo "🔧 Ensuring data directories exist with correct permissions..."
mkdir -p data/{postgres_data,postgres_rag_data,redis_data,uploaded_files,nginx_certs,n8n_data,openwebui_data,mgmt_ui_data,ragflow,ragflow_data,ragflow_sessions,sandbox_workspace,hpc_workspace,langfuse,vector_db_persistence}
chmod -R a+rwx data 2>/dev/null || echo "⚠️  Could not set data permissions (may need sudo)"
echo "  ✅ Data directories ready for Docker bind mounts"

echo "⏳ Waiting for network to be ready..."
sleep 20
make start
echo "⏳ Waiting for all services to initialize (Keycloak, PostgreSQL, etc.)..."
sleep 30  # Increased wait for Keycloak initialization

# Discover KC_ADMIN_CLI_SECRET from Keycloak database (handles fresh DB after teardown -v)
# keycloak-setup may fail if the secret in .env is stale; this re-discovers the real one.
echo "🔑 Discovering KC_ADMIN_CLI_SECRET from Keycloak database..."
DISCOVERED_SECRET=""
if docker ps --format '{{.Names}}' | grep -q "^postgres$"; then
    POSTGRES_USER="${POSTGRES_USER:-admin}"
    POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-password}"
    DISCOVERED_SECRET=$(docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" postgres \
        psql -U "$POSTGRES_USER" -d keycloak \
        -c "SELECT secret FROM client WHERE client_id = 'admin-cli' AND realm_id = (SELECT id FROM realm WHERE name = 'master');" \
        -t -A 2>/dev/null | tr -d ' \n')
fi

if [[ -n "$DISCOVERED_SECRET" ]]; then
    echo "  ✅ Discovered KC_ADMIN_CLI_SECRET from database"
    # Write to credentials directory (files may be owned by container UIDs 1000/1200)
    CREDS_DIR="deployment/local/docker-compose/.env-keycloak-credentials-dir"
    mkdir -p "$CREDS_DIR"
    # Overwrite or create — handle container-owned files via tee (works with sudo)
    if echo -n "$DISCOVERED_SECRET" > "$CREDS_DIR/KC_ADMIN_CLI_SECRET" 2>/dev/null; then
        :
    else
        echo -n "$DISCOVERED_SECRET" | sudo tee "$CREDS_DIR/KC_ADMIN_CLI_SECRET" > /dev/null
        sudo chmod 666 "$CREDS_DIR/KC_ADMIN_CLI_SECRET"
    fi
    # Write to .env
    if grep -q "^KC_ADMIN_CLI_SECRET=" .env 2>/dev/null; then
        sed -i "s|^KC_ADMIN_CLI_SECRET=.*|KC_ADMIN_CLI_SECRET=$DISCOVERED_SECRET|" .env
    else
        echo "KC_ADMIN_CLI_SECRET=$DISCOVERED_SECRET" >> .env
    fi
    echo "  ✅ Written to credentials directory and .env"
else
    echo "  ⚠️  Could not discover secret (Keycloak may still be initializing)"
    echo "     Will retry during fix-credentials phase"
fi

# Sync KC_ADMIN_CLI_SECRET from credentials directory to main .env file
# This ensures Management UI (which loads from .env) has the correct secret after rebuild
sync_admin_cli_secret_to_env() {
    echo ""
    echo "🔄 Syncing KC_ADMIN_CLI_SECRET from credentials directory to .env file..."

    CREDS_DIR="deployment/local/docker-compose/.env-keycloak-credentials-dir"

    if [[ -f "$CREDS_DIR/KC_ADMIN_CLI_SECRET" ]]; then
        SECRET=$(cat "$CREDS_DIR/KC_ADMIN_CLI_SECRET")

        if [[ -n "$SECRET" ]]; then
            # Update or add KC_ADMIN_CLI_SECRET in .env file
            if grep -q "^KC_ADMIN_CLI_SECRET=" .env; then
                sed -i "s|^KC_ADMIN_CLI_SECRET=.*$|KC_ADMIN_CLI_SECRET=$SECRET|" .env
                echo "   ✅ Updated KC_ADMIN_CLI_SECRET in .env file"
            else
                echo "KC_ADMIN_CLI_SECRET=$SECRET" >> .env
                echo "   ✅ Added KC_ADMIN_CLI_SECRET to .env file"
            fi

            # Force-recreate Management UI to reload .env values
            echo "   🔄 Reloading Management UI container with updated credentials..."
            docker compose -f deployment/local/docker-compose/docker-compose.base.yaml \
                           -f deployment/local/docker-compose/docker-compose.core.yaml \
                           up -d agent_gateway_mgmt_ui --force-recreate >/dev/null 2>&1
            echo "   ✅ Management UI reloaded with fresh credentials"
        else
            echo "   ⚠️  KC_ADMIN_CLI_SECRET is empty in credentials directory"
        fi
    else
        echo "   ⚠️  KC_ADMIN_CLI_SECRET not found in credentials directory"
        echo "      This may indicate bootstrap did not complete successfully"
    fi
    echo ""
}

# Run credential sync after keycloak-setup completes
# This prevents Management UI 401 errors after rebuild (Session 44 bugfix)
sync_admin_cli_secret_to_env

# Generate CA bundle for test TLS verification
# Must run after nginx_proxy is up (Phase 4) so we can extract the self-signed cert
echo "🔒 Generating test CA bundle for validation containers..."
make generate-test-ca-bundle

# 5. Health checks and validation
echo "✅ Phase 5: Validating stack health..."

# Validate Management UI credentials and configuration
validate_mgmt_ui_credentials() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "🔐 MANAGEMENT UI CREDENTIAL VALIDATION"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    # Check 1: Verify mgmt-ui-client credentials exist in container
    echo "   Checking mgmt-ui-client credentials in container..."
    CLIENT_ID=$(docker exec agent_gateway_mgmt_ui env | grep "^KEYCLOAK_CLIENT_ID=" | cut -d'=' -f2)
    if [[ "$CLIENT_ID" == "mgmt-ui-client" ]]; then
        echo "   ✅ KEYCLOAK_CLIENT_ID: mgmt-ui-client"
    else
        echo "   ❌ KEYCLOAK_CLIENT_ID: ${CLIENT_ID:-NOT SET}"
        echo "      Expected: mgmt-ui-client"
        return 1
    fi

    # Check 2: Verify client secret file is mounted
    docker exec agent_gateway_mgmt_ui ls /run/secrets/KEYCLOAK_CLIENT_SECRET >/dev/null 2>&1 && \
        echo "   ✅ KEYCLOAK_CLIENT_SECRET file mounted" || \
        { echo "   ❌ KEYCLOAK_CLIENT_SECRET file not found"; return 1; }

    # Check 3: Verify mgmt-ui-client has group membership mapper in Keycloak
    echo "   Checking mgmt-ui-client protocol mappers in Keycloak..."
    MAPPER_COUNT=$(docker exec postgres psql -U admin -d keycloak -t -A -c \
        "SELECT COUNT(*) FROM client c JOIN protocol_mapper pm ON c.id = pm.client_id \
         WHERE c.client_id = 'mgmt-ui-client' AND pm.name = 'group membership';" 2>/dev/null || echo "0")

    if [[ "$MAPPER_COUNT" -eq 1 ]]; then
        echo "   ✅ mgmt-ui-client has group membership mapper"
    else
        echo "   ❌ mgmt-ui-client missing group membership mapper (count: $MAPPER_COUNT)"
        echo "      Run: make fix-credentials to regenerate"
        return 1
    fi

    # Check 4: Test actual authentication with admin user
    echo "   Testing admin user authentication..."
    AUTH_TEST=$(docker exec agent_gateway_mgmt_ui python3 -c "
from keycloak import KeycloakOpenID
import os
import sys

try:
    client_id = os.getenv('KEYCLOAK_CLIENT_ID', 'mgmt-ui-client')
    with open('/run/secrets/KEYCLOAK_CLIENT_SECRET', 'r') as f:
        client_secret = f.read().strip()

    keycloak_openid = KeycloakOpenID(
        server_url='http://keycloak:8180',
        client_id=client_id,
        realm_name='master',
        client_secret_key=client_secret
    )

    token = keycloak_openid.token('admin', 'admin')
    user_info = keycloak_openid.userinfo(token['access_token'])
    groups = user_info.get('groups', [])

    if 'admin' in groups:
        print('SUCCESS')
    else:
        print('FAIL_NO_ADMIN_GROUP')
except Exception as e:
    print(f'ERROR: {e}')
    sys.exit(1)
" 2>&1)

    if [[ "$AUTH_TEST" == "SUCCESS" ]]; then
        echo "   ✅ Admin authentication test passed"
        echo "   ✅ Groups claim includes 'admin'"
    else
        echo "   ❌ Admin authentication test failed: $AUTH_TEST"
        echo "      The Management UI will not allow admin login"
        return 1
    fi

    echo ""
    echo "   ✅ Management UI credentials properly configured"
    return 0
}

# Check if Langfuse is healthy before proceeding
echo "Checking Langfuse health..."
make langfuse-health || {
    echo "⚠️  Langfuse health check failed, attempting restart..."
    make langfuse-restart
    sleep 20
}

# Validate ADEPT services
make validate-service-health || {
    echo "⚠️  Service health validation failed, attempting credential fix..."
    make fix-credentials
    echo "Syncing credentials to validation directory..."
    make sync-credentials
    sleep 5
    make validate-service-health || echo "⚠️  Some services may need manual attention"
}

# Validate Management UI credentials and authentication
validate_mgmt_ui_credentials || {
    echo ""
    echo "⚠️  Management UI credential validation failed"
    echo "   Attempting automatic fix..."
    make fix-credentials
    make sync-credentials
    sleep 5
    make rebuild-gateway-mgmt-ui
    sleep 10

    # Retry validation
    validate_mgmt_ui_credentials || {
        echo ""
        echo "❌ Management UI still not properly configured after fix attempt"
        echo "   Manual intervention required:"
        echo "   1. Check Keycloak bootstrap logs: docker logs keycloak-setup"
        echo "   2. Verify mgmt-ui-client exists: docker exec postgres psql -U admin -d keycloak -c \"SELECT client_id FROM client WHERE client_id = 'mgmt-ui-client';\""
        echo "   3. Review documentation: docs/bugfixes/MANAGEMENT_UI_ADMIN_CLI_VS_MGMT_UI_CLIENT_FIX.md"
        echo ""
    }
}

# Validate MCP tool discovery
make validate-mcp-tools-discovery || echo "⚠️  MCP tool discovery may need manual attention"

# Validate Session 32 Phase 1 schema (non-blocking)
echo "Validating Session Management Phase 1 schema..."
make validate-schema-drift || echo "⚠️  Schema drift detected - review migrations with 'make validate-schema-drift'"

# Idempotent checkpoint schema management (ORM-driven)
echo "Ensuring checkpoint schema matches LangGraph 1.0.5 (ORM-driven)..."
docker exec orchestration_service python3 /app/scripts/deps/manage_checkpoint_schema.py --auto-migrate --backup

# Check exit code
if [ $? -eq 0 ]; then
    echo "✅ Checkpoint schema verified and migrated (if needed)"
else
    echo "⚠️  Checkpoint schema migration encountered issues - check logs"
    echo "   Manual fix: docker exec orchestration_service python3 /app/scripts/deps/manage_checkpoint_schema.py --dry-run"
fi

# JupyterLab uses oauth2_proxy authentication (no token needed)
JUPYTER_URL="http://127.0.0.1:8888/jupyter/ (SSO via Keycloak)"

# Verify service accessibility
echo "Verifying service accessibility..."
echo ""

echo ""
echo "🎉 Stack startup complete!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📝 ACCESS URLS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🎯 Core Application UIs:"
echo "   • Streamlit UI v1:                http://localhost:8501"
echo "   • Streamlit App v2:               http://localhost:8503/streamlit/"
echo "   • OpenWebUI:                      http://localhost:8902"
echo ""
echo "🔌 API Gateway & SDK Client Endpoints:"
echo "   • Agent Gateway (Direct):         http://localhost:8083"
echo "   • NGINX Proxy (HTTPS):            https://api.agentic.local (SDK endpoint)"
echo "   • NGINX Proxy (HTTP):             http://api.agentic.local (redirects to HTTPS)"
echo "     Note: NGINX is the recommended endpoint for SDK CLI and client library"
echo ""
echo "🛠️  Administrative Interfaces:"
echo "   • Management UI:                  http://localhost:8502/mgmt-ui/"
echo "   • Langfuse (Observability):       http://localhost:3001"
echo "   • Keycloak (Identity):            http://localhost:8180/admin"
echo ""
echo "🔬 Development Tools:"
echo "   • JupyterLab:                     $JUPYTER_URL"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔑 DEFAULT CREDENTIALS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "   Streamlit/OpenWebUI:    notebook-user / notebook-password"
echo "   Keycloak Admin:         admin / admin"
echo "   Langfuse:               Check .env.langfuse for generated credentials"
echo "   JupyterLab:             Token-based (see URL above)"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ SERVICE HEALTH VERIFICATION"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
curl -f http://localhost:8501 -o /dev/null -s && echo "   ✅ Streamlit UI v1:        Ready" || echo "   ❌ Streamlit UI v1:        Not accessible"
curl -f http://localhost:8503/streamlit/ -o /dev/null -s && echo "   ✅ Streamlit App v2:       Ready" || echo "   ❌ Streamlit App v2:       Not accessible"
curl -f http://localhost:8502/mgmt-ui/ -o /dev/null -s && echo "   ✅ Management UI:          Ready" || echo "   ❌ Management UI:          Not accessible"
curl -f http://localhost:8902 -o /dev/null -s && echo "   ✅ OpenWebUI:              Ready" || echo "   ❌ OpenWebUI:              Not accessible"
docker inspect jupyterlab --format '{{.State.Health.Status}}' 2>/dev/null | grep -q "healthy" && echo "   ✅ JupyterLab:             Ready" || echo "   ❌ JupyterLab:             Not accessible"
curl -f http://localhost:3001 -o /dev/null -s && echo "   ✅ Langfuse:               Ready" || echo "   ❌ Langfuse:               Not accessible"
curl -f http://localhost:8180 -o /dev/null -s && echo "   ✅ Keycloak:               Ready" || echo "   ❌ Keycloak:               Not accessible"
curl -f http://localhost:8083/health -o /dev/null -s && echo "   ✅ Agent Gateway:          Ready" || echo "   ❌ Agent Gateway:          Not accessible"
curl -f http://localhost:80/health -o /dev/null -s && echo "   ✅ NGINX Proxy:            Ready" || echo "   ❌ NGINX Proxy:            Not accessible"
docker inspect oauth2_proxy --format '{{.State.Status}}' 2>/dev/null | grep -q "running" && echo "   ✅ OAuth2 Proxy:           Ready" || echo "   ❌ OAuth2 Proxy:           Not accessible"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 NEXT STEPS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "   1. Access Streamlit UI v1 at http://localhost:8501"
echo "   2. Try Streamlit App v2 at http://localhost:8503/streamlit/"
echo "   3. Access Management UI at http://localhost:8502 (admin/admin)"
echo "   4. Monitor observability at http://localhost:3001"
echo "   5. Run 'make validate' for full test suite"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "⚠️  TROUBLESHOOTING"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "   If services are unhealthy:"
echo "   • make fix-credentials          (regenerates keys + reloads via SIGHUP)"
echo "   • make reload-service-tokens    (SIGHUP reload without regeneration)"
echo "   • make validate-service-health"
echo ""
echo "   If Management UI login fails with 'Access Denied':"
echo "   • Verify credentials: docker exec agent_gateway_mgmt_ui env | grep KEYCLOAK_CLIENT"
echo "   • Check mapper: docker exec postgres psql -U admin -d keycloak -c \"SELECT name FROM protocol_mapper pm JOIN client c ON pm.client_id = c.id WHERE c.client_id = 'mgmt-ui-client';\""
echo "   • Review docs: docs/bugfixes/MANAGEMENT_UI_ADMIN_CLI_VS_MGMT_UI_CLIENT_FIX.md"
echo ""
echo "   Check service logs:"
echo "   • make logs-<service-name>"
echo "   • Example: make logs-jupyterlab (view logs and access URL)"
echo ""

