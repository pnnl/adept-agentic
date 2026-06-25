#!/bin/bash
#
# Main bootstrap script to set up the entire development environment.
# This script executes all other scripts in this directory in numerical order.
#
set -e

# --- Helper Functions ---
log() { echo -e "\033[1;34m[BOOTSTRAP]\033[0m $1"; }
error() { echo -e "\033[1;31m[ERROR]\033[0m $1"; exit 1; }

# Get the directory of the bootstrap.sh script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log "Starting full environment setup..."

# Find and execute all numbered scripts in order
for script in $(find "$SCRIPT_DIR" -name '[0-9][0-9]-*.sh' | sort); do
    log "Executing script: $(basename "$script")"
    bash "$script" || error "Script $(basename "$script") failed. Aborting."
    log "Successfully completed: $(basename "$script")"
    echo
done

log "✅ All setup scripts completed successfully."
log "Please run 'newgrp docker' or log out and log back in for Docker group changes to take effect."
log "Your environment is now ready."
