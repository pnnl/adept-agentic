#!/bin/bash
#
# 01-install-docker.sh
# Installs Docker Engine and related tools.
#
set -e

log_sub() { echo -e "  \033[1;32m[DOCKER]\033[0m $1"; }

if command -v docker &> /dev/null;
then
    log_sub "Docker is already installed. Skipping installation."
else
    log_sub "Installing Docker..."
    # Add Docker's official GPG key
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg

    # Add the Docker repository to Apt sources
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update -y

    # Install Docker packages
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    log_sub "Docker installed successfully."
fi

# Add user to the docker group
if ! getent group docker | grep -q "\b$USER\b";
then
    log_sub "Adding current user ($USER) to the 'docker' group..."
    sudo usermod -aG docker $USER
    log_sub "User added to docker group. Please run 'newgrp docker' or log out/in to apply changes."
else
    log_sub "User $USER is already in the 'docker' group."
fi
