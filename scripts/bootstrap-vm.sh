#!/bin/bash
# bootstrap-vm.sh — One-command VM setup + ADEPT stack launch
#
# Supported OS: Rocky Linux 9, Ubuntu 22.04/24.04
# Supported Cloud: AWS EC2, Azure VMs, on-prem (PNNL RC/EMSL)
#
# Takes a fresh VM from zero to running ADEPT stack:
#   Phase 0: System packages + conda + adept-session env
#   Phase 1: Ansible playbook (Docker, storage, firewall, TLS, workspace)
#   Phase 2: .env credential validation
#   Phase 3: ADEPT quickstart launch
#
# Usage:
#   ./scripts/bootstrap-vm.sh                # Full bootstrap (fresh VM)
#   ./scripts/bootstrap-vm.sh --skip-ansible # Already prepped, just launch
#   ./scripts/bootstrap-vm.sh --launch-only  # Just run quickstart
#   ./scripts/bootstrap-vm.sh --help

set -euo pipefail

# --- Configuration ---
ADEPT_WORKSPACE="${ADEPT_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
ADEPT_DATA_VOLUME="${ADEPT_DATA_VOLUME:-/data}"
ADEPT_GIT_BRANCH="${ADEPT_GIT_BRANCH:-main}"
CONDA_ENV_NAME="${CONDA_ENV_NAME:-adept-session}"
SKIP_ANSIBLE=false
LAUNCH_ONLY=false

for arg in "$@"; do
    case $arg in
        --skip-ansible) SKIP_ANSIBLE=true ;;
        --launch-only)  LAUNCH_ONLY=true; SKIP_ANSIBLE=true ;;
        --help|-h)
            sed -n '2,/^$/{ s/^# //; s/^#$//; p }' "$0"
            exit 0
            ;;
    esac
done

# --- Detect OS ---
detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS_ID="$ID"
        OS_VERSION="$VERSION_ID"
        OS_FAMILY=""
        case "$ID" in
            rocky|rhel|centos|almalinux|fedora) OS_FAMILY="redhat" ;;
            ubuntu|debian)                       OS_FAMILY="debian" ;;
            *)
                echo "WARNING: Unknown OS '$ID'. Attempting Debian-style commands."
                OS_FAMILY="debian"
                ;;
        esac
    else
        echo "ERROR: /etc/os-release not found. Cannot detect OS."
        exit 1
    fi
}

detect_os

echo "============================================"
echo "  ADEPT Bootstrap — $(hostname -f 2>/dev/null || hostname)"
echo "============================================"
echo "  OS:         ${OS_ID} ${OS_VERSION} (${OS_FAMILY})"
echo "  Workspace:  ${ADEPT_WORKSPACE}"
echo "  Data vol:   ${ADEPT_DATA_VOLUME}"
echo "  Conda env:  ${CONDA_ENV_NAME}"
echo "  Ansible:    $([ "$SKIP_ANSIBLE" = true ] && echo 'SKIP' || echo 'RUN')"
echo "============================================"
echo ""

# ================================================================
# Phase 0: System packages + Conda + Ansible
# ================================================================
if [ "$LAUNCH_ONLY" = false ]; then
    echo ">>> Phase 0: System packages + Conda environment ..."

    # --- Install base packages ---
    if [ "$OS_FAMILY" = "redhat" ]; then
        MISSING_PKGS=()
        for pkg in git make jq openssl rsync curl; do
            command -v "$pkg" &>/dev/null || MISSING_PKGS+=("$pkg")
        done
        if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
            echo "  Installing: ${MISSING_PKGS[*]}"
            sudo dnf install -y "${MISSING_PKGS[@]}" &>/dev/null
        fi
    elif [ "$OS_FAMILY" = "debian" ]; then
        MISSING_PKGS=()
        for pkg in git make jq openssl rsync curl ca-certificates gnupg; do
            command -v "$pkg" &>/dev/null || MISSING_PKGS+=("$pkg")
        done
        if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
            echo "  Installing: ${MISSING_PKGS[*]}"
            sudo apt-get update -qq &>/dev/null
            sudo apt-get install -y -qq "${MISSING_PKGS[@]}" &>/dev/null
        fi
    fi

    # --- Install conda ---
    CONDA_BIN=""
    if command -v conda &>/dev/null; then
        CONDA_BIN="$(command -v conda)"
    elif [ -x "$HOME/miniforge3/bin/conda" ]; then
        CONDA_BIN="$HOME/miniforge3/bin/conda"
    elif [ -x "/usr/bin/conda" ]; then
        CONDA_BIN="/usr/bin/conda"
    fi

    if [ -z "$CONDA_BIN" ]; then
        if [ "$OS_FAMILY" = "redhat" ]; then
            echo "  Installing conda via dnf..."
            sudo dnf install -y conda &>/dev/null
            CONDA_BIN="/usr/bin/conda"
        else
            echo "  Installing Miniforge (conda for Ubuntu)..."
            curl -fsSL "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh" -o /tmp/miniforge.sh
            bash /tmp/miniforge.sh -b -p "$HOME/miniforge3"
            rm -f /tmp/miniforge.sh
            "$HOME/miniforge3/bin/conda" init bash &>/dev/null
            CONDA_BIN="$HOME/miniforge3/bin/conda"
        fi
    fi

    echo "  Conda: $CONDA_BIN"

    # Initialize conda for this shell
    eval "$($CONDA_BIN shell.bash hook 2>/dev/null)" || true

    # --- Create adept-session env ---
    if ! $CONDA_BIN env list 2>/dev/null | grep -q "^${CONDA_ENV_NAME} "; then
        echo "  Creating conda env: ${CONDA_ENV_NAME} (Python 3.11)..."
        $CONDA_BIN create -n "${CONDA_ENV_NAME}" python=3.11 pip pyyaml -y -q
    fi

    # Determine conda env prefix
    CONDA_PREFIX="$($CONDA_BIN env list 2>/dev/null | grep "^${CONDA_ENV_NAME} " | awk '{print $NF}')"
    if [ -z "$CONDA_PREFIX" ]; then
        # Fallback paths
        if [ -d "$HOME/miniforge3/envs/${CONDA_ENV_NAME}" ]; then
            CONDA_PREFIX="$HOME/miniforge3/envs/${CONDA_ENV_NAME}"
        elif [ -d "$HOME/.conda/envs/${CONDA_ENV_NAME}" ]; then
            CONDA_PREFIX="$HOME/.conda/envs/${CONDA_ENV_NAME}"
        fi
    fi

    # --- Install ansible in conda env ---
    if [ -n "$CONDA_PREFIX" ] && [ -x "${CONDA_PREFIX}/bin/pip" ]; then
        if ! "${CONDA_PREFIX}/bin/ansible-playbook" --version &>/dev/null 2>&1; then
            echo "  Installing ansible + docker SDK into ${CONDA_ENV_NAME}..."
            "${CONDA_PREFIX}/bin/pip" install -q ansible docker requests
        fi
        ANSIBLE_PLAYBOOK="${CONDA_PREFIX}/bin/ansible-playbook"
    else
        echo "  WARNING: Could not find conda env at ${CONDA_PREFIX}"
        ANSIBLE_PLAYBOOK="$(command -v ansible-playbook 2>/dev/null || true)"
    fi

    echo "  Phase 0 complete."
    echo ""
fi

# ================================================================
# Phase 1: Ansible VM Preparation
# ================================================================
if [ "$SKIP_ANSIBLE" = false ]; then
    echo ">>> Phase 1: VM Preparation (Ansible playbook) ..."

    if [ -z "${ANSIBLE_PLAYBOOK:-}" ] || [ ! -x "${ANSIBLE_PLAYBOOK:-}" ]; then
        ANSIBLE_PLAYBOOK="$(command -v ansible-playbook 2>/dev/null || true)"
    fi

    if [ -z "$ANSIBLE_PLAYBOOK" ]; then
        echo "  ERROR: ansible-playbook not found."
        echo "  Install: conda activate ${CONDA_ENV_NAME} && pip install ansible"
        exit 1
    fi

    PLAYBOOK="${ADEPT_WORKSPACE}/deployment/ansible/playbooks/prepare-rocky-vm.yml"
    if [ ! -f "$PLAYBOOK" ]; then
        echo "  ERROR: Playbook not found at ${PLAYBOOK}"
        exit 1
    fi

    # Auto-detect inventory from hostname
    HOSTNAME_SHORT=$(hostname -s)
    INVENTORY_ARGS=""
    if [[ "$HOSTNAME_SHORT" == *"rc-aws"* ]] && [ -f "${ADEPT_WORKSPACE}/deployment/ansible/inventory/rc.ini" ]; then
        INVENTORY_ARGS="-i ${ADEPT_WORKSPACE}/deployment/ansible/inventory/rc.ini"
        echo "  Detected RC VM — using rc.ini"
    elif [[ "$HOSTNAME_SHORT" == *"emsl"* ]] && [ -f "${ADEPT_WORKSPACE}/deployment/ansible/inventory/emsl.ini" ]; then
        INVENTORY_ARGS="-i ${ADEPT_WORKSPACE}/deployment/ansible/inventory/emsl.ini"
        echo "  Detected EMSL VM — using emsl.ini"
    else
        INVENTORY_ARGS="-i localhost,"
        echo "  Using localhost inventory (${OS_ID} on ${HOSTNAME_SHORT})"
    fi

    echo "  Running Ansible playbook..."
    $ANSIBLE_PLAYBOOK "$PLAYBOOK" \
        $INVENTORY_ARGS \
        --connection=local \
        -e "ansible_user=$(whoami)" \
        -e "adept_workspace=${ADEPT_WORKSPACE}" \
        -e "data_volume=${ADEPT_DATA_VOLUME}" \
        -e "git_clone=false"

    echo "  Phase 1 complete."
    echo ""
fi

# ================================================================
# Phase 2: Validate .env
# ================================================================
echo ">>> Phase 2: Validating .env ..."
cd "${ADEPT_WORKSPACE}"

if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        echo "  No .env found — copying from .env.example"
        cp .env.example .env
    else
        echo "  ERROR: No .env or .env.example found."
        exit 1
    fi
fi

MISSING=()
for var in AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY DEFAULT_LLM_MODEL; do
    val=$(grep "^${var}=" .env 2>/dev/null | cut -d= -f2- || true)
    if [ -z "$val" ] || [[ "$val" == *"YOUR_"* ]] || [[ "$val" == *"CHANGEME"* ]]; then
        MISSING+=("$var")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    echo ""
    echo "  ================================================"
    echo "  WARNING: .env has unconfigured variables:"
    for v in "${MISSING[@]}"; do
        echo "    - $v"
    done
    echo ""
    echo "  Edit before LLM features will work:"
    echo "    vi ${ADEPT_WORKSPACE}/.env"
    echo "  ================================================"
    echo ""
    echo "  Continuing (infrastructure services don't need LLM keys)..."
fi
echo "  Phase 2 complete."
echo ""

# ================================================================
# Phase 3: Launch ADEPT Stack
# ================================================================
echo ">>> Phase 3: Launching ADEPT stack ..."
echo ""
exec "${ADEPT_WORKSPACE}/scripts/quick-start-adept-and-subsystems.sh"
