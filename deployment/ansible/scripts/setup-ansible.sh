#!/bin/bash
# Setup Ansible environment and dependencies for ADEPT multi-cloud deployment
#
# This script installs:
# - Ansible and Ansible Vault
# - Cloud provider CLIs (AWS, Azure, GCP)
# - Infrastructure tools (CDK, Pulumi, Helm)
# - Python dependencies for validation

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}==> Setting up Ansible orchestration environment${NC}"
echo

# Function to check if command exists
command_exists() {
    command -v "$1" &> /dev/null
}

# Install Ansible
echo -e "${GREEN}Installing Ansible...${NC}"
if command_exists ansible; then
    echo "  Ansible already installed: $(ansible --version | head -1)"
else
    pip3 install --user ansible
    echo "  Ansible installed successfully"
fi

# Install Ansible Vault (bundled with Ansible but ensure it's available)
if ! command_exists ansible-vault; then
    echo -e "${YELLOW}  Warning: ansible-vault not found in PATH${NC}"
fi

# Install AWS CLI
echo
echo -e "${GREEN}Installing AWS CLI...${NC}"
if command_exists aws; then
    echo "  AWS CLI already installed: $(aws --version)"
else
    pip3 install --user awscli
    echo "  AWS CLI installed successfully"
fi

# Install Azure CLI
echo
echo -e "${GREEN}Installing Azure CLI...${NC}"
if command_exists az; then
    echo "  Azure CLI already installed: $(az version --query '\"azure-cli\"' -o tsv)"
else
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        echo "  Downloading Azure CLI installation script..."
        curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        if command_exists brew; then
            brew install azure-cli
        else
            echo -e "${YELLOW}  Homebrew not found. Install Azure CLI manually: https://docs.microsoft.com/en-us/cli/azure/install-azure-cli${NC}"
        fi
    else
        echo -e "${YELLOW}  Unsupported OS for auto-install. Install Azure CLI manually: https://docs.microsoft.com/en-us/cli/azure/install-azure-cli${NC}"
    fi
fi

# Install GCP CLI (gcloud)
echo
echo -e "${GREEN}Checking GCP CLI...${NC}"
if command_exists gcloud; then
    echo "  GCP CLI already installed: $(gcloud version --format='value(version)')"
else
    echo -e "${YELLOW}  GCP CLI not installed.${NC}"
    echo "  Visit: https://cloud.google.com/sdk/docs/install"
    echo "  Installation is optional if you're not deploying to GCP"
fi

# Install Helm
echo
echo -e "${GREEN}Installing Helm...${NC}"
if command_exists helm; then
    echo "  Helm already installed: $(helm version --short)"
else
    echo "  Downloading Helm installation script..."
    curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
    echo "  Helm installed successfully"
fi

# Install AWS CDK
echo
echo -e "${GREEN}Installing AWS CDK...${NC}"
if command_exists cdk; then
    echo "  AWS CDK already installed: $(cdk --version)"
else
    if command_exists npm; then
        npm install -g aws-cdk
        echo "  AWS CDK installed successfully"
    else
        echo -e "${YELLOW}  npm not found. Install Node.js first: https://nodejs.org/${NC}"
        echo "  Then run: npm install -g aws-cdk"
    fi
fi

# Install Pulumi
echo
echo -e "${GREEN}Installing Pulumi...${NC}"
if command_exists pulumi; then
    echo "  Pulumi already installed: $(pulumi version)"
else
    echo "  Downloading Pulumi installation script..."
    curl -fsSL https://get.pulumi.com | sh
    echo "  Pulumi installed successfully"
    echo -e "${YELLOW}  Note: You may need to add Pulumi to your PATH${NC}"
    echo "  Run: export PATH=\$PATH:\$HOME/.pulumi/bin"
fi

# Install Python dependencies for validation
echo
echo -e "${GREEN}Installing Python dependencies...${NC}"
pip3 install --user jsonschema pyyaml

echo
echo -e "${GREEN}==> Setup complete!${NC}"
echo
echo "Next steps:"
echo "  1. Navigate to deployment/ansible/"
echo "  2. Copy config/adept-config.example.yml to config/adept-config-dev.yml"
echo "  3. Edit config/adept-config-dev.yml with your values"
echo "  4. Encrypt sensitive data:"
echo "       ansible-vault encrypt config/adept-config-dev.yml"
echo "  5. Deploy infrastructure:"
echo "       ansible-playbook playbooks/deploy-infrastructure.yml \\"
echo "         --vault-password-file ~/.ansible-vault-password \\"
echo "         -e \"@config/adept-config-dev.yml\""
echo
echo "For more information, see: deployment/ansible/README.md"
