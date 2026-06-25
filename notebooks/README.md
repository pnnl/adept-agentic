# ADEPT Ecosystem Jupyter Notebooks

Welcome to the ADEPT (Agentic Discovery and Exploration Platform for Tools) ecosystem interactive learning environment! These notebooks provide comprehensive tutorials and examples for end-users, developers, and operators.

## 📚 Learning Paths

### 🎯 [00-setup/](00-setup/) - Getting Started
Essential setup and authentication notebooks for all users:
- Environment verification and setup
- Authentication with Keycloak
- Basic connectivity tests

### 👤 [01-end-user/](01-end-user/) - End User Journey
For users who want to leverage the ADEPT ecosystem's capabilities:
- Chat with AI agents
- File operations (upload, process, download)
- Scientific workflows (bioinformatics, chemistry)
- Multi-agent collaboration
- Advanced use cases

### 💻 [02-developer/](02-developer/) - Developer Guide
For developers building on the ADEPT platform:
- SDK usage and best practices
- Building custom MCP tools
- Creating custom agents
- API integration patterns
- Testing strategies
- Framework extension

### 🔧 [03-operator/](03-operator/) - Operator Manual
For system administrators and DevOps engineers:
- Deployment strategies
- Monitoring and health checks
- Security configuration
- Scaling and optimization
- Troubleshooting guides
- Multi-stack management

## 🚀 Quick Start

1. **Start JupyterLab** (if not already running):
   ```bash
   make start  # Starts all services including JupyterLab
   ```

2. **Access JupyterLab**:
   - URL: http://localhost:8888
   - Token: Check logs with `docker logs jupyterlab`

3. **Begin with Setup**:
   - Start with `00-setup/00_environment_setup.ipynb`
   - Complete authentication in `00-setup/01_authentication.ipynb`

4. **Choose Your Path**:
   - **End Users**: Continue to `01-end-user/`
   - **Developers**: Proceed to `02-developer/`
   - **Operators**: Jump to `03-operator/`

## 📋 Prerequisites

- Docker and Docker Compose installed
- ADEPT ecosystem services running (`make start`)
- Python 3.11+ (for local execution)
- Modern web browser

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        NGINX Proxy                           │
│                    (TLS, Load Balancing)                     │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                    Agent Gateway (Tier 1)                    │
│              (Authentication, API Routing)                   │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│              Orchestration Service (Tier 2)                  │
│         (Agent Logic, State Management, LangGraph)           │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                  MCP Tool Servers (Tier 3)                   │
│     (Scientific Tools, Code Execution, HPC Pipelines)        │
└──────────────────────────────────────────────────────────────┘
```

## 🔑 Key Concepts

### Multi-Tier Session Management
- `session_id` - Basic conversation/thread session
- `mcp_session_id` - MCP tool execution session
- `multi_agent_session_id` - Multi-agent coordination
- `gateway_session_id` - Inter-gateway communication

### API Protocols
- **OpenAI API** - Compatible with OpenAI SDKs
- **Response API** - Simplified chat completions
- **Assistant API** - Stateful conversation management
- **MCP Protocol** - Model Context Protocol for tools
- **A2A Protocol** - Agent-to-Agent communication

### Security Model
- **Keycloak** - Identity and access management
- **JWT Tokens** - Stateless authentication
- **RBAC** - Role-based access control
- **TLS/SSL** - Encrypted communications

## 📝 Notebook Conventions

Each notebook follows these conventions:
- **Setup Cell**: Import statements and configuration
- **Authentication Cell**: Token management
- **Helper Functions**: Reusable utilities
- **Examples**: Interactive demonstrations
- **Exercises**: Hands-on practice
- **Cleanup**: Resource cleanup

## 🛠️ Troubleshooting

### Common Issues

1. **Connection Refused**
   - Ensure services are running: `docker ps`
   - Check service health: `make validate`

2. **Authentication Failed**
   - Verify Keycloak is running
   - Check credentials in `.env` files
   - Refresh tokens if expired

3. **Import Errors**
   - Install requirements: `pip install -r requirements.txt`
   - Ensure correct Python environment

## 📚 Additional Resources

- [CLAUDE.md](../CLAUDE.md) - Development guidelines
- [Makefile](../Makefile) - Available commands
- [Tests](../tests/e2e/) - End-to-end test examples
- [API Documentation](http://localhost:8081/docs) - Interactive API docs

## 🤝 Contributing

To add new notebooks:
1. Follow the existing structure and naming convention
2. Include comprehensive markdown documentation
3. Add error handling and cleanup cells
4. Test in both local and container environments
5. Update this README with descriptions

## 📄 License

Copyright (c) 2024 ADEPT Framework Team. All rights reserved.