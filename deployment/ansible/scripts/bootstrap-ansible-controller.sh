#!/bin/bash
# bootstrap-ansible-controller.sh — Prepare a machine to run ADEPT Ansible playbooks
#
# Run this ONCE on the machine that will execute ansible-playbook (the "controller").
# For EMSL/RC VMs this is typically the VM itself (ansible_connection=local).
#
# What it does:
#   1. Detects conda env or system Python 3
#   2. Installs Ansible (via conda or pip, whichever fits)
#   3. Installs required Ansible Galaxy collections (ansible.posix, community.general)
#   4. Runs ansible --version to confirm
#
# Usage:
#   # From the repo root:
#   bash deployment/ansible/scripts/bootstrap-ansible-controller.sh
#
#   # Or if you're already in deployment/ansible/:
#   bash scripts/bootstrap-ansible-controller.sh
#
# After this script completes you can run:
#   ansible-playbook deployment/ansible/playbooks/prepare-rocky-vm.yml \
#     -i deployment/ansible/inventory/emsl.ini

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

# Locate the requirements.yml relative to this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REQUIREMENTS_FILE="${SCRIPT_DIR}/../requirements.yml"

if [[ ! -f "$REQUIREMENTS_FILE" ]]; then
    error "Cannot find requirements.yml at $REQUIREMENTS_FILE"
    exit 1
fi

# ---------------------------------------------------------------
# Step 1: Ensure Ansible is installed
# ---------------------------------------------------------------
if command -v ansible &>/dev/null; then
    info "Ansible already installed: $(ansible --version | head -1)"
else
    info "Ansible not found — installing..."

    # Prefer conda if we're in a conda env
    if [[ -n "${CONDA_DEFAULT_ENV:-}" ]] && command -v conda &>/dev/null; then
        info "Installing Ansible via conda (env: $CONDA_DEFAULT_ENV)"
        conda install -y -c conda-forge ansible-core
    elif command -v pip3 &>/dev/null; then
        info "Installing Ansible via pip3 --user"
        pip3 install --user ansible-core
    elif command -v pip &>/dev/null; then
        info "Installing Ansible via pip --user"
        pip install --user ansible-core
    else
        error "No conda, pip3, or pip found. Install Python 3 + pip first."
        exit 1
    fi

    # Verify
    if ! command -v ansible &>/dev/null; then
        warn "ansible not on PATH after install. You may need to add ~/.local/bin to PATH:"
        warn "  export PATH=\$HOME/.local/bin:\$PATH"
        exit 1
    fi
fi

echo

# ---------------------------------------------------------------
# Step 2: Install Ansible Galaxy collections
# ---------------------------------------------------------------
info "Installing Ansible Galaxy collections from $REQUIREMENTS_FILE"
ansible-galaxy collection install -r "$REQUIREMENTS_FILE"

echo

# ---------------------------------------------------------------
# Step 3: Verify
# ---------------------------------------------------------------
info "Verification:"
echo "  ansible:          $(command -v ansible)"
echo "  ansible version:  $(ansible --version | head -1)"
echo "  collections:"
ansible-galaxy collection list 2>/dev/null | grep -E "ansible\.posix|community\.general" | sed 's/^/    /' || warn "Could not list collections"

echo
info "Bootstrap complete. You can now run:"
echo "  ansible-playbook deployment/ansible/playbooks/prepare-rocky-vm.yml \\"
echo "    -i deployment/ansible/inventory/emsl.ini"
