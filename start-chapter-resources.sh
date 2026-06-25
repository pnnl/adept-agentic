#!/bin/bash
set -e

# ==============================================================================
# ADEPT Tutorial Lifecycle Management Script (Interactive)
#
# Provides a menu-driven interface to manage Docker resources,
# distinguishing between core and base services for efficiency.
# ==============================================================================

# --- Configuration and Setup ---
set -o pipefail
BLUE='\033[1;34m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
RED='\033[1;31m'
NC='\033[0m'
export COMPOSE_BAKE=true

# Docker Compose file paths
COMPOSE_DIR="deployment/local/docker-compose"
CORE_COMPOSE_FILE="$COMPOSE_DIR/docker-compose.core.yaml"
BASE_COMPOSE_FILE="$COMPOSE_DIR/docker-compose.base.yaml"

build_compose_cmd() {
    local script_dir
    script_dir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
    local cmd="docker compose"
    if [ -f "$script_dir/$BASE_COMPOSE_FILE" ]; then
        cmd+=" -f $script_dir/$BASE_COMPOSE_FILE"
    fi
    if [ -f "$script_dir/$CORE_COMPOSE_FILE" ]; then
        cmd+=" -f $script_dir/$CORE_COMPOSE_FILE"
    fi
    echo "$cmd"
}

COMPOSE_CMD=$(build_compose_cmd)
CORE_COMPOSE_CMD="docker compose -f $BASE_COMPOSE_FILE -f $CORE_COMPOSE_FILE"

# --- Helper Functions ---
print_header() {
    echo -e "${BLUE}=======================================================${NC}"
    echo -e "${BLUE}  ADEPT Chapter Resource Manager (${PWD##*/}) ${NC}"
    echo -e "${BLUE}=======================================================${NC}"
}

# --- Lifecycle Functions ---
start_all() {
    # --- Phase 0: Pre-flight Checks and Placeholder Creation ---
    echo -e "${GREEN}Phase 0: Preparing environment and creating secret placeholders...${NC}"
    declare -a secret_files=(
        "AGENT_GATEWAY_CLIENT_ID" "AGENT_GATEWAY_CLIENT_SECRET" "KEYCLOAK_CLIENT_SECRET" "N8N_CLIENT_SECRET"
        "OPENWEBUI_CLIENT_SECRET" "REGISTRY_CLIENT_SECRET" ".env-keycloak-credentials"
    )
    mkdir -p .env-keycloak-credentials-dir && chmod 777 .env-keycloak-credentials-dir 2>/dev/null || true
    for secret_file in "${secret_files[@]}"; do
        touch ".env-keycloak-credentials-dir/${secret_file}" 2>/dev/null || true && chmod 666 ".env-keycloak-credentials-dir/${secret_file}" 2>/dev/null || true
    done
    echo "Secret placeholders created."

    if [ -f .env ]; then set -a; source .env; set +a; fi

    local build_args=""
    if [ "$1" == "--no-cache" ]; then
        build_args+=" --no-cache"
        echo -e "${YELLOW}Forcing a fresh build of all images (--no-cache)...${NC}"
    fi

    # --- Phase 1: Build Images ---
    echo -e "${GREEN}Phase 1: Building base images sequentially...${NC}"
    # Determine which profiles to use for building
    BUILD_PROFILES="--profile apps --profile bootstrap --profile bootstrap-task"
    $COMPOSE_CMD $BUILD_PROFILES build os-base $build_args
    $COMPOSE_CMD $BUILD_PROFILES build deps-base $build_args
    echo -e "${GREEN}Building all remaining application and third-party services...${NC}"
    $COMPOSE_CMD $BUILD_PROFILES build $build_args

    # --- Phase 2: Bootstrap Infrastructure and Tasks ---
    echo -e "${GREEN}Phase 2: Starting all bootstrap services and tasks...${NC}"
    $COMPOSE_CMD --profile bootstrap --profile bootstrap-task up -d --wait
    echo -e "${GREEN}Bootstrap and setup tasks complete.${NC}"

    # --- Phase 2.5: Wait for Keycloak Bootstrap Completion ---
    # Wait for keycloak-setup container to finish writing all credentials.
    # docker wait returns immediately if the container already exited.
    echo -e "${YELLOW}Waiting 30 seconds for keycloak-setup to complete bootstrap...${NC}"
    sleep 30
    echo -e "${YELLOW}Waiting for keycloak-setup container to exit...${NC}"
    KC_EXIT=$(docker wait keycloak-setup 2>/dev/null || echo "1")
    if [[ "$KC_EXIT" != "0" ]]; then
        echo -e "${RED}❌ keycloak-setup exited with code $KC_EXIT${NC}"
        echo -e "${RED}   Check logs: docker logs keycloak-setup --tail 30${NC}"
        exit 1
    fi
    echo -e "${GREEN}✅ keycloak-setup completed successfully${NC}"

    # Verify the credential file was written (poll for I/O sync on NFS/slow-disk VMs)
    CREDENTIALS_FILE="deployment/local/docker-compose/.env-keycloak-credentials-dir/SERVICE_API_KEYS_CONFIG"
    for i in {1..10}; do
        if [[ -f "$CREDENTIALS_FILE" ]]; then
            echo -e "${GREEN}✅ Keycloak credentials verified${NC}"
            break
        fi
        if [[ $i -eq 10 ]]; then
            echo -e "${RED}❌ SERVICE_API_KEYS_CONFIG not found after keycloak-setup completed (20s I/O wait)${NC}"
            echo -e "${RED}   Check keycloak-setup container logs: docker logs keycloak-setup${NC}"
            exit 1
        fi
        echo -e "${YELLOW}   Credentials not yet visible on disk, waiting for I/O sync... (attempt $i/10)${NC}"
        sleep 2
    done

    # Sync credentials to project root for validation tests
    if ! make sync-credentials 2>/dev/null; then
        echo -e "${YELLOW}   WARNING: 'make sync-credentials' failed — validation tests may not authenticate.${NC}"
        echo -e "${YELLOW}   Run 'make sync-credentials' manually after stack is healthy.${NC}"
    fi

    # --- Phase 3: Start All Application Services ---
    echo -e "${GREEN}Phase 3: Starting all main application services...${NC}"
    $COMPOSE_CMD --profile apps up -d --wait

    echo -e "${YELLOW}Fetching JupyterLab URL...${NC}"
    sleep 5
    JUPYTER_LOGS=$($COMPOSE_CMD logs jupyterlab 2>&1 || true)
    JUPYTER_URL=$(echo "$JUPYTER_LOGS" | grep -o 'http://127.0.0.1:8888/lab?token=[a-f0-9]*' | head -n 1 || true)

    echo -e "-------------------------------------------------------"
    echo -e "${GREEN}Access URLs:${NC}"
    echo -e "  - Streamlit App v2:          http://localhost:8503"
    echo -e "  - Management UI:             http://localhost:8502"
    echo -e "  - OpenWebUI:                 http://localhost:8902"
    echo -e "  - Agent Gateway (Direct):    http://localhost:8083"
    echo -e "  - NGINX Proxy (HTTPS):       https://api.agentic.local (SDK endpoint)"
    echo -e "  - NGINX Proxy (HTTP):        http://api.agentic.local (redirects to HTTPS)"
    if [ -n "$JUPYTER_URL" ]; then
        echo -e "  - JupyterLab:                ${JUPYTER_URL}"
    else
        echo -e "  - JupyterLab:    (Still starting up, please check logs with option 4)"
    fi
    echo -e "-------------------------------------------------------"
}

stop_all() {
    print_header
    echo -e "${YELLOW}Stopping all services defined in compose files...${NC}"
    $COMPOSE_CMD --profile "*" stop
    echo -e "${GREEN}All services stopped.${NC}"
}

restart_all() {
    print_header
    echo -e "${YELLOW}Restarting all services...${NC}"
    stop_all
    start_all "$1"
}

teardown_full() {
    print_header
    if [ "$1" != "-y" ]; then
        read -p "$(echo -e ${RED}"This will stop and remove ALL containers, networks, and volumes associated with the project. Are you sure? (y/N) "${NC})" -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Aborted."
            return
        fi
    fi
    echo -e "${RED}Tearing down ALL services, networks, and volumes...${NC}"
    $COMPOSE_CMD --profile "*" down --remove-orphans -v

    # Clean nginx certs (bind-mount, not a Docker volume) to prevent key/cert mismatch
    # on next startup. nginx_proxy regenerates a fresh matching pair on boot.
    if [ -d "data/nginx_certs" ]; then
        rm -f data/nginx_certs/api.agentic.local.crt data/nginx_certs/api.agentic.local.key data/nginx_certs/adept-ca-bundle.pem
        echo -e "${YELLOW}Cleared nginx certs (will regenerate on next start)${NC}"
    fi

    # Backup .env before modifying (preserves full state for recovery)
    if [ -f ".env" ]; then
        local backup_name=".env-backup-$(date +%Y%m%d-%H%M).bak"
        cp .env "$backup_name"
        echo -e "${YELLOW}Backed up .env to $backup_name${NC}"
    fi

    # Clear stale KC_ADMIN_CLI_SECRET (Keycloak generates a new one on fresh DB after -v)
    # Without this, keycloak-setup bootstrap gets 401 indefinitely on next start.
    local creds_dir="deployment/local/docker-compose/.env-keycloak-credentials-dir"
    if [ -f "$creds_dir/KC_ADMIN_CLI_SECRET" ]; then
        rm -f "$creds_dir/KC_ADMIN_CLI_SECRET"
        echo -e "${YELLOW}Cleared stale KC_ADMIN_CLI_SECRET (will rediscover on next start)${NC}"
    fi
    # Also clear from .env so keycloak-setup doesn't inherit stale value
    if grep -q "^KC_ADMIN_CLI_SECRET=" .env 2>/dev/null; then
        sed -i 's|^KC_ADMIN_CLI_SECRET=.*|KC_ADMIN_CLI_SECRET=|' .env
        echo -e "${YELLOW}Cleared KC_ADMIN_CLI_SECRET from .env${NC}"
    fi
    
    if [ "$1" != "-y" ]; then
        read -p "$(echo -e ${YELLOW}"Do you want to remove the images built for this project? (y/N) "${NC})" -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Image removal skipped."
            return
        fi
    fi
    
    echo "Removing project images..."
    $COMPOSE_CMD --profile "*" down --rmi all

    if [ "$1" != "-y" ]; then
        read -p "$(echo -e ${YELLOW}"Do you want to prune unused Docker networks? (y/N) "${NC})" -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Network pruning skipped."
            return
        fi
    fi

    echo "Pruning networks..."
    docker network prune -f
    echo -e "${GREEN}Full teardown complete.${NC}"
}

erase_all() {
    print_header
    echo -e "${RED}========================= DANGER ========================${NC}"
    echo -e "${RED}This option will stop ALL running Docker containers and   ${NC}"
    echo -e "${RED}permanently delete ALL Docker images on your system.      ${NC}"
    echo -e "${RED}This is a destructive action and cannot be undone.        ${NC}"
    echo -e "${RED}=======================================================${NC}"
    if [ "$1" != "-y" ]; then
        read -p "$(echo -e ${YELLOW}"First, stop and remove all containers? (y/N) "${NC})" -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Aborted."
            return
        fi
    fi

    echo -e "${YELLOW}Stopping all running containers...${NC}"
    if [ -n "$(docker ps -q)" ]; then
        docker stop $(docker ps -aq)
    else
        echo "No running containers to stop."
    fi

    echo -e "${YELLOW}Removing all containers...${NC}"
    if [ -n "$(docker ps -aq)" ]; then
        docker rm $(docker ps -aq)
    else
        echo "No containers to remove."
    fi
    echo -e "${GREEN}All containers stopped and removed.${NC}"

    if [ "$1" != "-y" ]; then
        read -p "$(echo -e ${RED}"DANGER: Now, permanently delete ALL images? This cannot be undone. (y/N) "${NC})" -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Aborted. Images were not deleted."
            return
        fi
    fi

    echo -e "${RED}Deleting all Docker images...${NC}"
    if [ -n "$(docker images -a -q)" ]; then
        docker rmi $(docker images -a -q) -f
    else
        echo "No images to delete."
    fi
    echo -e "${GREEN}All images deleted.${NC}"
}

show_status() {
    print_header
    echo -e "${GREEN}Current status of all services:${NC}"
    $COMPOSE_CMD ps
}

tail_logs() {
    local services="$@"
    print_header
    echo -e "${GREEN}Tailing logs for: ${services:-all services}. Press Ctrl+C to stop.${NC}"
    $COMPOSE_CMD logs -f --tail=100 $services
}

show_logs_menu() {
    while true; do
        print_header
        echo "View logs for which services?"
        echo "  1) All Services"
        echo "  2) Application Services Only"
        echo "  3) 3rd-Party Infrastructure Only"
        echo "  b) Back to Main Menu"
        read -p "Enter choice: " log_choice

        local app_services="agent_gateway mcp_server streamlit_app hpc_mcp_server sandbox_mcp_server agent_gateway_mgmt_ui gateway_registry jupyterlab orchestration_service"
        local third_party_services="vector_db_server keycloak redis n8n openwebui postgres"

        case $log_choice in
            1) tail_logs ;;
            2) tail_logs $app_services ;;
            3) tail_logs $third_party_services ;;
            b) return ;;
            *) echo -e "${RED}Invalid option.${NC}" ;;
        esac
        echo ""
        read -p "Press Enter to return to the log menu..."
    done
}

main_menu() {
    print_header
    echo "Please choose an option:"
    echo "  1) Start All Services (use cache)"
    echo "  1a) Start All Services (force fresh build)"
    echo "  2) Stop All Services"
    echo "  2a) Restart All Services"
    echo "  3) Status"
    echo "  4) View Logs"
    echo "  5) Teardown Core Services Only (for developers)"
    echo "  6) Teardown ALL Services (full reset)"
    echo -e "  ${RED}7) Stop Containers & Erase ALL Images (DANGER)${NC}"
    echo "  q) Quit"
    read -p "Enter choice: " choice

    case $choice in
        1) start_all ;;
        1a) start_all --no-cache ;;
        2) stop_all ;;
        2a) restart_all ;;
        3) show_status ;;
        4) show_logs_menu ;;
        5) teardown_core ;;
        6) teardown_full ;;
        7) erase_all ;;
        q) exit 0 ;;
        *) echo -e "${RED}Invalid option. Please try again.${NC}" ;;
    esac
    echo ""
    read -p "Press Enter to return to the menu..."
}

# --- Script Execution ---
if [ ! -f "$BASE_COMPOSE_FILE" ] || [ ! -f "$CORE_COMPOSE_FILE" ]; then
    echo -e "${RED}Error: Core or Base docker-compose files not found. Exiting.${NC}"
    exit 1
fi

if [ "$#" -gt 0 ]; then
    case "$1" in
        start)
            start_all "$2"
            ;;
        stop)
            stop_all
            ;;
        restart)
            restart_all "$2"
            ;;
        status)
            show_status
            ;;
        logs)
            shift
            tail_logs "$@"
            ;;
        teardown)
            teardown_full "$2"
            ;;
        erase)
            erase_all "$2"
            ;;
        *)
            echo -e "${RED}Invalid command: $1${NC}"
            echo "Usage: $0 {start|stop|restart|status|logs|teardown|erase}"
            exit 1
            ;;
    esac
    exit 0
fi

if [ "$1" == "--force" ]; then
    start_all "$2"
    exit 0
fi

while true; do
    main_menu
done
