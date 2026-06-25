# ADEPT AWS VM Deployment Guide
## Complete Setup from AWS Account to Running Services

**Author**: Paul Rigor, PhD
**Version**: 2.0
**Date**: November 2025
**Estimated Time**: 15-20 minutes end-to-end

---

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Quick Start Overview](#quick-start-overview)
3. [Step 1: Environment Setup](#step-1-environment-setup)
4. [Step 2: Deploy EC2 Instance with CDK](#step-2-deploy-ec2-instance-with-cdk)
5. [Step 3: SSH Key Management](#step-3-ssh-key-management)
6. [Step 4: Wait for Cloud-Init Completion](#step-4-wait-for-cloud-init-completion)
7. [Step 5: Bootstrap ADEPT Framework](#step-5-bootstrap-adept-framework)
8. [Step 6: VS Code Remote Development Setup](#step-6-vs-code-remote-development-setup)
9. [Step 7: Configure & Start Services](#step-7-configure--start-services)
10. [Quick Reference Commands](#quick-reference-commands)
11. [Instance Management](#instance-management)
12. [Troubleshooting](#troubleshooting)
13. [Next Steps](#next-steps)

---

## Prerequisites

### Required Tools
- **AWS CLI** configured with appropriate credentials
  ```bash
  aws --version  # Should be v2.x
  ```
- **CDK** installed globally
  ```bash
  npm install -g aws-cdk
  cdk --version  # Should be v2.x
  ```
- **Python 3.11+** with pip
  ```bash
  python3 --version
  ```
- **VS Code** with Remote-SSH extension (for development)
- **GitHub Personal Access Token** (for repository access)

### AWS Resources
- **Valid AWS Account ID**: Your AWS account
- **VPC ID**: A VPC in your target region
- **IAM Permissions**: EC2, VPC, SSM, CloudFormation

### Optional
- Configured `.env` file for ADEPT (can copy from template later)
- AWS Bedrock credentials (for coding agent features)

### Pre-Deployment Checklist
- [ ] AWS CLI configured: `aws sts get-caller-identity` works
- [ ] CDK installed: `cdk --version` shows v2.x
- [ ] GitHub token ready (for private repository access)
- [ ] SSH client available: `ssh -V` works
- [ ] 500GB+ free space on local machine (for repository clone)

---

## Quick Start Overview

```mermaid
graph LR
    A[AWS Credentials] --> B[CDK Deploy<br/>~3 min]
    B --> C[Cloud-Init<br/>~5 min]
    C --> D[Bootstrap<br/>~2 min]
    D --> E[VS Code Setup<br/>~3 min]
    E --> F[Start Services<br/>~5 min]
    F --> G[Vibe Coding!]

    style A fill:#f9f,stroke:#333,stroke-width:2px
    style G fill:#9f9,stroke:#333,stroke-width:2px
```

**Total Time**: 15-20 minutes from zero to running ADEPT stack

**What You Get**:
- EC2 t3.2xlarge instance (8 vCPU, 32GB RAM)
- 100GB root + 500GB data volumes
- Python 3.11 virtual environment with UV package manager
- Docker with Docker-in-Docker support
- ADEPT framework cloned and configured
- All 15 services running and validated
- VS Code remote development with port forwarding

---

## Step 1: Environment Setup

### 1.1 Set Deployment Parameters
```bash
# Navigate to CDK directory
cd devtools/aws-cdk

# Set your unique identifiers
export CDK_ENV_LABEL="dev"
export CDK_USER_LABEL="yourname"  # Use your username, e.g., paulr, demo01

# Get your AWS account ID
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo "AWS Account ID: $AWS_ACCOUNT_ID"

# Set VPC (adjust for your environment)
export VPC_ID="vpc-xxxxxxxxxxxxxxx"
```

### 1.2 (Optional) Configure AWS Bedrock Credentials
If you plan to use the coding agent with AWS Bedrock:
```bash
# Copy template and configure
cp setup-claude-bedrock.sh.template setup-claude-bedrock.sh
vim setup-claude-bedrock.sh

# Update CHANGEME placeholders:
# - AWS_ACCOUNT_ID
# - AWS_ACCESS_KEY_ID
# - AWS_SECRET_ACCESS_KEY
# - AWS_BEARER_TOKEN_BEDROCK (if using bearer token auth)

# Source credentials
source setup-claude-bedrock.sh
```

### 1.3 Verify Configuration
```bash
# Test AWS access
aws sts get-caller-identity

# Expected output:
# {
#     "UserId": "AIDAXXXXXXXXXXXXXXXXX",
#     "Account": "123456789012",
#     "Arn": "arn:aws:iam::123456789012:user/your-username"
# }

# Verify CDK is ready
cdk doctor
```

---

## Step 2: Deploy EC2 Instance with CDK

### 2.1 Deploy the Stack
```bash
# From devtools/aws-cdk directory
cdk deploy \
  -c env=${CDK_ENV_LABEL} \
  -c user=${CDK_USER_LABEL} \
  -c vpc=${VPC_ID} \
  -c account=${AWS_ACCOUNT_ID}

# When prompted with security-sensitive changes, type 'y'
```

### 2.2 Expected Output
```
  Synthesis time: 5.2s

ADE-dev-yourname-Stack: deploying... [1/1]
ADE-dev-yourname-Stack: creating CloudFormation changeset...

  ADE-dev-yourname-Stack

  Deployment time: 179.3s

Outputs:
ADE-dev-yourname-Stack.InstanceId = i-070eca2c6b080b3ed
ADE-dev-yourname-Stack.KeyPairId = key-00d4fbe3473d7450e
ADE-dev-yourname-Stack.PrivateIP = <your-ec2-private-ip>
ADE-dev-yourname-Stack.RetrievePrivateKeyCommand = aws ssm get-parameter --name /ec2/keypair/key-00d4fbe3473d7450e --with-decryption --query 'Parameter.Value' --output text > ~/.ssh/ADE-dev-yourname-key.pem && chmod 400 ~/.ssh/ADE-dev-yourname-key.pem
ADE-dev-yourname-Stack.SSHCommand = ssh -i ~/.ssh/ADE-dev-yourname-key.pem ubuntu@<your-ec2-private-ip>
ADE-dev-yourname-Stack.SessionManagerCommand = aws ssm start-session --target i-070eca2c6b080b3ed

Stack ARN:
arn:aws:cloudformation:us-west-2:123456789012:stack/ADE-dev-yourname-Stack/...

  Total time: 185.86s
```

### 2.3 Resources Created
- **Instance Type**: t3.2xlarge (8 vCPU, 32GB RAM)
- **Storage**:
  - 100GB root volume (gp3)
  - 500GB data volume (gp3, mounted at `/data`)
- **AMI**: Base Ubuntu image (configure for your account)
- **SSH Key**: Auto-generated and stored in AWS Systems Manager Parameter Store
- **Security Group**: SSH access (port 22) configured
- **IAM Role**: SSM access for Session Manager

### 2.4 Save Critical Values
```bash
# Extract and save these for later steps
export INSTANCE_ID="i-070eca2c6b080b3ed"        # From InstanceId output
export KEY_PAIR_ID="key-00d4fbe3473d7450e"      # From KeyPairId output
export PRIVATE_IP="<your-ec2-private-ip>"       # From PrivateIP output
export KEY_PATH="~/.ssh/ADE-dev-yourname-key.pem"

# Print for reference
echo "Instance ID: $INSTANCE_ID"
echo "Private IP: $PRIVATE_IP"
echo "Key Path: $KEY_PATH"
```

---

## Step 3: SSH Key Management

### 3.1 Retrieve SSH Private Key
```bash
# Use the command from CDK output (or construct manually)
aws ssm get-parameter \
  --name /ec2/keypair/${KEY_PAIR_ID} \
  --with-decryption \
  --query 'Parameter.Value' \
  --output text > ~/.ssh/ADE-dev-yourname-key.pem

# Set proper permissions (critical!)
chmod 400 ~/.ssh/ADE-dev-yourname-key.pem

# Verify key was saved
ls -lh ~/.ssh/ADE-dev-yourname-key.pem
# Should show: -r-------- 1 user user 1.7K Nov 10 10:30 ...
```

### 3.2 Test SSH Connection
```bash
# Connect to instance
ssh -i ${KEY_PATH} ubuntu@${PRIVATE_IP}

# First connection will prompt to accept fingerprint:
# "Are you sure you want to continue connecting (yes/no/[fingerprint])?"
# Type: yes

# If successful, you'll see:
# Welcome to Ubuntu 22.04.3 LTS (GNU/Linux 6.8.0-1036-aws x86_64)
# ...
# ubuntu@ip-x-x-x-x:~$
```

### 3.3 Alternative: Session Manager (No SSH Key Required)
```bash
# Connect via AWS Systems Manager (works without SSH key)
aws ssm start-session --target ${INSTANCE_ID}

# This opens an interactive shell without needing the private key
# Useful if SSH key retrieval fails or for additional security
```

---

## Step 4: Wait for Cloud-Init Completion

### 4.1 Monitor Bootstrap Progress
```bash
# SSH to instance (if not already connected)
ssh -i ${KEY_PATH} ubuntu@${PRIVATE_IP}

# Monitor cloud-init log in real-time
tail -f /var/log/cloud-init-output.log
```

### 4.2 What's Being Installed
The cloud-init script automatically installs:
- **Python**: 3.10 and 3.11 (3.11 set as default)
- **Docker**: Latest version with Docker-in-Docker support
- **UV Package Manager**: Fast Python package installer
- **Miniconda**: For optional conda environment management
- **AWS CLI v2**: For S3 and other AWS service access
- **Node.js**: For CDK and other JavaScript tools
- **Build Tools**: gcc, make, git, vim, etc.

### 4.3 Expected Completion Messages
```bash
# You'll see these messages when cloud-init finishes (~5 minutes):

Cloud-init v. 24.3.1-0ubuntu1 finished at Mon, 10 Nov 2025 18:45:32 +0000.
Datasource DataSourceEc2Local.  Up 315.23 seconds

=== Setup Complete ===
Development environment is ready!

Python version: 3.11.7
Docker version: 27.3.1
UV version: 0.4.18
Node version: v22.11.0

All services initialized. You can now proceed with ADEPT bootstrap.
```

### 4.4 Verify Installation
```bash
# Check Python version
python3 --version
# Expected: Python 3.11.x

# Check Docker
docker --version
docker ps  # Should show no errors (empty list is fine)

# Check UV package manager
uv --version
# Expected: uv 0.4.x

# Verify data volume is mounted
df -h /data
# Should show 500GB volume mounted at /data
```

### 4.5 Troubleshooting Cloud-Init
```bash
# If cloud-init seems stuck, check status
cloud-init status

# Expected when complete:
# status: done

# If failed, check error logs
sudo journalctl -u cloud-init -n 50

# Force re-run (if needed, USE WITH CAUTION)
sudo cloud-init clean --logs --reboot
```

---

## Step 5: Bootstrap ADEPT Framework

### 5.1 Prepare Bootstrap Script
```bash
# On your LOCAL machine (not on EC2)
cd devtools/shared/bootstrap

# Install bootstrap dependencies (one-time)
pip install click fabric paramiko rich pyyaml

# Or use a virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt  # If requirements.txt exists
```

### 5.2 Run Bootstrap Script
```bash
# Replace placeholders with your values
python3 bootstrap.py init \
  --host ${PRIVATE_IP} \
  --key ${KEY_PATH} \
  --repo https://github.com/pnnl/adept-agentic.git \
  --token <YOUR_GITHUB_PERSONAL_ACCESS_TOKEN>

# Example with actual values:
python3 bootstrap.py init \
  --host <your-ec2-private-ip> \
  --key ~/.ssh/ADE-dev-demo01-key.pem \
  --repo https://github.com/pnnl/adept-agentic.git \
  --token ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### 5.3 Bootstrap Process Details
The bootstrap script performs these actions:
1. **SSH Connection**: Connects to EC2 instance using provided key
2. **Directory Setup**: Creates `/data/workspace/` with proper permissions
3. **Repository Clone**: Clones ADEPT repository to `/data/workspace/adept-agentic/`
4. **UV Installation**: Verifies UV package manager is installed
5. **Virtual Environment**: Creates Python 3.11 venv using UV
6. **Dependency Sync**: Runs `uv sync --all-extras` to install all packages
7. **Environment Template**: Copies `.env.example` to `.env`

### 5.4 Expected Bootstrap Output
```
+============================================================+
|                ADEPT Framework Bootstrap                     |
+============================================================+

[1/7] Connecting to remote host...
  SSH connection established: ubuntu@<your-ec2-private-ip>

[2/7] Setting up workspace directory...
  Created /data/workspace with proper permissions

[3/7] Cloning ADEPT repository...
  Repository cloned: adept-agentic

[4/7] Verifying UV package manager...
  UV installed: version 0.4.18

[5/7] Creating Python virtual environment...
  Virtual environment created: .venv (Python 3.11.7)

[6/7] Syncing dependencies with UV...
  Resolved 247 packages
  Installed 247 packages

[7/7] Copying environment template...
  Created .env from .env.example

+============================================================+
|              Bootstrap Complete!                             |
+============================================================+

Environment Summary:
  Host:           <your-ec2-private-ip>
  Repository:     adept-agentic
  Python Version: 3.11.7
  Environment:    UV Virtual Environment
  Venv Path:      /data/workspace/adept-agentic/.venv

Next Steps:
  1. Copy your configured .env file to the instance
  2. SSH to the instance and activate the virtual environment
  3. Run 'make start' to launch ADEPT services
```

### 5.5 Verify Bootstrap
```bash
# SSH to the instance
ssh -i ${KEY_PATH} ubuntu@${PRIVATE_IP}

# Navigate to workspace
cd /data/workspace/adept-agentic

# Verify repository structure
ls -la
# Should show: src/, tests/, docker-compose.*.yaml, Makefile, .env, etc.

# Activate virtual environment
source .venv/bin/activate

# Verify Python packages
python -c "import agentic_framework_pkg; print('Package installed')"
# Should print: Package installed
```

---

## Step 6: VS Code Remote Development Setup

VS Code provides two powerful methods for accessing your remote ADEPT services. Choose the approach that best fits your workflow.

### Quick Start: Which Port Forwarding Method?

```
+-------------------------------------+
|  Do you use ADEPT daily?            |
+-------------------+-----------------+
            |
        Yes | No
            |
    +-------v--------+      +------------------+
    |  Method 1:     |      |   Method 2:      |
    |  SSH Config    |      |   Ports Panel    |
    |  (Automatic)   |      |   (Dynamic)      |
    +----------------+      +------------------+
```

**Use Method 1 if**: You are a domain scientist doing daily vibe coding
**Use Method 2 if**: You are testing, demoing, or need temporary access
**Use Both if**: You are a platform engineer who needs flexibility

---

### Method 1: SSH Config with Automatic Port Forwarding (Recommended)

**Best for**: Daily development work where you want ports automatically forwarded on every connection.

#### 6.1.1 Install VS Code Remote-SSH Extension
```bash
# Install via command line (macOS/Linux)
code --install-extension ms-vscode-remote.remote-ssh

# Or install via VS Code UI:
# 1. Open Extensions (Ctrl+Shift+X / Cmd+Shift+X)
# 2. Search for "Remote - SSH"
# 3. Click Install on the Microsoft official extension
```

#### 6.1.2 Configure SSH with Port Forwarding
Edit your SSH config file (`~/.ssh/config`) to include port forwarding directives:

```bash
# Open/create SSH config
vim ~/.ssh/config

# Add this configuration (adjust IP and key path):
Host adept-dev
  HostName <your-ec2-private-ip>                    # Your EC2 private IP
  User ubuntu
  IdentityFile ~/.ssh/ADE-dev-yourname-key.pem      # Your SSH key path

  # ADEPT Service Port Forwarding (9 primary services)
  LocalForward 8888 localhost:8888    # JupyterLab
  LocalForward 8501 localhost:8501    # Streamlit UI (legacy)
  LocalForward 8503 localhost:8503    # Streamlit v2 (Primary interface)
  LocalForward 8083 localhost:8083    # Agent Gateway (API endpoint)
  LocalForward 8180 localhost:8180    # Keycloak Authentication
  LocalForward 8080 localhost:8080    # MCP Server (Main tools)
  LocalForward 8081 localhost:8081    # HPC MCP Server (Nextflow, GitXray)
  LocalForward 8082 localhost:8082    # Sandbox MCP Server (Code execution)
  LocalForward 8086 localhost:8086    # Gateway Registry (Service discovery)

  # Optional: Additional services for debugging
  LocalForward 8084 localhost:8084    # Orchestration Service (internal API)
  LocalForward 5432 localhost:5432    # PostgreSQL database
  LocalForward 6379 localhost:6379    # Redis cache
  LocalForward 8001 localhost:8001    # ChromaDB vector store
  LocalForward 8902 localhost:8902    # OpenWebUI (LLM chat interface)

  # Connection settings for stability
  ServerAliveInterval 60              # Send keepalive every 60 seconds
  ServerAliveCountMax 3               # Disconnect after 3 failed keepalives
  TCPKeepAlive yes                    # Enable TCP keepalive

  # Performance optimization
  Compression yes                     # Enable compression for faster transfers
  ControlMaster auto                  # Reuse connections
  ControlPath ~/.ssh/control-%r@%h:%p # Control socket path
  ControlPersist 10m                  # Keep connection alive for 10 minutes
```

#### 6.1.3 Connect via VS Code

**Option A: Command Palette Method**
```
1. Press Ctrl+Shift+P (Windows/Linux) or Cmd+Shift+P (macOS)
2. Type "Remote-SSH: Connect to Host"
3. Select "adept-dev" from the list
4. Wait for VS Code to connect (10-20 seconds)
5. Once connected, you'll see "SSH: adept-dev" in the bottom-left corner
```

**Option B: Terminal Method**
```bash
# Opens VS Code with remote connection and workspace
code --remote ssh-remote+adept-dev /data/workspace/adept-agentic
```

**Option C: VS Code UI Method**
```
1. Click the green remote icon in bottom-left corner
2. Select "Connect to Host..." from the menu
3. Choose "adept-dev"
```

#### 6.1.4 Verify Port Forwarding
Once connected, open your local browser and test each service:

```bash
# Primary Services (Test These First)
http://localhost:8503  -> Streamlit v2 (Login: notebook-user / notebook-password)
http://localhost:8888  -> JupyterLab (Token from logs: docker logs jupyterlab 2>&1 | grep token)
http://localhost:8083  -> Agent Gateway API (Should see "Not Found" - API is working)
http://localhost:8180  -> Keycloak Admin Console (Login: admin / admin)

# MCP Tool Servers (For Testing)
http://localhost:8080  -> MCP Server health check
http://localhost:8081  -> HPC MCP Server health check
http://localhost:8082  -> Sandbox MCP Server health check

# Service Discovery
http://localhost:8086  -> Gateway Registry health check

# Optional Debugging Services
http://localhost:8084  -> Orchestration Service (Internal API docs)
http://localhost:8902  -> OpenWebUI (LLM chat interface)
```

#### 6.1.5 Troubleshooting SSH Config Method

**Issue: Ports don't forward automatically**
```bash
# Verify SSH config syntax
ssh -T adept-dev  # Should connect without errors

# Check for active port forwarding
ssh -v adept-dev 2>&1 | grep "Local forwarding"
# Should show: Local forwarding listening on 127.0.0.1:8503

# Kill any zombie SSH sessions
pkill -f "ssh.*adept-dev"
```

**Issue: "Address already in use"**
```bash
# Find what's using the port
lsof -ti:8503

# Kill the process (if safe to do so)
kill -9 $(lsof -ti:8503)

# Or use a different local port in .ssh/config:
LocalForward 18503 localhost:8503  # Access via localhost:18503
```

**Issue: Connection drops frequently**
```bash
# Increase keepalive frequency in .ssh/config
ServerAliveInterval 30              # Reduce to 30 seconds
ServerAliveCountMax 6               # Increase to 6 attempts

# Or keep a persistent connection
ssh -N -f adept-dev  # Background SSH tunnel
```

---

### Method 2: VS Code Ports Panel (Dynamic Forwarding)

**Best for**: Ad-hoc port forwarding, testing new services, or when you don't want persistent tunnels.

**Reference**: [Official VS Code Port Forwarding Docs](https://code.visualstudio.com/docs/debugtest/port-forwarding)

#### 6.2.1 Open the Ports Panel
```
Option A (Keyboard Shortcut):
  1. Press Ctrl+Shift+P / Cmd+Shift+P
  2. Type "Ports: Focus on Ports View"
  3. Press Enter

Option B (UI Navigation):
  1. Click the "Ports" tab in the lower panel area
     (Next to Terminal, Output, Problems tabs)
  2. If not visible, right-click panel and select "Ports"
```

#### 6.2.2 Forward a Port (Step-by-Step UI Guide)

**Step 1: Click "Forward a Port"**
- Look for the "+" icon or "Forward a Port" button in the Ports panel
- Click it to open the port forwarding dialog

**Step 2: Enter Port Number**
```
Prompt: "Port number or address (e.g. 3000 or 10.10.10.10:3000)"
Enter: 8503
Press: Enter
```

**Step 3: First-Time GitHub Authentication** (Only required once)
```
1. VS Code prompts: "Sign in to use port forwarding"
2. Click "Sign in with GitHub"
3. Browser opens -> Authorize VS Code
4. Return to VS Code -> Authentication complete

Note: VS Code uses an outbound connection to Azure to create a secure tunnel.
      This enables port forwarding even through corporate firewalls.
```

**Step 4: Access the Forwarded Port**
```
Ports panel now shows:
+----------+-----------------------------+--------------+
| Port     | Forwarded Address           | Running Proc |
+----------+-----------------------------+--------------+
| 8503     | https://abc123.devtunnels   | streamlit_v2 |
|          | ms.com                       |              |
+----------+-----------------------------+--------------+

Hover actions:
  Copy URL           - Copy public URL to clipboard
  Open in Browser    - Open in your default browser
  Open Preview       - Open in VS Code embedded browser
  Port Visibility    - Toggle public/private access
  Set Label          - Add custom label (e.g., "Streamlit v2")
```

#### 6.2.3 Forward All ADEPT Services (Batch Method)

Repeat step 6.2.2 for each service. Here's the complete list:

```
+------+--------------------------+-----------------------------+
| Port | Service                  | Access URL (local)          |
+------+--------------------------+-----------------------------+
| 8503 | Streamlit v2 (primary)   | http://localhost:8503       |
| 8888 | JupyterLab              | http://localhost:8888       |
| 8501 | Streamlit UI (legacy)   | http://localhost:8501       |
| 8083 | Agent Gateway           | http://localhost:8083       |
| 8180 | Keycloak Auth           | http://localhost:8180       |
| 8080 | MCP Server (Main)       | http://localhost:8080       |
| 8081 | HPC MCP Server          | http://localhost:8081       |
| 8082 | Sandbox MCP Server      | http://localhost:8082       |
| 8086 | Gateway Registry        | http://localhost:8086       |
+------+--------------------------+-----------------------------+

Primary interface for domain scientists: port 8503
```

**Pro Tip: Use Labels and Auto-Forward**
```
For each forwarded port:
  1. Right-click the port -> "Set Port Label"
  2. Enter descriptive name: "Streamlit v2 - Vibe Coding"
  3. Right-click again -> Enable "Auto Forward"
     (Port will automatically forward in future sessions)
```

#### 6.2.4 Port Management in Ports Panel

**View Active Ports**
```
All forwarded ports appear in the Ports panel with:
- Port number
- Forwarded address (local or public URL)
- Running process name
- Visibility status (public/private)
```

**Stop Forwarding a Port**
```
1. Right-click the port in Ports panel
2. Select "Stop Forwarding Port"
3. Port is released and no longer accessible
```

**Change Port Visibility**
```
Right-click port -> "Port Visibility"
  - Private: Only accessible on localhost
  - Public: Accessible via public URL (requires GitHub auth)
```

**Set Custom Port Label**
```
Right-click port -> "Set Port Label"
Example labels:
  - "Streamlit v2 - Main UI"
  - "JupyterLab - Dev Notebooks"
  - "Agent Gateway - API"
```

**Enable Auto-Forward**
```
Right-click port -> Check "Auto Forward"
VS Code will automatically forward this port in future sessions
```

#### 6.2.5 Troubleshooting Ports Panel Method

**Issue: GitHub authentication fails**
```bash
# Clear VS Code authentication cache
rm -rf ~/.config/Code/User/globalStorage/ms-vscode-remote.*

# Restart VS Code
code --reboot-window

# Try authenticating again
# You may need to revoke and re-grant permissions at:
# https://github.com/settings/connections/applications
```

**Issue: Port shows as "Not Forwarded"**
```
Possible causes:
1. Service not running on remote host
   -> Check: ssh adept-dev "docker ps | grep streamlit"

2. Port already in use locally
   -> Check: lsof -ti:8503
   -> Kill process: kill -9 $(lsof -ti:8503)

3. Firewall blocking connection
   -> Check: curl -I http://localhost:8503
```

**Issue: Can't access forwarded service in browser**
```bash
# 1. Verify service is running on remote host
ssh adept-dev "docker ps --format 'table {{.Names}}\t{{.Ports}}'"

# 2. Test port locally with curl
curl -v http://localhost:8503

# 3. Check for firewall issues
# Some corporate VPNs block localhost tunneling
# Try using the public URL instead (if visibility is set to "public")
```

---

### Method Comparison: SSH Config vs. Ports Panel

| Feature | SSH Config (Method 1) | Ports Panel (Method 2) |
|---------|----------------------|------------------------|
| **Setup Time** | 5 minutes (one-time) | 30 seconds per port |
| **Persistence** | Auto-forwards on every connection | Manual each session (unless auto-forward enabled) |
| **Best For** | Daily development workflow | Testing, demos, debugging |
| **Authentication** | SSH key only | GitHub OAuth (first time) |
| **Connection Type** | Direct SSH tunnel | VS Code secure tunnel via Azure |
| **Network Requirements** | Direct access to EC2 (VPN may be required) | Works through corporate firewalls |
| **Port Management** | Edit `.ssh/config` file | Dynamic via UI (point-and-click) |
| **Performance** | Direct connection (low latency) | Routes through Azure (slight latency) |
| **Bandwidth Usage** | Low (direct tunnel) | Moderate (Azure relay) |
| **Security** | SSH key-based encryption | GitHub OAuth + Azure tunnel encryption |
| **Offline Mode** | Requires active SSH connection | Requires internet + Azure access |
| **Multi-Machine** | Configure on each machine | Auto-syncs via GitHub account |
| **Recommended For** | **Domain Scientists** (set and forget) | **Platform Engineers** (flexibility) |

**Pro Tip**: Use **Method 1** for your primary workflow (automatic port forwarding), and **Method 2** for ad-hoc testing of additional services or when working from different locations.

---

## Step 7: Configure & Start Services

### 7.1 Copy Your Configured .env File
```bash
# From your LOCAL machine (not on EC2)
# If you have a pre-configured .env file:
scp -i ${KEY_PATH} .env \
  ubuntu@${PRIVATE_IP}:/data/workspace/adept-agentic/

# Or copy the template and edit manually on the instance:
ssh -i ${KEY_PATH} ubuntu@${PRIVATE_IP}
cd /data/workspace/adept-agentic
cp .env.example .env
vim .env  # Edit with your settings
```

### 7.2 Configure Critical Environment Variables
```bash
# Minimum required configuration in .env:

# LLM Configuration
DEFAULT_MODEL=gpt-4o
CODING_AGENT_DEFAULT_MODEL=bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0

# AWS Bedrock Credentials (for coding agent)
AWS_ACCESS_KEY_ID=your_access_key_id
AWS_SECRET_ACCESS_KEY=your_secret_access_key
AWS_REGION_NAME=us-west-2

# Database (leave defaults for local development)
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=agenticframework
POSTGRES_USER=agenticframework
POSTGRES_PASSWORD=securepassword

# Keycloak (leave defaults for local development)
KEYCLOAK_REALM=agenticframework
KEYCLOAK_CLIENT_ID=gateway-service
KEYCLOAK_CLIENT_SECRET=your_keycloak_secret
KEYCLOAK_URL=http://keycloak:8180

# Service URLs (internal Docker network - don't change)
GATEWAY_URL=http://agent_gateway:8081
ORCHESTRATION_URL=http://orchestration_service:8084
MCP_SERVER_URL=http://mcp_server:8080
HPC_MCP_SERVER_URL=http://hpc_mcp_server:8081
SANDBOX_MCP_SERVER_URL=http://sandbox_mcp_server:8082
```

### 7.3 Initialize Docker Permissions
```bash
# SSH to the instance
ssh -i ${KEY_PATH} ubuntu@${PRIVATE_IP}

# Navigate to ADEPT directory
cd /data/workspace/adept-agentic

# Activate virtual environment
source .venv/bin/activate

# Fix Docker volume permissions (CRITICAL - run first!)
make init-shared-volume-permissions

# Expected output:
# --> Initializing shared volume permissions...
# Creating shared directories: data/uploaded_files/sessions/...
# Setting permissions to 777 for multi-user access
# Permissions initialized
```

### 7.4 Start All ADEPT Services
```bash
# Start the entire stack (builds if needed)
make start

# This command:
# 1. Pulls base images (if not cached)
# 2. Builds custom images (agent_gateway, orchestration_service, etc.)
# 3. Starts 15 containers via docker-compose
# 4. Initializes databases and services
# 5. Runs health checks

# Expected duration: 5-7 minutes (first run), 2-3 minutes (subsequent runs)
```

### 7.5 Monitor Startup Progress
```bash
# Watch all containers start
docker ps --format "table {{.Names}}\t{{.Status}}"

# Expected output when ready:
# NAMES                       STATUS
# streamlit_app_v2           Up 2 minutes (healthy)
# agent_gateway              Up 3 minutes (healthy)
# orchestration_service      Up 3 minutes (healthy)
# mcp_server                 Up 3 minutes (healthy)
# hpc_mcp_server             Up 3 minutes (healthy)
# sandbox_mcp_server         Up 3 minutes (healthy)
# gateway_registry           Up 3 minutes (healthy)
# keycloak                   Up 4 minutes (healthy)
# postgres                   Up 4 minutes (healthy)
# redis                      Up 4 minutes (healthy)
# chromadb                   Up 4 minutes (healthy)
# jupyterlab                 Up 2 minutes
# nginx_proxy                Up 2 minutes
# n8n                        Up 2 minutes
# openwebui                  Up 2 minutes

# Monitor specific service logs
docker logs orchestration_service -f   # Core orchestration
docker logs agent_gateway -f           # API gateway
docker logs mcp_server -f              # MCP tools
```

### 7.6 Validate Service Health
```bash
# Run comprehensive health checks
make validate-service-health

# Expected output:
# --> Validating service health...
# Keycloak: Healthy (http://keycloak:8180)
# PostgreSQL: Healthy (postgres:5432)
# Redis: Healthy (redis:6379)
# Agent Gateway: Healthy (http://agent_gateway:8081)
# Orchestration Service: Healthy (http://orchestration_service:8084)
# MCP Server: Healthy (http://mcp_server:8080)
# HPC MCP Server: Healthy (http://hpc_mcp_server:8081)
# Sandbox MCP Server: Healthy (http://sandbox_mcp_server:8082)
# Gateway Registry: Healthy (http://gateway_registry:8086)
# All services healthy!

# Validate credentials
make validate-credentials

# Validate MCP tool discovery
make validate-mcp-tools-discovery

# Run core validation suite
make validate
```

### 7.7 Access ADEPT Interfaces
With port forwarding configured (Step 6), open these URLs in your **local browser**:

```
Primary Interface:
  http://localhost:8503  -> Streamlit v2 (Vibe Coding Interface)
     Login: notebook-user / notebook-password

Development Interfaces:
  http://localhost:8888  -> JupyterLab
     Token: Check logs with 'docker logs jupyterlab 2>&1 | grep token'

  http://localhost:8501  -> Streamlit UI (Legacy)

API & Admin:
  http://localhost:8083  -> Agent Gateway (API endpoint)
  http://localhost:8180  -> Keycloak (Admin: admin / admin)
  http://localhost:8086  -> Gateway Registry

MCP Tool Servers:
  http://localhost:8080  -> MCP Server (Main tools)
  http://localhost:8081  -> HPC MCP Server
  http://localhost:8082  -> Sandbox MCP Server
```

### 7.8 First Login Test
```bash
# Test Streamlit v2 login:
# 1. Open http://localhost:8503
# 2. Enter credentials:
#    Username: notebook-user
#    Password: notebook-password
# 3. You should see the ADEPT chat interface

# Test JupyterLab:
# 1. Get token: docker logs jupyterlab 2>&1 | grep token
# 2. Open http://localhost:8888
# 3. Paste token when prompted
# 4. You should see the JupyterLab interface

# Test Agent Gateway API:
# 1. Open http://localhost:8083/docs
# 2. You should see OpenAPI/Swagger documentation
```

---

## Quick Reference Commands

### One-Liner: Complete Deployment
```bash
# Deploy EC2, bootstrap, configure, and start services (replace placeholders)
cdk deploy -c env=dev -c user=yourname \
  -c vpc=vpc-xxxxxxxxxxxxxxx \
  -c account=123456789012 && \
python3 ../shared/bootstrap/bootstrap.py init \
  --host <PRIVATE_IP> \
  --key ~/.ssh/ADE-dev-yourname-key.pem \
  --repo https://github.com/pnnl/adept-agentic.git \
  --token <GITHUB_TOKEN> && \
scp -i ~/.ssh/ADE-dev-yourname-key.pem .env \
  ubuntu@<PRIVATE_IP>:/data/workspace/adept-agentic/ && \
ssh -i ~/.ssh/ADE-dev-yourname-key.pem ubuntu@<PRIVATE_IP> \
  "cd /data/workspace/adept-agentic && \
   source .venv/bin/activate && \
   make init-shared-volume-permissions && \
   make start"
```

### Daily Development Workflow
```bash
# Morning: Start services
ssh -i ${KEY_PATH} ubuntu@${PRIVATE_IP}
cd /data/workspace/adept-agentic
source .venv/bin/activate
make start

# Development: Make code changes, rebuild specific services
make rebuild-orchestrator        # Rebuild orchestration service
make rebuild-mcp-servers        # Rebuild all MCP servers
make validate                   # Run tests

# Evening: Stop services
make stop
```

### Service Management
```bash
# Start all services
make start

# Stop all services
make stop

# Restart all services
make restart

# Rebuild specific service
make rebuild-gateway            # Agent Gateway
make rebuild-orchestrator       # Orchestration Service
make rebuild-mcp-servers        # All 3 MCP servers
make rebuild-streamlit-app-v2   # Streamlit v2 UI

# Complete rebuild (nuclear option)
make rebuild                    # Full rebuild with --no-cache

# Teardown (removes containers, networks, volumes)
make teardown

# Erase (teardown + prune all Docker data)
make erase  # WARNING: Removes ALL Docker data
```

### Validation & Testing
```bash
# Quick validation suite
make validate

# Comprehensive validation
make validate-all

# Specific validations
make validate-service-health
make validate-credentials
make validate-mcp-tools-discovery
make validate-multi-agent
make validate-bedrock-connectivity

# Fix common issues
make fix-credentials           # Auto-repair auth issues
make init-shared-volume-permissions  # Fix Docker permissions
```

### Monitoring & Debugging
```bash
# View all container statuses
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# View specific service logs
docker logs orchestration_service -f
docker logs agent_gateway -f
docker logs mcp_server -f

# Check container health
docker inspect orchestration_service | grep -A 10 Health

# Enter a running container
docker exec -it orchestration_service bash

# View resource usage
docker stats
```

---

## Instance Management

### Stop Instance (Save Costs)
```bash
# Stop instance when not in use (saves ~$300/month)
aws ec2 stop-instances --instance-ids ${INSTANCE_ID}

# Verify instance stopped
aws ec2 describe-instances \
  --instance-ids ${INSTANCE_ID} \
  --query 'Reservations[0].Instances[0].State.Name'
# Expected: "stopped"
```

### Start Instance
```bash
# Start instance when ready to work
aws ec2 start-instances --instance-ids ${INSTANCE_ID}

# Wait for instance to be running
aws ec2 wait instance-running --instance-ids ${INSTANCE_ID}

# Get new private IP (may change after restart)
export PRIVATE_IP=$(aws ec2 describe-instances \
  --instance-ids ${INSTANCE_ID} \
  --query 'Reservations[0].Instances[0].PrivateIpAddress' \
  --output text)

echo "New Private IP: ${PRIVATE_IP}"

# Update .ssh/config with new IP if changed
```

### Destroy Stack Completely
```bash
# WARNING: This deletes ALL resources (instance, volumes, SSH key)
# Backup any important data first!

cd devtools/aws-cdk

cdk destroy ADE-dev-yourname-Stack

# Confirm deletion when prompted
# Type: yes
```

### Alternative: Session Manager (No SSH Key)
```bash
# Connect without SSH key (useful if key is lost)
aws ssm start-session --target ${INSTANCE_ID}

# This opens an interactive shell
# Useful for emergency access or debugging
```

### Instance Cost Optimization
```bash
# Monthly costs (approximate):
# - EC2 t3.2xlarge (running 24/7): ~$300/month
# - Storage (600GB EBS): ~$48/month
# - Data transfer: Variable (typically $10-50/month)
# Total running cost: ~$360/month

# Cost savings strategies:
# 1. Stop instance when not in use: Save $300/month
# 2. Use smaller instance for testing: t3.xlarge saves $150/month
# 3. Delete old snapshots: Save $5-10/month
# 4. Use spot instances (non-production): Save up to 70%

# Clean up Docker to free disk space
ssh -i ${KEY_PATH} ubuntu@${PRIVATE_IP}
docker system prune -a  # Removes unused images, containers, volumes
# Can reclaim 10-50GB
```

---

## Troubleshooting

### Common Issues & Fixes

#### Issue: CDK Bootstrap Fails
```
Error: Need to perform AWS calls for account XXX, but no credentials found
```
**Solution**:
```bash
# Ensure AWS credentials are configured
aws sts get-caller-identity

# If fails, reconfigure AWS CLI
aws configure

# Or set environment variables
export AWS_ACCESS_KEY_ID="your_key"
export AWS_SECRET_ACCESS_KEY="your_secret"
export AWS_DEFAULT_REGION="us-west-2"
```

#### Issue: CDK Deploy Fails with "No VPC Found"
```
Error: Cannot find VPC vpc-xxxxxxxxxxxxxxx
```
**Solution**:
```bash
# Verify VPC exists in your account/region
aws ec2 describe-vpcs --vpc-ids vpc-xxxxxxxxxxxxxxx

# If VPC doesn't exist, use a different VPC ID
aws ec2 describe-vpcs --query 'Vpcs[*].[VpcId,Tags[?Key==`Name`].Value|[0]]'

# Update CDK deploy command with correct VPC
export VPC_ID="vpc-xxxxxxxx"
```

#### Issue: SSH Connection Refused
```
ssh: connect to host <your-ec2-private-ip> port 22: Connection refused
```
**Solution**:
```bash
# 1. Verify instance is running
aws ec2 describe-instances --instance-ids ${INSTANCE_ID} \
  --query 'Reservations[0].Instances[0].State.Name'

# 2. If stopped, start the instance
aws ec2 start-instances --instance-ids ${INSTANCE_ID}

# 3. Wait for instance to be ready
aws ec2 wait instance-running --instance-ids ${INSTANCE_ID}

# 4. Verify security group allows SSH (port 22)
aws ec2 describe-security-groups \
  --filters Name=group-name,Values="ADE-dev-yourname-*" \
  --query 'SecurityGroups[*].IpPermissions[?FromPort==`22`]'

# 5. Try Session Manager as alternative
aws ssm start-session --target ${INSTANCE_ID}
```

#### Issue: Cloud-Init Takes Too Long
```
Waiting for cloud-init... (>10 minutes)
```
**Solution**:
```bash
# Check cloud-init status
ssh -i ${KEY_PATH} ubuntu@${PRIVATE_IP}
cloud-init status

# If stuck, check logs for errors
sudo tail -f /var/log/cloud-init-output.log

# Look for specific error messages
sudo journalctl -u cloud-init -n 100

# If truly stuck, force reboot (last resort)
aws ec2 reboot-instances --instance-ids ${INSTANCE_ID}
```

#### Issue: Bootstrap Script Fails
```
Error: Permission denied (publickey)
```
**Solution**:
```bash
# Verify SSH key permissions
chmod 400 ${KEY_PATH}
ls -l ${KEY_PATH}
# Should show: -r-------- 1 user user ...

# Test SSH connection manually
ssh -i ${KEY_PATH} ubuntu@${PRIVATE_IP} -v
# Look for authentication errors in verbose output

# Verify key was retrieved correctly from SSM
aws ssm get-parameter \
  --name /ec2/keypair/${KEY_PAIR_ID} \
  --with-decryption \
  --query 'Parameter.Value' \
  --output text | head -1
# Should show: -----BEGIN RSA PRIVATE KEY-----
```

#### Issue: Docker Permission Denied
```
Got permission denied while trying to connect to the Docker daemon socket
```
**Solution**:
```bash
# Add ubuntu user to docker group (should be done by cloud-init)
sudo usermod -aG docker ubuntu

# Log out and log back in for group changes to take effect
exit
ssh -i ${KEY_PATH} ubuntu@${PRIVATE_IP}

# Verify docker works without sudo
docker ps

# If still fails, restart Docker
sudo systemctl restart docker
```

#### Issue: Make Start Fails
```
Error: No such file or directory: '.env'
```
**Solution**:
```bash
# Ensure .env file exists
ls -la .env

# If missing, copy from template
cp .env.example .env

# Or copy your pre-configured .env
scp -i ${KEY_PATH} .env \
  ubuntu@${PRIVATE_IP}:/data/workspace/adept-agentic/
```

#### Issue: Services Don't Start
```
Error: Container orchestration_service is unhealthy
```
**Solution**:
```bash
# Check specific container logs
docker logs orchestration_service --tail 100

# Common causes:
# 1. Database connection failed
docker logs postgres --tail 50

# 2. Redis connection failed
docker logs redis --tail 50

# 3. Port already in use
sudo netstat -tulpn | grep :8084

# 4. Permission issues
make init-shared-volume-permissions

# 5. Rebuild the failing service
make rebuild-orchestrator

# 6. Nuclear option: complete rebuild
make erase && make start
```

#### Issue: Port Forwarding Not Working
```
curl: (7) Failed to connect to localhost port 8503
```
**Solution**:
```bash
# Method 1 (SSH Config): Verify SSH connection is active
ps aux | grep "ssh.*adept-dev"

# If not running, reconnect
code --remote ssh-remote+adept-dev /data/workspace/adept-agentic

# Verify port forwarding is active
lsof -i :8503
# Should show: ssh ... TCP localhost:8503 (LISTEN)

# Method 2 (Ports Panel): Check VS Code Ports panel
# Ensure port shows "Forwarded" status

# Test on remote host first
ssh -i ${KEY_PATH} ubuntu@${PRIVATE_IP}
curl -I http://localhost:8503
# Should return 200 OK

# If works on remote but not local, firewall/VPN may be blocking
```

#### Issue: Out of Disk Space
```
Error: No space left on device
```
**Solution**:
```bash
# Check disk usage
df -h

# Clean up Docker artifacts
docker system prune -a
# WARNING: This removes all unused images, containers, volumes

# Check what's using space
du -sh /data/workspace/* | sort -h

# Remove old logs
find /data/workspace -name "*.log" -mtime +7 -delete

# If still out of space, consider increasing data volume size
# (Requires AWS console or CLI - see AWS EBS documentation)
```

#### Issue: VS Code Remote Connection Drops
```
VS Code: "Connection to SSH server lost"
```
**Solution**:
```bash
# Update .ssh/config with better keepalive settings
Host adept-dev
  ...
  ServerAliveInterval 30       # More frequent keepalives
  ServerAliveCountMax 6        # More retries before disconnect
  TCPKeepAlive yes

# Keep a persistent background SSH tunnel
ssh -N -f adept-dev  # Runs in background

# Or use mosh (mobile shell) for unstable connections
# Install on both local and remote:
brew install mosh  # macOS
sudo apt-get install mosh  # Ubuntu

mosh ubuntu@${PRIVATE_IP}  # More resilient than SSH
```

---

## Next Steps

### Deployment Complete! What's Next?

**Immediate Actions**:
1. Bookmark your local ADEPT URLs:
   - http://localhost:8503 (Streamlit v2)
   - http://localhost:8888 (JupyterLab)
   - http://localhost:8083 (Agent Gateway API)

2. Test basic functionality:
   - Login to Streamlit v2
   - Upload a test file
   - Try a simple query: "List all available tools"

3. Review documentation:
   - [DOMAIN_SME_VIBE_CODING_GUIDE.md](../docs/DOMAIN_SME_VIBE_CODING_GUIDE.md) - Vibe coding workflows
   - [CLAUDE.md](../CLAUDE.md) - Architecture and development patterns
   - [README.md](../README.md) - Project overview

### Start Vibe Coding

**For Domain Scientists**:
```markdown
Proceed to: docs/DOMAIN_SME_VIBE_CODING_GUIDE.md

Learn how to:
- Upload domain-specific datasets
- Create analysis workflows with natural language
- Build metabolic models interactively
- Use RAG for literature-informed coding
- Execute code safely in sandbox environments
```

**For Platform Engineers**:
```markdown
Proceed to: CLAUDE.md

Learn about:
- Three-tier architecture (Gateway, Orchestration, MCP Servers)
- Multi-agent orchestration patterns
- MCP tool development lifecycle
- Testing and validation strategies
- Production deployment considerations
```

### Advanced Topics

**Week 2+**:
- [ ] Create your first custom MCP tool
- [ ] Set up multi-agent coding sessions
- [ ] Integrate your domain-specific databases
- [ ] Configure RAG for your literature corpus
- [ ] Optimize LLM model selection for your use case

**Month 2+**:
- [ ] Deploy to production with AWS CDK (see `docs/architecture/AWS_CDK_STACK_ARCHITECTURE.md`)
- [ ] Set up CI/CD pipeline with GitHub Actions
- [ ] Implement custom authentication with Keycloak
- [ ] Scale horizontally with Kubernetes (see `infra/helm/`)
- [ ] Fine-tune LLMs for your domain

### Best Practices Reminder

1. **Stop EC2 instance when not in use** - Save $300/month
2. **Commit code regularly** - Use feature branches
3. **Run validation tests** - `make validate` before committing
4. **Monitor disk usage** - `df -h /data` regularly
5. **Keep .env secure** - Never commit credentials to Git
6. **Update regularly** - `git pull origin main` weekly
7. **Backup important data** - Use S3 or EBS snapshots

### Getting Help

**Support Resources**:
- **GitHub Issues**: [https://github.com/pnnl/adept-agentic/issues](https://github.com/pnnl/adept-agentic/issues)
- **Documentation**: `/docs` directory in repository
- **Architecture Guide**: `CLAUDE.md`
- **Slack/Teams Channel**: #adept-support (if available)
- **Office Hours**: Check with your team lead

**Debug Commands**:
```bash
# Comprehensive health check
make validate-service-health
make validate-comprehensive-health
python scripts/deps/service_health_manager.py --health-check

# View system status
docker ps --format "table {{.Names}}\t{{.Status}}"
docker stats --no-stream

# Check logs
docker logs orchestration_service --tail 100
docker logs agent_gateway --tail 100
```

---

## Appendix: Architecture Diagram

```mermaid
graph TB
    subgraph "Local Machine"
        VS[VS Code]
        Browser[Web Browser]
    end

    subgraph "AWS EC2 Instance (t3.2xlarge)"
        subgraph "ADEPT Stack - Application Layer"
            JL[JupyterLab<br/>:8888]
            ST[Streamlit UI<br/>:8501]
            ST2[Streamlit v2<br/>:8503]
        end

        subgraph "ADEPT Stack - Core Services"
            GW[Agent Gateway<br/>:8083<br/>Tier 1: Auth]
            OS[Orchestration Service<br/>:8084<br/>Tier 2: Brain]
            MCP1[MCP Server<br/>:8080<br/>Tier 3: Tools]
            MCP2[HPC MCP<br/>:8081<br/>Tier 3: HPC]
            MCP3[Sandbox MCP<br/>:8082<br/>Tier 3: Code Exec]
        end

        subgraph "ADEPT Stack - Infrastructure"
            KC[Keycloak<br/>:8180<br/>Auth Server]
            PG[PostgreSQL<br/>:5432<br/>State DB]
            RD[Redis<br/>:6379<br/>Cache]
            CD[ChromaDB<br/>:8001<br/>Vector Store]
        end
    end

    subgraph "External Services"
        AWS[AWS Bedrock<br/>Claude Models]
        GH[GitHub<br/>Source Control]
    end

    VS -->|SSH Port Forwarding<br/>or VS Code Tunnel| JL
    VS -->|SSH Port Forwarding<br/>or VS Code Tunnel| ST2
    Browser --> JL
    Browser --> ST2

    JL --> GW
    ST --> GW
    ST2 --> GW
    GW --> OS
    OS --> MCP1
    OS --> MCP2
    OS --> MCP3
    OS --> AWS

    GW --> KC
    OS --> PG
    OS --> RD
    MCP1 --> CD

    VS --> GH
    OS --> GH
```

---

## Appendix: Environment Variables Reference

### Minimal .env Configuration
```bash
# LLM Configuration
DEFAULT_MODEL=gpt-4o
CODING_AGENT_DEFAULT_MODEL=bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0

# AWS Bedrock
AWS_ACCESS_KEY_ID=AKIAXXXXXXXXXXXXX
AWS_SECRET_ACCESS_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
AWS_REGION_NAME=us-west-2

# Database (default values for local development)
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=agenticframework
POSTGRES_USER=agenticframework
POSTGRES_PASSWORD=securepassword

# Keycloak (default values for local development)
KEYCLOAK_REALM=agenticframework
KEYCLOAK_CLIENT_ID=gateway-service
KEYCLOAK_CLIENT_SECRET=generate_a_secure_secret_here
KEYCLOAK_URL=http://keycloak:8180

# Service URLs (internal Docker network)
GATEWAY_URL=http://agent_gateway:8081
ORCHESTRATION_URL=http://orchestration_service:8084
MCP_SERVER_URL=http://mcp_server:8080
HPC_MCP_SERVER_URL=http://hpc_mcp_server:8081
SANDBOX_MCP_SERVER_URL=http://sandbox_mcp_server:8082
```

### Complete .env Configuration
See `.env.example` in the repository root for the full configuration template with all available options.

---

## Appendix: Instance Specifications

| Component | Specification | Notes |
|-----------|---------------|-------|
| **Instance Type** | t3.2xlarge | 8 vCPU, 32GB RAM |
| **Root Volume** | 100GB gp3 | OS and system files |
| **Data Volume** | 500GB gp3 | `/data` - workspace and Docker |
| **AMI** | Ubuntu 22.04 LTS | Configure for your account |
| **Operating System** | Ubuntu 22.04 LTS | Kernel 6.8.0-1036-aws |
| **Python** | 3.11.7 (default) | Also includes 3.10 |
| **Docker** | 27.3.1 | With Docker-in-Docker |
| **UV Package Manager** | 0.4.18 | Fast Python package installer |
| **Node.js** | v22.11.0 | For CDK and tooling |
| **AWS CLI** | v2.x | Latest version |
| **Networking** | Private IP only | Access via VPN or bastion |
| **IAM Role** | SSM access | For Session Manager |

---

**End of AWS VM Deployment Guide**

For questions or issues, please open a GitHub issue or contact the ADEPT platform team.

**Next**: [DOMAIN_SME_VIBE_CODING_GUIDE.md](../docs/DOMAIN_SME_VIBE_CODING_GUIDE.md) - Start your vibe coding journey!
