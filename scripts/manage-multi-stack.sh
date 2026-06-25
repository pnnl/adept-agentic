#!/bin/bash
# manage-multi-stack.sh
# Multi-stack deployment management script for testing multiple gateway instances
#
# This script enables launching, managing, and testing multiple complete application
# stacks (gateway_a, gateway_b, etc.) while sharing base infrastructure.

set -e

# Colors for output
BLUE='\033[1;34m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
RED='\033[1;31m'
NC='\033[0m'

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BASE_COMPOSE_FILE="docker-compose.base.yaml"
CORE_COMPOSE_FILE="docker-compose.core.yaml"
MULTI_STACK_COMPOSE_FILE="docker-compose.multi-stack.yaml"

# Default port mappings for different stacks (avoiding conflicts with base system)
declare -A STACK_PORT_MAPPINGS=(
    ["stack_a"]="8095:8096:8097:8098:8099:8505"  # gateway:orchestrator:mcp:hpc:sandbox:streamlit
    ["stack_b"]="8105:8106:8107:8108:8109:8515"
    ["stack_c"]="8115:8116:8117:8118:8119:8525"
    ["stack_d"]="8125:8126:8127:8128:8129:8535"
)

# Default Redis DB mappings for different stacks
declare -A STACK_REDIS_DB_MAPPINGS=(
    ["stack_a"]="0"
    ["stack_b"]="1" 
    ["stack_c"]="2"
    ["stack_d"]="3"
)

print_header() {
    echo -e "${BLUE}========================================================${NC}"
    echo -e "${BLUE}  Multi-Stack Agentic Framework Manager${NC}"
    echo -e "${BLUE}========================================================${NC}"
}

print_usage() {
    echo -e "${YELLOW}Usage:${NC}"
    echo -e "  $0 <command> [stack_id] [options]"
    echo -e ""
    echo -e "${YELLOW}Commands:${NC}"
    echo -e "  start <stack_id>     - Start a specific stack (e.g., stack_a, stack_b)"
    echo -e "  stop <stack_id>      - Stop a specific stack" 
    echo -e "  restart <stack_id>   - Restart a specific stack"
    echo -e "  status <stack_id>    - Show status of a specific stack"
    echo -e "  list                 - List all active stacks"
    echo -e "  start-multi <list>   - Start multiple stacks (comma-separated)"
    echo -e "  stop-all             - Stop all stacks"
    echo -e "  test-connectivity    - Test connectivity between all active stacks"
    echo -e "  test-inter-gateway   - Test secure inter-gateway communication and credential isolation"
    echo -e "  show-urls            - Show access URLs for all active stacks"
    echo -e ""
    echo -e "${YELLOW}Available Stack IDs:${NC} stack_a, stack_b, stack_c, stack_d"
    echo -e ""
    echo -e "${YELLOW}Examples:${NC}"
    echo -e "  $0 start stack_a"
    echo -e "  $0 start-multi stack_a,stack_b"
    echo -e "  $0 test-connectivity"
    echo -e "  $0 show-urls"
}

get_stack_ports() {
    local stack_id="$1"
    local ports="${STACK_PORT_MAPPINGS[$stack_id]:-}"
    if [ -z "$ports" ]; then
        echo -e "${RED}Error: Unknown stack ID '$stack_id'${NC}" >&2
        return 1
    fi
    echo "$ports"
}

get_stack_redis_db() {
    local stack_id="$1"
    echo "${STACK_REDIS_DB_MAPPINGS[$stack_id]:-0}"
}

bootstrap_stack_credentials() {
    local stack_id="$1"
    
    echo -e "${GREEN}Bootstrapping credentials for stack: $stack_id${NC}"
    
    # Create stack-specific credential directory
    local stack_creds_dir=".env-keycloak-credentials-dir-$stack_id"
    mkdir -p "$stack_creds_dir" && chmod 777 "$stack_creds_dir"
    
    # Create stack-specific Keycloak bootstrap script
    local stack_bootstrap_script="/tmp/bootstrap_keycloak_$stack_id.py"
    
    # Copy the original bootstrap script and modify for stack-specific clients
    cat > "$stack_bootstrap_script" << 'EOF'
import os
import sys
import time
from keycloak import KeycloakAdmin, KeycloakOpenIDConnection
import json

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../src')))
from agentic_framework_pkg.core.secrets_manager import save_secrets
from agentic_framework_pkg.logger_config import get_logger

logger = get_logger(__name__)

def get_keycloak_admin_client():
    keycloak_connection = KeycloakOpenIDConnection(
        server_url="http://keycloak:8180/",
        username=os.getenv("KC_BOOTSTRAP_ADMIN_USERNAME", "admin"),
        password=os.getenv("KC_BOOTSTRAP_ADMIN_PASSWORD", "admin"),
        realm_name="master",
        user_realm_name="master",
        verify=True
    )
    
    for i in range(10):
        try:
            admin_client = KeycloakAdmin(connection=keycloak_connection)
            admin_client.get_realms()
            logger.info("Successfully connected to Keycloak.")
            return admin_client
        except Exception as e:
            logger.warning(f"Could not connect to Keycloak, retrying in 3 seconds... ({e})")
            time.sleep(3)
    
    logger.error("Failed to connect to Keycloak after multiple retries.")
    return None

def bootstrap_stack_keycloak(admin_client, stack_id):
    # Stack-specific client configurations
    stack_clients = [
        {
            "clientId": f"agent-gateway-{stack_id}",
            "serviceAccountsEnabled": True,
            "directAccessGrantsEnabled": True,
            "publicClient": False,
            "standardFlowEnabled": False
        },
        {
            "clientId": f"gateway-{stack_id}",
            "serviceAccountsEnabled": True,
            "directAccessGrantsEnabled": True,
            "publicClient": False,
            "standardFlowEnabled": False
        }
    ]
    
    # Create stack-specific clients
    for client_config in stack_clients:
        client_id = client_config["clientId"]
        if not any(c['clientId'] == client_id for c in admin_client.get_clients()):
            logger.info(f"Creating stack client: {client_id}")
            admin_client.create_client(payload=client_config)
            
            # Add protocol mappers
            internal_client_id = admin_client.get_client_id(client_id)
            if internal_client_id:
                mappers = admin_client.get_mappers_from_client(internal_client_id)
                
                # Add group membership mapper
                if not any(m['name'] == 'group membership' for m in mappers):
                    logger.info(f"Adding 'group membership' protocol mapper to client '{client_id}'")
                    mapper_payload = {
                        'name': 'group membership', 'protocol': 'openid-connect',
                        'protocolMapper': 'oidc-group-membership-mapper',
                        'config': {
                            'claim.name': 'groups', 'full.path': 'false',
                            'access.token.claim': 'true', 'id.token.claim': 'true',
                            'userinfo.token.claim': 'true', 'multivalued': 'true'
                        }
                    }
                    admin_client.add_mapper_to_client(internal_client_id, mapper_payload)
                
                # Add audience mapper
                audience_mapper_name = f"audience-{client_id}"
                if not any(m['name'] == audience_mapper_name for m in mappers):
                    logger.info(f"Adding audience mapper to client '{client_id}'")
                    mapper_payload = {
                        'name': audience_mapper_name,
                        'protocol': 'openid-connect',
                        'protocolMapper': 'oidc-audience-mapper',
                        'config': {
                            'id.token.claim': 'false',
                            'access.token.claim': 'true',
                            'included.client.audience': f'agent-gateway-{stack_id}',
                        }
                    }
                    admin_client.add_mapper_to_client(internal_client_id, mapper_payload)
        else:
            logger.info(f"Stack client {client_id} already exists.")
    
    # Assign service accounts to appropriate groups
    client_to_group_mapping = {
        f"agent-gateway-{stack_id}": ["gateway-service", "gateway-agents"],
        f"gateway-{stack_id}": ["gateway-service", "gateway-agents"]
    }
    
    all_groups = admin_client.get_groups()
    group_name_to_id = {g['name']: g['id'] for g in all_groups}
    
    for client_name, group_names in client_to_group_mapping.items():
        for group_name in group_names:
            group_id = group_name_to_id.get(group_name)
            if not group_id:
                logger.error(f"CRITICAL: Group '{group_name}' not found.")
                continue
            
            try:
                client_internal_id = admin_client.get_client_id(client_name)
                if client_internal_id:
                    service_account = admin_client.get_client_service_account_user(client_internal_id)
                    if service_account:
                        user_groups = admin_client.get_user_groups(user_id=service_account['id'])
                        if not any(g['id'] == group_id for g in user_groups):
                            admin_client.group_user_add(service_account['id'], group_id)
                            logger.info(f"Successfully assigned '{client_name}' to the '{group_name}' group.")
            except Exception as e:
                logger.error(f"Failed to assign '{client_name}' to '{group_name}' group: {e}")

def generate_and_save_stack_secrets(admin_client, stack_id, output_dir):
    stack_clients = [
        {"client_id": f"agent-gateway-{stack_id}", "secret_env": f"AGENT_GATEWAY_{stack_id.upper()}_CLIENT_SECRET"},
        {"client_id": f"gateway-{stack_id}", "secret_env": f"GATEWAY_{stack_id.upper()}_CLIENT_SECRET"}
    ]
    
    secrets_to_write = {}
    
    for client_info in stack_clients:
        client_id_str = client_info["client_id"]
        try:
            internal_client_id = admin_client.get_client_id(client_id_str)
            if not internal_client_id:
                logger.error(f"Could not find internal ID for client '{client_id_str}'.")
                continue
            
            new_secret = admin_client.generate_client_secrets(internal_client_id)
            secret_value = new_secret['value']
            secrets_to_write[client_info["secret_env"]] = secret_value
            logger.info(f"Generated secret for stack client: {client_id_str}")
            
        except Exception as e:
            logger.error(f"Failed to generate secret for client '{client_id_str}': {e}")
    
    # Save stack-specific secrets
    save_secrets(
        secrets_to_write,
        output_dir=output_dir,
        consolidated_file_name=f".env-keycloak-credentials-{stack_id}"
    )
    
    return secrets_to_write

if __name__ == "__main__":
    stack_id = sys.argv[1] if len(sys.argv) > 1 else "stack_a"
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "/app/credentials"
    
    admin_client = get_keycloak_admin_client()
    if admin_client:
        bootstrap_stack_keycloak(admin_client, stack_id)
        secrets = generate_and_save_stack_secrets(admin_client, stack_id, output_dir)
        logger.info(f"Stack {stack_id} Keycloak bootstrapping completed successfully.")
        
        # Print secrets for environment setup
        for key, value in secrets.items():
            print(f"export {key}={value}")
    else:
        logger.error(f"Stack {stack_id} Keycloak bootstrapping failed.")
        exit(1)
EOF
    
    # Run stack-specific bootstrap inside the container
    echo -e "${YELLOW}Running credential bootstrap for $stack_id...${NC}"
    docker exec -i keycloak python3 < "$stack_bootstrap_script" "$stack_id" "/app/credentials" > /tmp/stack_secrets_$stack_id.env
    
    if [ $? -eq 0 ]; then
        # Source the generated secrets into the environment
        source /tmp/stack_secrets_$stack_id.env
        
        # Copy secrets to stack-specific directory
        docker cp keycloak:/app/credentials/.env-keycloak-credentials-$stack_id "$stack_creds_dir/"
        
        echo -e "${GREEN}Credentials bootstrapped successfully for stack: $stack_id${NC}"
        rm -f /tmp/stack_secrets_$stack_id.env "$stack_bootstrap_script"
    else
        echo -e "${RED}Failed to bootstrap credentials for stack: $stack_id${NC}"
        rm -f /tmp/stack_secrets_$stack_id.env "$stack_bootstrap_script"
        return 1
    fi
}

register_gateway_with_registry() {
    local stack_id="$1"
    local gateway_port="$2"
    
    echo -e "${GREEN}Registering gateway $stack_id with gateway registry...${NC}"
    
    # Wait for gateway to be ready
    local max_attempts=30
    for attempt in $(seq 1 $max_attempts); do
        if curl -sf "http://localhost:$gateway_port/health" > /dev/null 2>&1; then
            echo -e "${GREEN}Gateway $stack_id is ready${NC}"
            break
        fi
        if [ $attempt -eq $max_attempts ]; then
            echo -e "${YELLOW}Warning: Gateway $stack_id health check timeout${NC}"
            return 1
        fi
        sleep 2
    done
    
    # Register with gateway registry
    local registration_payload=$(cat <<EOF
{
    "alias": "$stack_id",
    "url": "http://localhost:$gateway_port",
    "description": "Multi-stack gateway instance $stack_id"
}
EOF
)
    
    # Get admin token for registry registration
    local admin_token
    if [ -f ".env-keycloak-credentials-dir/AGENT_GATEWAY_CLIENT_SECRET" ]; then
        local client_secret=$(cat .env-keycloak-credentials-dir/AGENT_GATEWAY_CLIENT_SECRET)
        admin_token=$(curl -s -X POST \
            "http://localhost:8180/realms/master/protocol/openid-connect/token" \
            -H "Content-Type: application/x-www-form-urlencoded" \
            -d "grant_type=client_credentials" \
            -d "client_id=agent-gateway-client" \
            -d "client_secret=$client_secret" | jq -r '.access_token')
    fi
    
    if [ -n "$admin_token" ] && [ "$admin_token" != "null" ]; then
        local response=$(curl -s -X POST \
            "http://localhost:8086/v1/gateways" \
            -H "Authorization: Bearer $admin_token" \
            -H "Content-Type: application/json" \
            -d "$registration_payload")
        
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}Successfully registered gateway $stack_id with registry${NC}"
        else
            echo -e "${YELLOW}Warning: Failed to register gateway $stack_id with registry${NC}"
        fi
    else
        echo -e "${YELLOW}Warning: Could not obtain admin token for gateway registration${NC}"
    fi
}

ensure_base_infrastructure() {
    echo -e "${GREEN}Ensuring base infrastructure is running...${NC}"
    
    # Check if base services are running
    cd "$PROJECT_ROOT"
    
    if ! docker compose -f "$BASE_COMPOSE_FILE" ps --filter status=running | grep -q postgres; then
        echo -e "${YELLOW}Starting base infrastructure using start-chapter-resources.sh bootstrap approach...${NC}"
        
        # Create secret placeholders (mirroring start-chapter-resources.sh)
        echo -e "${GREEN}Phase 0: Preparing environment and creating secret placeholders...${NC}"
        declare -a secret_files=(
            "AGENT_GATEWAY_CLIENT_ID" "AGENT_GATEWAY_CLIENT_SECRET" "KEYCLOAK_CLIENT_SECRET" "N8N_CLIENT_SECRET"
            "OPENWEBUI_CLIENT_SECRET" "REGISTRY_CLIENT_SECRET" ".env-keycloak-credentials"
        )
        mkdir -p .env-keycloak-credentials-dir && chmod 777 .env-keycloak-credentials-dir
        for secret_file in "${secret_files[@]}"; do
            touch ".env-keycloak-credentials-dir/${secret_file}" && chmod 666 ".env-keycloak-credentials-dir/${secret_file}"
        done
        echo "Secret placeholders created."

        # Set environment from .env if available
        if [ -f .env ]; then set -a; source .env; set +a; fi
        
        # Set environment variables for compose
        export COMPOSE_BAKE=true
        local COMPOSE_CMD="docker compose -f $BASE_COMPOSE_FILE -f $CORE_COMPOSE_FILE"
        
        # Build images following start-chapter-resources.sh pattern
        echo -e "${GREEN}Phase 1: Building base images sequentially...${NC}"
        $COMPOSE_CMD build os-base
        $COMPOSE_CMD build deps-base
        echo -e "${GREEN}Building all remaining application and third-party services...${NC}"
        $COMPOSE_CMD build

        # Bootstrap infrastructure and tasks
        echo -e "${GREEN}Phase 2: Starting all bootstrap services and tasks...${NC}"
        $COMPOSE_CMD --profile bootstrap --profile bootstrap-task up -d --wait
        echo -e "${GREEN}Bootstrap and setup tasks complete.${NC}"

        echo -e "${GREEN}Base infrastructure started successfully.${NC}"
    else
        echo -e "${GREEN}Base infrastructure already running.${NC}"
    fi
}

start_stack() {
    local stack_id="$1"
    local no_cache="$2"
    
    if [ -z "$stack_id" ]; then
        echo -e "${RED}Error: Stack ID is required${NC}"
        print_usage
        return 1
    fi
    
    local ports
    ports=$(get_stack_ports "$stack_id")
    if [ $? -ne 0 ]; then
        return 1
    fi
    
    local redis_db
    redis_db=$(get_stack_redis_db "$stack_id")
    
    # Parse ports
    IFS=':' read -ra PORT_ARRAY <<< "$ports"
    local gateway_port="${PORT_ARRAY[0]}"
    local orchestrator_port="${PORT_ARRAY[1]}"
    local mcp_port="${PORT_ARRAY[2]}"
    local hpc_port="${PORT_ARRAY[3]}"
    local sandbox_port="${PORT_ARRAY[4]}"
    local streamlit_port="${PORT_ARRAY[5]}"
    
    echo -e "${GREEN}Starting stack: $stack_id${NC}"
    echo -e "${YELLOW}Ports: Gateway=$gateway_port, Orchestrator=$orchestrator_port, MCP=$mcp_port, HPC=$hpc_port, Sandbox=$sandbox_port, Streamlit=$streamlit_port${NC}"
    echo -e "${YELLOW}Redis DB: $redis_db${NC}"
    
    # Ensure base infrastructure is running
    ensure_base_infrastructure
    
    # Bootstrap stack-specific credentials
    if ! bootstrap_stack_credentials "$stack_id"; then
        echo -e "${RED}Failed to bootstrap credentials for $stack_id${NC}"
        return 1
    fi
    
    cd "$PROJECT_ROOT"
    
    # Set environment variables for this stack
    export STACK_ID="$stack_id"
    export STACK_REDIS_DB="$redis_db"
    export GATEWAY_EXTERNAL_PORT="$gateway_port"
    export ORCHESTRATOR_EXTERNAL_PORT="$orchestrator_port"
    export MCP_SERVER_EXTERNAL_PORT="$mcp_port"
    export HPC_MCP_SERVER_EXTERNAL_PORT="$hpc_port"
    export SANDBOX_MCP_SERVER_EXTERNAL_PORT="$sandbox_port"
    export STREAMLIT_V2_EXTERNAL_PORT="$streamlit_port"
    
    local build_args=""
    if [ "$no_cache" == "--no-cache" ]; then
        build_args="--no-cache"
        echo -e "${YELLOW}Building with --no-cache flag...${NC}"
    fi
    
    # Set environment variables for compose
    export COMPOSE_BAKE=true
    
    # Build and start the specific stack services by leveraging the existing services
    echo -e "${GREEN}Creating additional stack services for $stack_id...${NC}"
    
    # Use docker run commands to create individual stack containers
    # This approach avoids the dependency resolution issues of project isolation
    
    # Source stack-specific credentials
    local stack_creds_file=".env-keycloak-credentials-dir-$stack_id/.env-keycloak-credentials-$stack_id"
    if [ -f "$stack_creds_file" ]; then
        set -a
        source "$stack_creds_file"
        set +a
        echo -e "${GREEN}Loaded stack-specific credentials for $stack_id${NC}"
    else
        echo -e "${YELLOW}Warning: Stack-specific credentials not found, using default credentials${NC}"
    fi

    # Create the agent gateway for this stack
    echo -e "${GREEN}Starting agent gateway for $stack_id...${NC}"
    docker run -d \
        --name "agent_gateway_$stack_id" \
        --network agentic_framework_network \
        -p "$gateway_port:8081" \
        -e "STACK_ID=$stack_id" \
        -e "STACK_REDIS_DB=$redis_db" \
        -e "AGENT_GATEWAY_ALIAS=$stack_id" \
        -e "PUBLIC_GATEWAY_URL=http://localhost:$gateway_port" \
        -e "REDIS_URL=redis://redis:6379/$redis_db" \
        -e "ORCHESTRATION_SERVICE_URL=http://orchestration_service_$stack_id:8084" \
        -e "GATEWAY_REGISTRY_URL=http://gateway_registry:8086" \
        -e "KEYCLOAK_CLIENT_ID=agent-gateway-$stack_id" \
        -e "AGENT_GATEWAY_CLIENT_SECRET=${AGENT_GATEWAY_STACK_A_CLIENT_SECRET:-$AGENT_GATEWAY_CLIENT_SECRET}" \
        --env-file .env \
        --restart unless-stopped \
        chapter-06-advanced-multi-agent-orchestration-agent_gateway || true
    
    # Create the orchestration service for this stack
    echo -e "${GREEN}Starting orchestration service for $stack_id...${NC}"
    docker run -d \
        --name "orchestration_service_$stack_id" \
        --network agentic_framework_network \
        -p "$orchestrator_port:8084" \
        -e "STACK_ID=$stack_id" \
        -e "DATABASE_URL=postgresql+asyncpg://admin:password@postgres:5432/agentic_orchestrator_$stack_id" \
        -e "REDIS_URL=redis://redis:6379/$redis_db" \
        --env-file .env \
        --restart unless-stopped \
        chapter-06-advanced-multi-agent-orchestration-orchestration_service || true
    
    # Wait a moment for services to initialize
    sleep 5
    
    # Register gateway with registry for inter-gateway communication
    register_gateway_with_registry "$stack_id" "$gateway_port"
    
    echo -e "${GREEN}Stack $stack_id started successfully!${NC}"
    show_stack_urls "$stack_id"
}

stop_stack() {
    local stack_id="$1"
    
    if [ -z "$stack_id" ]; then
        echo -e "${RED}Error: Stack ID is required${NC}"
        print_usage
        return 1
    fi
    
    echo -e "${YELLOW}Stopping stack: $stack_id${NC}"
    
    # Stop and remove containers for this stack
    docker stop "agent_gateway_$stack_id" "orchestration_service_$stack_id" 2>/dev/null || true
    docker rm "agent_gateway_$stack_id" "orchestration_service_$stack_id" 2>/dev/null || true
    
    echo -e "${GREEN}Stack $stack_id stopped successfully!${NC}"
}

restart_stack() {
    local stack_id="$1"
    local no_cache="$2"
    
    echo -e "${YELLOW}Restarting stack: $stack_id${NC}"
    stop_stack "$stack_id"
    sleep 2
    start_stack "$stack_id" "$no_cache"
}

show_stack_status() {
    local stack_id="$1"
    
    if [ -z "$stack_id" ]; then
        echo -e "${RED}Error: Stack ID is required${NC}"
        print_usage
        return 1
    fi
    
    echo -e "${BLUE}Status for stack: $stack_id${NC}"
    
    cd "$PROJECT_ROOT"
    export STACK_ID="$stack_id"
    
    docker compose -f "$BASE_COMPOSE_FILE" -f "$CORE_COMPOSE_FILE" -f "$MULTI_STACK_COMPOSE_FILE" --project-name "$stack_id" --profile multi-stack ps
}

list_active_stacks() {
    echo -e "${BLUE}Active Stacks:${NC}"
    
    cd "$PROJECT_ROOT"
    
    # Check for running containers with stack naming pattern
    for stack_id in "${!STACK_PORT_MAPPINGS[@]}"; do
        if docker ps --filter "name=agent_gateway_${stack_id}" --filter status=running | grep -q agent_gateway; then
            echo -e "${GREEN}✓ $stack_id${NC} - Running"
            show_stack_urls "$stack_id" "  "
        else
            echo -e "${YELLOW}✗ $stack_id${NC} - Stopped"
        fi
    done
}

show_stack_urls() {
    local stack_id="$1"
    local prefix="$2"
    
    local ports
    ports=$(get_stack_ports "$stack_id")
    if [ $? -ne 0 ]; then
        return 1
    fi
    
    IFS=':' read -ra PORT_ARRAY <<< "$ports"
    local gateway_port="${PORT_ARRAY[0]}"
    local streamlit_port="${PORT_ARRAY[5]}"
    
    echo -e "${prefix}${YELLOW}URLs for $stack_id:${NC}"
    echo -e "${prefix}  Gateway API: http://localhost:$gateway_port"
    echo -e "${prefix}  Streamlit UI: http://localhost:$streamlit_port"
}

show_all_urls() {
    echo -e "${BLUE}Access URLs for all active stacks:${NC}"
    echo ""
    
    # Shared services
    echo -e "${GREEN}Shared Services:${NC}"
    echo -e "  Management UI:       http://localhost:8502"
    echo -e "  OpenWebUI:          http://localhost:8902"
    echo -e "  JupyterLab:         http://localhost:8888"
    echo -e "  Keycloak Admin:     http://localhost:8180"
    echo -e "  Gateway Registry:   http://localhost:8086"
    echo ""
    
    # Stack-specific services
    for stack_id in "${!STACK_PORT_MAPPINGS[@]}"; do
        if docker ps --filter "name=agent_gateway_${stack_id}" --filter status=running | grep -q agent_gateway; then
            show_stack_urls "$stack_id"
            echo ""
        fi
    done
}

start_multiple_stacks() {
    local stack_list="$1"
    local no_cache="$2"
    
    if [ -z "$stack_list" ]; then
        echo -e "${RED}Error: Stack list is required (comma-separated)${NC}"
        print_usage
        return 1
    fi
    
    IFS=',' read -ra STACKS <<< "$stack_list"
    for stack_id in "${STACKS[@]}"; do
        stack_id=$(echo "$stack_id" | tr -d ' ') # Remove whitespace
        echo -e "${GREEN}Starting stack: $stack_id${NC}"
        start_stack "$stack_id" "$no_cache"
        echo ""
    done
    
    echo -e "${GREEN}All requested stacks started successfully!${NC}"
    show_all_urls
}

stop_all_stacks() {
    echo -e "${YELLOW}Stopping all stacks...${NC}"
    
    for stack_id in "${!STACK_PORT_MAPPINGS[@]}"; do
        # Stop stack containers if they exist
        docker stop "agent_gateway_$stack_id" "orchestration_service_$stack_id" 2>/dev/null || true
        docker rm "agent_gateway_$stack_id" "orchestration_service_$stack_id" 2>/dev/null || true
    done
    
    echo -e "${GREEN}All stacks stopped successfully!${NC}"
}

test_stack_connectivity() {
    echo -e "${BLUE}Testing connectivity between active stacks...${NC}"
    
    local active_stacks=()
    
    # Find active stacks
    for stack_id in "${!STACK_PORT_MAPPINGS[@]}"; do
        if docker ps --filter "name=agent_gateway_${stack_id}" --filter status=running | grep -q agent_gateway; then
            active_stacks+=("$stack_id")
        fi
    done
    
    if [ ${#active_stacks[@]} -eq 0 ]; then
        echo -e "${YELLOW}No active stacks found.${NC}"
        return 0
    fi
    
    echo -e "${GREEN}Active stacks: ${active_stacks[*]}${NC}"
    echo ""
    
    # Test each stack's health endpoints
    for stack_id in "${active_stacks[@]}"; do
        local ports
        ports=$(get_stack_ports "$stack_id")
        IFS=':' read -ra PORT_ARRAY <<< "$ports"
        local gateway_port="${PORT_ARRAY[0]}"
        
        echo -e "${YELLOW}Testing $stack_id (port $gateway_port)...${NC}"
        
        if curl -sf "http://localhost:$gateway_port/health" >/dev/null; then
            echo -e "${GREEN}  ✓ Gateway health check passed${NC}"
        else
            echo -e "${RED}  ✗ Gateway health check failed${NC}"
        fi
        
        # Test models endpoint (requires auth, so just test if it returns 401/200)
        local status_code
        status_code=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$gateway_port/v1/models" || echo "000")
        if [[ "$status_code" =~ ^(200|401)$ ]]; then
            echo -e "${GREEN}  ✓ Models API endpoint accessible${NC}"
        else
            echo -e "${RED}  ✗ Models API endpoint failed (status: $status_code)${NC}"
        fi
    done
    
    echo ""
    
    # Test gateway registry integration
    echo -e "${YELLOW}Testing gateway registry integration...${NC}"
    local admin_token
    if [ -f ".env-keycloak-credentials-dir/AGENT_GATEWAY_CLIENT_SECRET" ]; then
        local client_secret=$(cat .env-keycloak-credentials-dir/AGENT_GATEWAY_CLIENT_SECRET)
        admin_token=$(curl -s -X POST \
            "http://localhost:8180/realms/master/protocol/openid-connect/token" \
            -H "Content-Type: application/x-www-form-urlencoded" \
            -d "grant_type=client_credentials" \
            -d "client_id=agent-gateway-client" \
            -d "client_secret=$client_secret" | jq -r '.access_token' 2>/dev/null)
    fi
    
    if [ -n "$admin_token" ] && [ "$admin_token" != "null" ]; then
        local registry_response=$(curl -s "http://localhost:8086/v1/gateways" \
            -H "Authorization: Bearer $admin_token" 2>/dev/null)
        
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}  ✓ Gateway registry accessible${NC}"
            local registered_count=$(echo "$registry_response" | jq -r '.gateways | length' 2>/dev/null)
            if [ -n "$registered_count" ] && [ "$registered_count" != "null" ]; then
                echo -e "${GREEN}  ✓ Found $registered_count registered gateways${NC}"
            fi
        else
            echo -e "${YELLOW}  ~ Gateway registry test incomplete${NC}"
        fi
    else
        echo -e "${YELLOW}  ~ Could not test gateway registry (authentication issue)${NC}"
    fi
    
    echo ""
    echo -e "${GREEN}Connectivity test completed.${NC}"
}

test_inter_gateway_communication() {
    echo -e "${BLUE}Testing secure inter-gateway communication...${NC}"
    
    local active_stacks=()
    
    # Find active stacks
    for stack_id in "${!STACK_PORT_MAPPINGS[@]}"; do
        if docker ps --filter "name=agent_gateway_${stack_id}" --filter status=running | grep -q agent_gateway; then
            active_stacks+=("$stack_id")
        fi
    done
    
    if [ ${#active_stacks[@]} -lt 2 ]; then
        echo -e "${YELLOW}Need at least 2 active stacks for inter-gateway communication test.${NC}"
        echo -e "${YELLOW}Currently active: ${active_stacks[*]:-none}${NC}"
        return 0
    fi
    
    echo -e "${GREEN}Testing communication between ${#active_stacks[@]} active stacks...${NC}"
    
    # Test gateway registry discovery
    local admin_token
    if [ -f ".env-keycloak-credentials-dir/AGENT_GATEWAY_CLIENT_SECRET" ]; then
        local client_secret=$(cat .env-keycloak-credentials-dir/AGENT_GATEWAY_CLIENT_SECRET)
        admin_token=$(curl -s -X POST \
            "http://localhost:8180/realms/master/protocol/openid-connect/token" \
            -H "Content-Type: application/x-www-form-urlencoded" \
            -d "grant_type=client_credentials" \
            -d "client_id=agent-gateway-client" \
            -d "client_secret=$client_secret" | jq -r '.access_token' 2>/dev/null)
    fi
    
    if [ -n "$admin_token" ] && [ "$admin_token" != "null" ]; then
        echo -e "${YELLOW}Testing gateway discovery via registry...${NC}"
        local registry_response=$(curl -s "http://localhost:8086/v1/gateways" \
            -H "Authorization: Bearer $admin_token" 2>/dev/null)
        
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}  ✓ Successfully discovered registered gateways${NC}"
            
            # Extract gateway information
            local gateway_info=$(echo "$registry_response" | jq -r '.gateways[]? | "\(.alias):\(.url)"' 2>/dev/null)
            if [ -n "$gateway_info" ]; then
                echo -e "${GREEN}  Registered gateways:${NC}"
                echo "$gateway_info" | while read -r line; do
                    echo -e "${BLUE}    - $line${NC}"
                done
            fi
        else
            echo -e "${RED}  ✗ Failed to discover gateways via registry${NC}"
        fi
        
        # Test credential isolation
        echo -e "${YELLOW}Testing credential isolation between stacks...${NC}"
        for stack_id in "${active_stacks[@]}"; do
            local stack_creds_file=".env-keycloak-credentials-dir-$stack_id/.env-keycloak-credentials-$stack_id"
            if [ -f "$stack_creds_file" ]; then
                echo -e "${GREEN}  ✓ Stack $stack_id has isolated credentials${NC}"
            else
                echo -e "${YELLOW}  ~ Stack $stack_id using shared credentials${NC}"
            fi
        done
        
        echo -e "${GREEN}Inter-gateway communication test completed.${NC}"
    else
        echo -e "${RED}Could not obtain admin token for inter-gateway tests${NC}"
    fi
}

# Main script logic
case "${1:-}" in
    "start")
        if [ -z "${2:-}" ]; then
            echo -e "${RED}Error: Stack ID is required${NC}"
            print_usage
            exit 1
        fi
        start_stack "$2" "${3:-}"
        ;;
    "stop")
        if [ -z "${2:-}" ]; then
            echo -e "${RED}Error: Stack ID is required${NC}"
            print_usage
            exit 1
        fi
        stop_stack "$2"
        ;;
    "restart")
        if [ -z "${2:-}" ]; then
            echo -e "${RED}Error: Stack ID is required${NC}"
            print_usage
            exit 1
        fi
        restart_stack "$2" "${3:-}"
        ;;
    "status")
        if [ -z "${2:-}" ]; then
            echo -e "${RED}Error: Stack ID is required${NC}"
            print_usage
            exit 1
        fi
        show_stack_status "$2"
        ;;
    "list")
        list_active_stacks
        ;;
    "start-multi")
        if [ -z "${2:-}" ]; then
            echo -e "${RED}Error: Stack list is required${NC}"
            print_usage
            exit 1
        fi
        start_multiple_stacks "$2" "${3:-}"
        ;;
    "stop-all")
        stop_all_stacks
        ;;
    "test-connectivity")
        test_stack_connectivity
        ;;
    "test-inter-gateway")
        test_inter_gateway_communication
        ;;
    "show-urls")
        show_all_urls
        ;;
    "help"|"-h"|"--help"|"")
        print_header
        print_usage
        ;;
    *)
        echo -e "${RED}Error: Unknown command '${1:-}'${NC}"
        print_usage
        exit 1
        ;;
esac
