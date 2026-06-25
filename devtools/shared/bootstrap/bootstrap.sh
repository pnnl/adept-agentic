#!/bin/bash

# ADEPT Bootstrap Script - Bash Alternative
# Team-agnostic development environment setup
# Supports GitHub, GitLab, and other Git sources

set -e

# Color codes (matching ADEPT conventions)
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
RED='\033[1;31m'
BLUE='\033[1;34m'
NC='\033[0m' # No Color

# Default values
PYTHON_VERSION="3.11"
BRANCH="main"
USE_CONDA=false
CONDA_ENV="adept"
WORKSPACE_DIR="/data/workspace"
VERBOSE=false

# Function to print colored output
log() {
    echo -e "${BLUE}[BOOTSTRAP]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
    exit 1
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Function to show usage
usage() {
    cat << EOF
Usage: $0 COMMAND [OPTIONS]

Commands:
    init        Initialize development environment
    validate    Validate environment setup
    remote      Execute remote command

Options for 'init':
    -h, --host HOST           EC2 instance IP or hostname (required)
    -k, --key KEY_FILE        Path to SSH private key (required)
    -r, --repo REPO_URL       Git repository URL (required)
    -t, --token TOKEN         Personal Access Token for Git
    -b, --branch BRANCH       Git branch to clone (default: main)
    -f, --folder FOLDER       Clone folder name (default: repo name)
    -p, --python VERSION      Python version: 3.10, 3.11 (default: 3.11)
    --use-conda              Use conda instead of UV
    --conda-env NAME         Conda environment name (default: adept)
    -v, --verbose            Enable verbose output

Options for 'validate':
    -h, --host HOST           EC2 instance IP or hostname (required)
    -k, --key KEY_FILE        Path to SSH private key (required)
    -c, --check TYPE          Check type: docker, python, services, env, all

Options for 'remote':
    -h, --host HOST           EC2 instance IP or hostname (required)
    -k, --key KEY_FILE        Path to SSH private key (required)
    COMMAND                   Command to execute remotely

Examples:
    # Initialize with UV
    $0 init -h 10.0.0.1 -k ~/.ssh/key.pem -r https://github.com/pnnl/adept-agentic.git -t ghp_xxx

    # Initialize with Conda
    $0 init -h 10.0.0.1 -k ~/.ssh/key.pem -r https://gitlab.com/team/adept.git --use-conda

    # Validate setup
    $0 validate -h 10.0.0.1 -k ~/.ssh/key.pem -c all

    # Execute remote command
    $0 remote -h 10.0.0.1 -k ~/.ssh/key.pem "docker ps"

EOF
    exit 1
}

# Function to test SSH connection
test_ssh_connection() {
    local host=$1
    local key=$2

    if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -i "$key" ubuntu@"$host" "echo 'Connection test'" &>/dev/null; then
        return 0
    else
        return 1
    fi
}

# Function to execute SSH command
ssh_exec() {
    local host=$1
    local key=$2
    local command=$3

    if [ "$VERBOSE" = true ]; then
        ssh -o StrictHostKeyChecking=no -i "$key" ubuntu@"$host" "$command"
    else
        ssh -o StrictHostKeyChecking=no -i "$key" ubuntu@"$host" "$command" 2>/dev/null
    fi
}

# Function to initialize environment
init_environment() {
    local host=""
    local key=""
    local repo=""
    local token=""
    local folder=""

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--host)
                host="$2"
                shift 2
                ;;
            -k|--key)
                key="$2"
                shift 2
                ;;
            -r|--repo)
                repo="$2"
                shift 2
                ;;
            -t|--token)
                token="$2"
                shift 2
                ;;
            -b|--branch)
                BRANCH="$2"
                shift 2
                ;;
            -f|--folder)
                folder="$2"
                shift 2
                ;;
            -p|--python)
                PYTHON_VERSION="$2"
                shift 2
                ;;
            --use-conda)
                USE_CONDA=true
                shift
                ;;
            --conda-env)
                CONDA_ENV="$2"
                shift 2
                ;;
            -v|--verbose)
                VERBOSE=true
                shift
                ;;
            *)
                error "Unknown option: $1"
                ;;
        esac
    done

    # Validate required arguments
    [ -z "$host" ] && error "Host is required (-h/--host)"
    [ -z "$key" ] && error "SSH key is required (-k/--key)"
    [ -z "$repo" ] && error "Repository URL is required (-r/--repo)"

    # Check if key file exists
    [ ! -f "$key" ] && error "SSH key file not found: $key"

    # Extract folder name from repo if not specified
    if [ -z "$folder" ]; then
        folder=$(basename "$repo" .git)
    fi

    log "Initializing ADEPT development environment..."
    log "  Host: $host"
    log "  Repository: $repo"
    log "  Branch: $BRANCH"
    log "  Python: $PYTHON_VERSION"
    [ "$USE_CONDA" = true ] && log "  Using Conda environment: $CONDA_ENV" || log "  Using UV virtual environment"

    # Test SSH connection
    log "Testing SSH connection..."
    if ! test_ssh_connection "$host" "$key"; then
        error "Failed to connect to $host. Check your SSH key and host address."
    fi
    success "Connected to $host"

    # Create workspace directory with proper permissions
    log "Setting up workspace..."
    ssh_exec "$host" "$key" "sudo mkdir -p $WORKSPACE_DIR"
    ssh_exec "$host" "$key" "sudo chown ubuntu:ubuntu $WORKSPACE_DIR"
    ssh_exec "$host" "$key" "sudo chmod 777 $WORKSPACE_DIR"
    ssh_exec "$host" "$key" "sudo chmod g+s $WORKSPACE_DIR"

    # Clone repository
    local clone_path="$WORKSPACE_DIR/$folder"
    log "Cloning repository to $clone_path..."

    # Build authenticated URL if token provided
    local auth_repo="$repo"
    if [ -n "$token" ]; then
        if [[ "$repo" == *"github.com"* ]]; then
            auth_repo=${repo/https:\/\//https:\/\/$token@}
        elif [[ "$repo" == *"gitlab"* ]]; then
            auth_repo=${repo/https:\/\//https:\/\/oauth2:$token@}
        fi
    fi

    # Check if directory exists
    if ssh_exec "$host" "$key" "test -d $clone_path"; then
        warning "Directory $clone_path already exists, pulling latest changes..."
        ssh_exec "$host" "$key" "cd $clone_path && git pull origin $BRANCH"
    else
        # Clone the repository
        if ! ssh_exec "$host" "$key" "cd $WORKSPACE_DIR && git clone -b $BRANCH '$auth_repo' $folder"; then
            error "Failed to clone repository"
        fi
    fi
    success "Repository cloned successfully"

    # Set up Python environment
    if [ "$USE_CONDA" = true ]; then
        log "Setting up Conda environment '$CONDA_ENV'..."

        # Create conda environment
        ssh_exec "$host" "$key" "/opt/miniconda3/bin/conda create -n $CONDA_ENV python=$PYTHON_VERSION -y"

        # Install UV in conda environment
        ssh_exec "$host" "$key" "/opt/miniconda3/bin/conda run -n $CONDA_ENV pip install uv"

        # Check for uv.lock and sync if exists
        if ssh_exec "$host" "$key" "test -f $clone_path/uv.lock"; then
            log "Installing dependencies from uv.lock..."
            ssh_exec "$host" "$key" "cd $clone_path && /opt/miniconda3/bin/conda run -n $CONDA_ENV uv sync --all-extras"
        fi

        success "Conda environment '$CONDA_ENV' created"
        log "Activate with: conda activate $CONDA_ENV"

    else
        log "Setting up UV virtual environment..."

        # Check if UV is installed, install if missing
        echo -ne "  Checking UV installation... "
        if ! ssh_exec "$host" "$key" "test -f /home/ubuntu/.local/bin/uv" 2>/dev/null; then
            echo -e "${YELLOW}not found${NC}"
            echo -ne "  Installing UV package manager... "
            ssh_exec "$host" "$key" "curl -LsSf https://astral.sh/uv/install.sh | sh"
            echo -e "${GREEN}✓ installed${NC}"
        else
            echo -e "${GREEN}✓ already installed${NC}"
        fi

        # Create virtual environment with UV
        echo -ne "  Creating Python $PYTHON_VERSION virtual environment... "
        ssh_exec "$host" "$key" "cd $clone_path && /home/ubuntu/.local/bin/uv venv .venv --python $PYTHON_VERSION"
        echo -e "${GREEN}✓ created${NC}"

        # Check for uv.lock and sync if exists
        if ssh_exec "$host" "$key" "test -f $clone_path/uv.lock"; then
            echo -ne "  Syncing dependencies from uv.lock... "
            ssh_exec "$host" "$key" "cd $clone_path && /home/ubuntu/.local/bin/uv sync --all-extras"
            echo -e "${GREEN}✓ synced${NC}"

            # Install in editable mode
            echo -ne "  Installing package in editable mode... "
            ssh_exec "$host" "$key" "cd $clone_path && .venv/bin/pip install -e ."
            echo -e "${GREEN}✓ installed${NC}"
        fi

        success "Virtual environment created at $clone_path/.venv"
        log "Activate with: source $clone_path/.venv/bin/activate"
    fi

    # Set up .env file if template exists
    if ssh_exec "$host" "$key" "test -f $clone_path/.env.example"; then
        log "Setting up environment configuration..."
        ssh_exec "$host" "$key" "cp $clone_path/.env.example $clone_path/.env"
        success "Created .env from template"
        warning "Remember to update .env with your credentials"
    fi

    # Display summary
    echo
    success "Environment initialization complete!"
    echo
    echo "  Next steps:"
    echo "  1. SSH to instance: ssh -i $key ubuntu@$host"
    echo "  2. Navigate to: cd $clone_path"
    if [ "$USE_CONDA" = true ]; then
        echo "  3. Activate environment: conda activate $CONDA_ENV"
    else
        echo "  3. Activate environment: source .venv/bin/activate"
    fi
    echo "  4. Update .env file with your credentials"
    echo "  5. Setup ADEPT volumes and data folders: make init-shared-volume-permissions"
    echo "  6. Start ADEPT services: make start"
    echo
}

# Function to validate environment
validate_environment() {
    local host=""
    local key=""
    local check_type="all"

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--host)
                host="$2"
                shift 2
                ;;
            -k|--key)
                key="$2"
                shift 2
                ;;
            -c|--check)
                check_type="$2"
                shift 2
                ;;
            *)
                error "Unknown option: $1"
                ;;
        esac
    done

    # Validate required arguments
    [ -z "$host" ] && error "Host is required (-h/--host)"
    [ -z "$key" ] && error "SSH key is required (-k/--key)"

    log "Validating ADEPT development environment..."

    # Test SSH connection
    if ! test_ssh_connection "$host" "$key"; then
        error "Failed to connect to $host"
    fi

    local has_errors=false
    local has_warnings=false

    # Docker check
    if [ "$check_type" = "docker" ] || [ "$check_type" = "all" ]; then
        if ssh_exec "$host" "$key" "docker --version" >/dev/null 2>&1; then
            local version=$(ssh_exec "$host" "$key" "docker --version")
            success "Docker: $version"
        else
            error "Docker: Not installed"
            has_errors=true
        fi
    fi

    # Python check
    if [ "$check_type" = "python" ] || [ "$check_type" = "all" ]; then
        for py_ver in 3.10 3.11; do
            if ssh_exec "$host" "$key" "python$py_ver --version" >/dev/null 2>&1; then
                success "Python $py_ver: Installed"
            else
                warning "Python $py_ver: Not found"
                has_warnings=true
            fi
        done
    fi

    # UV check
    if [ "$check_type" = "env" ] || [ "$check_type" = "all" ]; then
        if ssh_exec "$host" "$key" "/home/ubuntu/.local/bin/uv --version" >/dev/null 2>&1; then
            local version=$(ssh_exec "$host" "$key" "/home/ubuntu/.local/bin/uv --version")
            success "UV: $version"
        else
            error "UV: Not installed"
            has_errors=true
        fi

        # Conda check
        if ssh_exec "$host" "$key" "/opt/miniconda3/bin/conda --version" >/dev/null 2>&1; then
            local version=$(ssh_exec "$host" "$key" "/opt/miniconda3/bin/conda --version")
            success "Conda: $version"
        else
            warning "Conda: Not installed"
            has_warnings=true
        fi
    fi

    # ADEPT services check
    if [ "$check_type" = "services" ] || [ "$check_type" = "all" ]; then
        if ssh_exec "$host" "$key" "ls $WORKSPACE_DIR/*/Makefile 2>/dev/null" >/dev/null 2>&1; then
            success "ADEPT Makefile: Found"

            # Check if services are running
            local count=$(ssh_exec "$host" "$key" "docker ps --format '{{.Names}}' | grep -E '(orchestration|gateway)' | wc -l" || echo "0")
            if [ "$count" -gt 0 ]; then
                success "ADEPT Services: $count running"
            else
                warning "ADEPT Services: Not running"
                has_warnings=true
            fi
        else
            warning "ADEPT Repository: Not found"
            has_warnings=true
        fi
    fi

    echo
    if [ "$has_errors" = true ]; then
        error "Validation failed with critical errors"
    elif [ "$has_warnings" = true ]; then
        warning "Validation passed with warnings"
    else
        success "All validations passed!"
    fi
}

# Function to execute remote command
execute_remote() {
    local host=""
    local key=""
    shift # Remove 'remote' command

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--host)
                host="$2"
                shift 2
                ;;
            -k|--key)
                key="$2"
                shift 2
                ;;
            *)
                # Rest is the command to execute
                break
                ;;
        esac
    done

    # Validate required arguments
    [ -z "$host" ] && error "Host is required (-h/--host)"
    [ -z "$key" ] && error "SSH key is required (-k/--key)"
    [ -z "$*" ] && error "Command to execute is required"

    log "Executing remote command: $*"

    # Execute command
    ssh -o StrictHostKeyChecking=no -i "$key" ubuntu@"$host" "$*"
    local exit_code=$?

    if [ $exit_code -eq 0 ]; then
        success "Command executed successfully"
    else
        error "Command failed with exit code $exit_code"
    fi
}

# Main script logic
main() {
    # Check if no arguments provided
    [ $# -eq 0 ] && usage

    # Get the command
    COMMAND=$1
    shift

    case $COMMAND in
        init)
            init_environment "$@"
            ;;
        validate)
            validate_environment "$@"
            ;;
        remote)
            execute_remote "$@"
            ;;
        -h|--help|help)
            usage
            ;;
        *)
            error "Unknown command: $COMMAND"
            ;;
    esac
}

# Run main function
main "$@"