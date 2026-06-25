# CLI Reference

The ADEPT CLI (`afk`) provides command-line access to the platform for session management, tool operations, file handling, and Agent-to-Agent (A2A) mesh administration.

## Installation

```bash
pip install agentic-framework-sdk
```

After installation, the `afk` command is available in your shell.

## Basic Usage

```bash
# Start an interactive chat session
afk chat

# Start chat with a named session for continuity
afk chat --session my-research

# Use a specific model
afk chat --model gpt-4o --session analysis
```

## Command Reference

| Command | Description |
|---------|-------------|
| `afk chat` | Start an interactive chat session with the agent |
| `afk tools` | Manage registered tools (list, register, delete) |
| `afk files` | Upload, list, and download files |
| `afk sessions` | List and load saved conversation sessions |
| `afk config` | View and modify CLI configuration |
| `afk a2a` | Agent-to-Agent mesh administration |

## Configuration

```bash
afk config show --verbose                # Show current configuration
afk config set gateway_url <url>         # Set a configuration value
afk config init                          # Initialize interactively
afk config doctor                        # Run health check
afk config bootstrap \
  --gateway-url https://your-adept-server.example.com/v1 \
  --keycloak-url https://your-adept-server.example.com/auth \
  --username alice
```

## Tool Management

```bash
# List all available tools
afk tools list --username alice --password secret

# Register a new MCP tool
afk tools register my-tool \
  --description "Custom analysis tool" \
  --protocol mcp \
  --url http://my-tool-server:8080 \
  --acl-groups scientists,admins

# Delete a registered tool
afk tools delete my-tool --yes
```

## File Operations

```bash
afk files upload ./data.csv --purpose assistants --description "Experiment results"
afk files list --limit 20
afk files download file-abc123 --output ./downloaded.csv
```

## Session Management

```bash
afk sessions list                    # List saved sessions
afk sessions load session-id-here    # Resume a previous session
```

## A2A Commands

The `afk a2a` command group manages the Agent-to-Agent gateway mesh for inter-deployment communication.

```bash
# Generate a service token for A2A operations
afk a2a generate-token --profile default

# Register a peer gateway
afk a2a register-peer production-gw https://peer-gateway.example.com/v1 \
  --description "Production Gateway" \
  --tags "production,us-west-2" \
  --registry-url http://gateway-registry:8086

# List all registered peer gateways
afk a2a list-peers --format table

# Test connectivity to a registered peer
afk a2a test-token <token> --gateway-url https://peer-gateway.example.com/v1
```

!!! info "Authentication"
    A2A operations authenticate via Keycloak client credentials. The CLI retrieves service tokens automatically using the configured profile credentials.
