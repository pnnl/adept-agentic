#!/bin/bash
#
# 00-update-and-install-core.sh
# Updates package lists and installs essential build tools.
#
set -e

log_sub() { echo -e "  \033[1;32m[CORE]\033[0m $1"; }

log_sub "Updating package lists..."
sudo apt-get update -y

log_sub "Installing core dependencies (curl, git, gnupg, wget, etc.)..."
sudo apt-get install -y \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg \
    git \
    wget \
    jq

log_sub "Core dependencies installed."
