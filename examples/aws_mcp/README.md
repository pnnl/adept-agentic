# AWS MCP Server Manager

A meta-MCP server that provides on-demand access to 62+ AWS MCP servers from the [AWS Labs MCP collection](https://github.com/awslabs/mcp). Instead of running all servers simultaneously, this manager hot-loads/unloads individual AWS MCP servers as stdio subprocesses, maintains an internal registry, routes tool calls, and brokers STS temporary credentials.

## Architecture

```
                         ┌──────────────────────────────────────────┐
                         │        ADEPT Agent / Orchestrator        │
                         └───────────────┬──────────────────────────┘
                                         │
                    aws_tool_call("s3_tables.create_table_bucket", {...})
                                         │
               ┌─────────────────────────┼─────────────────────────┐
               │  Same-host (HTTP)       │     Cross-host (HTTPS)  │
               │  Docker network         │     TLS via nginx       │
               │                         │                         │
               ▼                         ▼                         │
   http://aws_mcp_manager:8003    https://<host>:9831              │
               │                    │  (TLS termination)           │
               │                    ▼                              │
               │           ┌────────────────────┐                  │
               │           │  Nginx Proxy        │                  │
               │           │  ssl_certificate    │                  │
               │           │  /etc/nginx/ssl/    │                  │
               │           └─────────┬──────────┘                  │
               │                     │ proxy_pass                  │
               ▼                     ▼                             │
          ┌──────────────────────────────────────┐                 │
          │         Meta-Server (:8003)          │                 │
          │                                      │                 │
          │  ┌────────────┐  ┌────────────────┐  │                 │
          │  │ STS Broker  │  │ Server Registry│  │                 │
          │  │ AssumeRole  │  │ load/unload    │  │                 │
          │  │ + cache     │  │ + route        │  │                 │
          │  └──────┬─────┘  └───────┬────────┘  │                 │
          │         │                │            │                 │
          └─────────┼────────────────┼────────────┘                 │
                    │                │                              │
          ┌─────────┴────────────────┴──────────┐                  │
          │  IAM User (sts:AssumeRole only)     │                  │
          │  → STS temp creds (cached, 1h TTL)  │                  │
          └─────────┬───────────────────────────┘                  │
                    │                                              │
                    ▼  env: AWS_ACCESS_KEY_ID=ASIA...              │
          ┌──────────────────────────────┐                         │
          │  s3-tables-mcp-server (stdio)│                         │
          │  └── AWS S3 Tables API       │                         │
          └──────────────────────────────┘                         │
```

## Deployment Patterns

### Pattern 1: Same Host (Internal)

ADEPT and the AWS MCP Manager run on the same Docker host, sharing `adept_application_network`. The orchestration service reaches the meta-server directly via HTTP over the Docker bridge.

```bash
cp .env.example .env
# Edit .env with AWS credentials
make setup
```

### Pattern 2: Cross Host (External)

The AWS MCP Manager runs on a separate host (e.g., different EC2 instance, HPC node). Communication goes through the nginx reverse proxy with TLS termination.

```bash
# On the AWS MCP Manager host:
cp .env.example .env
# Edit .env with AWS credentials
AWS_MCP_HOST_IP=10.0.0.1 make generate-certs
make build && make start

# Copy CA cert to ADEPT host:
scp certs/ca.crt adept-host:examples/aws_mcp/certs/

# On the ADEPT host — register tools via HTTPS:
AWS_MCP_PROTO=https AWS_MCP_HOST=10.0.0.1 AWS_MCP_PORT=9831 \
  ./scripts/register-aws-tools.sh register
```

## Quick Start

```bash
# 1. Configure credentials
cp .env.example .env
# Edit .env with your IAM user credentials and role ARN

# 2. Full setup (build, start, register with ADEPT)
make setup

# 3. Verify
curl http://localhost:9830/health
make test-unit
```

## Meta-Tools

The manager exposes 6 MCP tools:

| Tool | Description |
|------|-------------|
| `load_aws_server` | Hot-load an AWS MCP server subprocess |
| `unload_aws_server` | Stop and remove a server subprocess |
| `list_available_servers` | Show catalog with load state |
| `server_status` | Detailed status of one server |
| `aws_tool_call` | Dispatch tool call to loaded server |
| `list_loaded_tools` | Aggregate tools from all loaded servers |

## STS Security Model

- IAM user credentials are held **privately** by the meta-server (never exposed to subprocesses)
- IAM user needs only `sts:AssumeRole` permission
- Subprocesses receive **time-limited STS temporary credentials** via environment variables
- Credentials are refreshed 5 minutes before expiry (transparent subprocess restart)
- Session names include server name for CloudTrail traceability

## TLS / Certificate Generation

Generate a self-signed CA and server certificate for the nginx proxy:

```bash
# Required: routable IP of this host
AWS_MCP_HOST_IP=10.0.0.1 make generate-certs

# Optional: extra SANs
AWS_MCP_HOST_IP=10.0.0.1 \
  AWS_MCP_EXTRA_DNS=aws-mcp.example.com \
  AWS_MCP_EXTRA_IPS=192.168.1.100 \
  make generate-certs
```

This creates:
- `certs/ca.crt` + `certs/ca.key` — Certificate Authority (5-year validity)
- `certs/aws_mcp.crt` + `certs/aws_mcp.key` — Server cert (1-year validity)

When certs are present, nginx automatically enables HTTPS on port 9831 (configurable via `AWS_MCP_PROXY_HTTPS_PORT`).

## Pre-installed Servers

8 commonly-used servers are pre-installed in the Docker image:
- s3-tables-mcp-server, dynamodb-mcp-server, cloudwatch-mcp-server
- ecs-mcp-server, lambda-tool-mcp-server, iam-mcp-server
- cost-explorer-mcp-server, bedrock-kb-retrieval-mcp-server

Other servers are installed on-demand via `scripts/install-aws-server.sh`.

## Development

```bash
make test-unit          # Unit tests (mocked AWS) — 45 tests
make test-tls           # TLS cert + HTTPS flow tests — 15+ tests
make test-integration   # Integration tests (requires running services)
make test-e2e           # End-to-end tests
make test-all           # All tests
```

## Full Reference

See [User Guide](../../docs/guides/AWS_MCP_SERVER_MANAGER_USER_GUIDE.md) for detailed usage, configuration, and troubleshooting.
