# ADEPT Bootstrap Tool

Team-agnostic development environment setup for ADEPT framework. Supports multiple Git sources (GitHub, GitLab) and provides both Python (with Fabric) and Bash implementations.

## Features

- 🚀 **Quick Setup**: Initialize complete ADEPT development environment in minutes
- 🔧 **Multi-Tool Support**: UV and Conda package managers
- 🌐 **Multi-Git Support**: Works with GitHub, GitLab, and other Git providers
- 👥 **Team Agnostic**: Configuration-driven for different teams
- 🐍 **Python & Bash**: Choose your preferred implementation
- ✅ **Validation**: Built-in environment verification
- 🔒 **Secure**: PAT token support for private repositories

## Prerequisites

### On Your Local Machine
- SSH client
- Python 3.10+ (for Python version)
- Bash (for Bash version)

### On Target EC2 Instance
The EC2 instance should be provisioned using the ADEPT CDK stack which includes:
- Ubuntu 22.04 LTS
- Docker and Docker Compose
- Python 3.10, 3.11, 3.12
- UV package manager
- Miniconda3
- 500GB data volume at `/data`

## Installation

### Python Version

```bash
# Clone this repository
git clone https://github.com/pnnl/adept-agentic.git
cd adept-agentic-framework-extended/devtools/shared/bootstrap

# Install dependencies
pip install -r requirements.txt
# OR using UV
uv pip install click fabric rich pyyaml python-dotenv paramiko

# Make executable
chmod +x bootstrap.py
```

### Bash Version

```bash
# Just make it executable
chmod +x bootstrap.sh
```

## Usage

### Python CLI

#### Initialize Environment

```bash
# Basic initialization with UV
python bootstrap.py init \
  --host 10.0.0.1 \
  --key ~/.ssh/ADE-dev-key.pem \
  --repo https://github.com/pnnl/adept-agentic.git \
  --token ghp_xxxxxxxxxxxx

# With Conda environment
python bootstrap.py init \
  --host 10.0.0.1 \
  --key ~/.ssh/ADE-dev-key.pem \
  --repo https://code.emsl.pnnl.gov/team/adept.git \
  --use-conda \
  --conda-env adept-dev \
  --python 3.11

# With specific branch and folder
python bootstrap.py init \
  --host 10.0.0.1 \
  --key ~/.ssh/ADE-dev-key.pem \
  --repo https://github.com/pnnl/adept-agentic.git \
  --token ghp_xxxxxxxxxxxx \
  --branch develop \
  --folder my-adept-workspace
```

#### Validate Environment

```bash
# Run all validations
python bootstrap.py validate \
  --host 10.0.0.1 \
  --key ~/.ssh/ADE-dev-key.pem

# Run specific checks
python bootstrap.py validate \
  --host 10.0.0.1 \
  --key ~/.ssh/ADE-dev-key.pem \
  --check docker \
  --check python
```

#### Execute Remote Commands

```bash
# Start ADEPT services
python bootstrap.py remote \
  --host 10.0.0.1 \
  --key ~/.ssh/ADE-dev-key.pem \
  "cd /data/workspace/adept && make start"

# Check Docker containers
python bootstrap.py remote \
  --host 10.0.0.1 \
  --key ~/.ssh/ADE-dev-key.pem \
  "docker ps"
```

### Bash Script

#### Initialize Environment

```bash
# Basic initialization
./bootstrap.sh init \
  -h 10.0.0.1 \
  -k ~/.ssh/ADE-dev-key.pem \
  -r https://github.com/pnnl/adept-agentic.git \
  -t ghp_xxxxxxxxxxxx

# With Conda
./bootstrap.sh init \
  -h 10.0.0.1 \
  -k ~/.ssh/ADE-dev-key.pem \
  -r https://gitlab.com/team/adept.git \
  --use-conda \
  --conda-env myenv \
  -p 3.11

# Verbose mode
./bootstrap.sh init \
  -h 10.0.0.1 \
  -k ~/.ssh/ADE-dev-key.pem \
  -r https://github.com/pnnl/adept-agentic.git \
  -t ghp_xxxxxxxxxxxx \
  -v
```

#### Validate Environment

```bash
# Full validation
./bootstrap.sh validate \
  -h 10.0.0.1 \
  -k ~/.ssh/ADE-dev-key.pem \
  -c all

# Specific check
./bootstrap.sh validate \
  -h 10.0.0.1 \
  -k ~/.ssh/ADE-dev-key.pem \
  -c services
```

#### Execute Remote Commands

```bash
# Run make command
./bootstrap.sh remote \
  -h 10.0.0.1 \
  -k ~/.ssh/ADE-dev-key.pem \
  "cd /data/workspace/adept && make validate"
```

## Team Configuration

Team-specific configurations are stored in `../configs/teams/`. See examples:

- `pnnl-emsl.yaml` - PNNL EMSL team configuration
- `example-team.yaml` - Template for new teams

### Using Team Configuration

```bash
# With Python CLI (team config support)
python bootstrap.py init \
  --host 10.0.0.1 \
  --key ~/.ssh/ADE-dev-key.pem \
  --config ../configs/teams/pnnl-emsl.yaml \
  --team pnnl-emsl
```

## Environment Variables

### Git Authentication

- **GitHub**: Use Personal Access Token (PAT)
  ```bash
  --token ghp_xxxxxxxxxxxx
  ```

- **GitLab**: Use OAuth2 token
  ```bash
  --token glpat-xxxxxxxxxxxx
  ```

### Python Environment

- **UV** (Default): Fast, modern Python package manager
  ```bash
  # Automatically uses uv.lock if present
  ```

- **Conda**: Scientific computing environment
  ```bash
  --use-conda --conda-env myenv
  ```

## Directory Structure

After successful initialization:

```
/data/workspace/
└── adept-extended/           # Your clone folder
    ├── .venv/               # UV virtual environment (if using UV)
    ├── .env                 # Environment configuration
    ├── .env.example         # Template file
    ├── Makefile            # ADEPT make targets
    ├── docker-compose.*.yaml
    └── src/                # ADEPT source code
```

## Validation Checks

The validation command checks:

- ✅ **SSH Connectivity**: Can connect to instance
- ✅ **Docker**: Docker daemon is running
- ✅ **Python**: Required Python versions installed
- ✅ **UV**: Package manager available
- ✅ **Conda**: Miniconda installed
- ✅ **ADEPT**: Repository cloned and Makefile present
- ✅ **Services**: ADEPT containers running

## Troubleshooting

### SSH Connection Failed
```bash
# Check SSH key permissions
chmod 400 ~/.ssh/your-key.pem

# Test SSH manually
ssh -i ~/.ssh/your-key.pem ubuntu@host-ip
```

### Git Clone Failed
```bash
# Verify token is valid
# GitHub: Settings → Developer settings → Personal access tokens
# GitLab: User Settings → Access Tokens

# Test clone manually
git clone https://TOKEN@github.com/org/repo.git
```

### Python Environment Issues
```bash
# On EC2, verify UV is installed
/home/ubuntu/.cargo/bin/uv --version

# Verify Conda is installed
/opt/miniconda3/bin/conda --version
```

### Docker Permission Denied
```bash
# Ensure ubuntu user is in docker group
# Log out and back in after bootstrap
```

## Module Implementation Status

⚠️ **Note**: Several Python modules are currently placeholders and need implementation:

### Modules Requiring Implementation
- `commands/remote.py` - Remote execution utilities
- `commands/validate.py` - Extended validation logic
- `lib/env_manager.py` - Environment file management
- `lib/git_manager.py` - Git operations abstraction
- `lib/ssh_executor.py` - SSH connection pooling

The main `bootstrap.py` CLI is fully functional, but these supporting modules need to be implemented for complete functionality.

## Development

### Running Tests
```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/

# With coverage
pytest --cov=bootstrap tests/
```

### Code Quality
```bash
# Format code
black bootstrap.py commands/ lib/

# Lint
ruff check .

# Type checking
mypy bootstrap.py
```

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'feat: Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is part of the ADEPT framework and follows the same license.

## Support

- **Slack**: #adept-support
- **Email**: adept-dev@pnnl.gov
- **Issues**: [GitHub Issues](https://github.com/pnnl/adept-agentic/issues)

## Roadmap

### Near Term
- [ ] Complete implementation of placeholder modules
- [ ] Add progress persistence for long operations
- [ ] Implement retry logic for network failures
- [ ] Add more team configurations

### Future
- [ ] Web UI for bootstrap operations
- [ ] Amazon SageMaker Studio support
- [ ] Kubernetes development environments
- [ ] Multi-cloud support (Azure, GCP)