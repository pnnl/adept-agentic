# Platform AI Engineer Onboarding Guide

## Welcome to ADEPT Extended Platform

This guide provides everything you need to get productive with the ADEPT Extended platform as a Platform AI Engineer. The platform implements a production-ready, secure three-tier architecture for AI agent orchestration with enterprise-grade authentication, observability, and scalability.

## Table of Contents
1. [Quick Start](#quick-start)
2. [Architecture Overview](#architecture-overview)
3. [Development Workflow](#development-workflow)
4. [Critical Commands Reference](#critical-commands-reference)
5. [Troubleshooting Guide](#troubleshooting-guide)
6. [Platform Status and Roadmap](#platform-status-and-roadmap)
7. [Best Practices](#best-practices)
8. [Session Lineage Isolation](#session-lineage-isolation)
9. [Compliance and Security Guidelines](#compliance-and-security-guidelines)
10. [Advanced Topics](#advanced-topics)
    - [Multi-Agent Orchestration](#multi-agent-orchestration)
    - [A2A Communication](#a2a-communication)
    - [Custom LLM Integration](#custom-llm-integration)
    - [Kubernetes Deployment](#kubernetes-deployment)
    - [Database Management](#database-management-and-schema)
11. [Getting Help](#getting-help)
12. [Testing and Validation](#testing-and-validation)
13. [Examples and Notebooks](#examples-and-notebooks)
14. [Quick Reference Card](#quick-reference-card)
15. [Related Documentation](#related-documentation)

---

## Quick Start

### Prerequisites
- Docker Desktop with Docker Compose v2
- 16GB+ RAM (32GB recommended)
- 50GB+ free disk space
- Access to OpenAI API or Azure OpenAI (for LLM features)
- Git and basic command line familiarity

### AWS EC2 Development Environment Caveat

**If you are developing on AWS EC2**, be aware of Docker Hub rate limiting issues:

**The Problem**:
- Docker Hub limits anonymous pulls to **100 per 6 hours per IP address**
- AWS EC2 instances often share public IPs across multiple users
- ADEPT requires 15+ base images from Docker Hub during build
- You may encounter `429 Too Many Requests` errors during builds

**The Solution** (Auto-Detected):
The `quick-start-adept-and-subsystems.sh` script automatically detects AWS EC2 environments and applies mitigation:
- Prompts for Docker Hub authentication (increases limit to 200 pulls/6h)
- Pre-caches critical images before build
- Uses automatic retry logic with exponential backoff
- Provides troubleshooting guidance if builds fail

**Quick Authentication** (Recommended for AWS):
```bash
# 1. Create Docker Hub account (free): https://hub.docker.com/signup
# 2. Generate access token: https://hub.docker.com/settings/security
# 3. Set environment variables:
export DOCKERHUB_USERNAME='your-username'
export DOCKERHUB_TOKEN='your-access-token'

# 4. Run authentication script (or let quickstart prompt you):
./scripts/aws-docker-hub-auth.sh
```

**Running Unattended/Background Builds** (nohup, screen, tmux):
```bash
# For unattended builds, authenticate BEFORE running the script
export DOCKERHUB_USERNAME='your-username'
export DOCKERHUB_TOKEN='your-access-token'
./scripts/aws-docker-hub-auth.sh

# Then run quickstart in background
nohup ./scripts/quick-start-adept-and-subsystems.sh > logs/quickstart.log 2>&1 &

# Or with screen/tmux (recommended for long-running builds)
screen -S adept-build
./scripts/quick-start-adept-and-subsystems.sh
# Press Ctrl+A, then D to detach
```

**How Non-Interactive Mode Works**:
- The script detects when stdin is unavailable (nohup, background jobs, CI/CD)
- Skips interactive prompts automatically
- Proceeds with warnings if not authenticated
- Applies all AWS optimizations (pre-caching, retry logic) automatically

**For comprehensive solutions including ECR pull-through cache and production strategies**, see:
- **[AWS Docker Hub Mitigation Guide](AWS_DOCKER_HUB_MITIGATION.md)**

**Non-AWS Developers**: You can safely ignore this section - the quickstart script works normally without AWS-specific optimizations.

---

### Initial Setup (30 minutes)

```bash
# 1. Clone the repository into its default or arbitrary folder
git clone <repository-url> adept-extended-2025-11-07
cd adept-extended-2025-11-07  # This is an example of an arbitrary clone folder

# 2. Copy environment template
cp .env.example .env
# Edit .env with your API keys and configuration

# 3. Complete system startup (25-30 minutes)
./scripts/quick-start-adept-and-subsystems.sh

# Or manually:
make erase          # Clean slate (nuclear option)
make init-shared-docker-compose-network  # Create shared network (required!)
make init-shared-volume-permissions      # Initialize shared volumes (required!)
make build          # Build all images (10 min)
make langfuse-build # Build Langfuse images
make langfuse-start # Start observability stack (3 min)
make langfuse-init-complete # Initialize Langfuse credentials & org
make start          # Start core services (5 min)
make validate-service-health  # Verify everything works
```

### CLI Setup (Host Machine)

If you want to use the `agentic` CLI from your host machine (outside Docker), run the bootstrap command to auto-configure connectivity:

```bash
# One command: detects environment, discovers URLs, authenticates, saves config
agentic config bootstrap

# Verify it worked
agentic config doctor
agentic tools list
```

This solves the common DNS resolution error when the saved config points to `https://api.agentic.local` (only resolvable inside Docker). See **[CLI Bootstrap Guide](guides/CLI_BOOTSTRAP_GUIDE.md)** for details, environment variables, non-interactive mode, and troubleshooting.

### Access Points

**HTTPS Single Entry Point (Nginx Service Consolidation)**:
| Service | URL | Credentials | Notes |
|---------|-----|-------------|-------|
| **Nginx Proxy** | https://api.agentic.local | N/A | Single HTTPS entrypoint for all services |
| **Agent Gateway** | https://api.agentic.local/v1 | JWT token | Path-based routing via Nginx |
| **Keycloak** | https://api.agentic.local/auth | N/A | SSO authentication with dual path routing |
| **JupyterLab (SSO)** | https://api.agentic.local/jupyter | notebook-user / notebook-password | Keycloak SSO via OAuth2-Proxy |

**Legacy Direct Access Ports** (HTTP, for development/debugging):
| Service | URL | Credentials |
|---------|-----|-------------|
| **Streamlit UI** | http://localhost:8503 | notebook-user / notebook-password |
| **Keycloak Admin** | http://localhost:8180/admin | admin / admin |
| **Langfuse UI** | http://localhost:3001 | admin@adept.local / [auto-generated] |
| **JupyterLab (Direct)** | http://localhost:8888 | Token in logs |
| **OpenWebUI** | http://localhost:8902 | admin@example.com / changeme |

**Important**: The single HTTPS entry point (`https://api.agentic.local`) provides production-ready routing with TLS termination, OAuth2 authentication, and path-based service access. Legacy direct ports remain available for development debugging.

**Accessing via Custom IP or Hostname**: If you're deploying ADEPT on cloud VMs (AWS EC2, Azure) or accessing via custom hostnames/IP addresses (e.g., `https://<your-server-ip>/jupyter`), you need to register OAuth2 redirect URIs in Keycloak. See [Systems Administrator Onboarding - OAuth2 Configuration](SYSTEMS_ADMINISTRATOR_ONBOARDING.md#oauth2-configuration) for the complete setup guide and troubleshooting.

**TLS Certificate Trust for External Tools**: If connecting to ADEPT from a developer workstation (VS Code, Python, curl), each client needs to trust the self-signed certificate. See the [Client-Side Certificate Trust Guide](guides/CLIENT_CERTIFICATE_TRUST.md) for step-by-step instructions per platform and tool.

---

## Architecture Overview

### Three-Tier Security Architecture

```
+---------------------------------------------------------+
|                    User Interface Layer                  |
|  (Streamlit v2, JupyterLab, OpenWebUI, CLI, SDK)       |
+----------------------------+----------------------------+
                             | HTTPS
                             v
+---------------------------------------------------------+
|              Tier 1: Agent Gateway                       |
|  - Pure authentication proxy (no business logic)         |
|  - Keycloak JWT validation with RBAC                     |
|  - CORS handling, request routing                        |
|  - A2A (Agent-to-Agent) mesh communication              |
+----------------------------+----------------------------+
                             | Authenticated requests
                             v
+---------------------------------------------------------+
|           Tier 2: Orchestration Service                  |
|  - Core "brain" with OpenAI API compatibility           |
|  - ScientificWorkflowAgent with LangGraph               |
|  - Multi-agent orchestration                            |
|  - PostgreSQL state persistence                         |
|  - Dynamic tool management                              |
+----------------------------+----------------------------+
                             | Tool execution
                             v
+---------------------------------------------------------+
|            Tier 3: MCP Tool Servers                      |
|  - mcp_server: Scientific tools (BLAST, UniProt, RAG)   |
|  - hpc_mcp_server: HPC pipelines (Nextflow, GitXray)    |
|  - sandbox_mcp_server: Secure code execution            |
|  (All stateless - no persistent state)                  |
+---------------------------------------------------------+
```

### Key Components

#### Tier 1: Agent Gateway (`src/agentic_framework_pkg/agent_gateway/`)
- **Purpose**: Security boundary and authentication
- **No business logic** - pure proxy
- **Key files**: `app.py`, `auth.py`, `routers/v1/*`
- **Port**: 8081 (internal/container), 8083 (host), 443 (via NGINX)

#### Tier 2: Orchestration Service (`src/agentic_framework_pkg/orchestration_service/`)
- **Purpose**: Core AI agent logic and state management
- **OpenAI-compatible** API implementation
- **Key files**:
  - `scientific_workflow/langchain_agent.py` - Main agent
  - `persistence.py` - State management
  - `multi_agent_manager.py` - Multi-agent orchestration
- **Port**: 8084 (internal only)

#### Tier 3: MCP Tool Servers
- **mcp_server** (Port 8003): 18 scientific tools
- **hpc_mcp_server** (Port 8004): HPC and pipeline tools
- **sandbox_mcp_server** (Port 8005): Secure code execution
- **utility_mcp_tools**: Internal framework self-reflection tools
  - **QueryUserSessions**: Query session metadata and telemetry
  - **GetSessionHistory**: Retrieve full conversation history
  - **QueryLangfuseTelemetry**: Query observability traces
  - **GeneratePresignedURL**: Create time-limited file download URLs
- **CRITICAL**: All are stateless - orchestration owns all state

#### Storage Management (`src/agentic_framework_pkg/orchestration_service/routers/v1/storage_quota.py`)
- **Purpose**: Ephemeral file storage with context window optimization
- **Two-Tier Architecture**:
  - **Tier 1: Plots** - Persistent storage on shared volume (`/app/data/uploaded_files/plots/`)
  - **Tier 2: Ephemeral** - 7-day TTL storage (`/app/data/uploaded_files/ephemeral/{session_id}/`)
- **Features**:
  - Three-tier output routing (SMALL/MEDIUM/LARGE based on character count)
  - Streaming output buffer with mid-stream file redirection
  - Storage quota management (5GB hard limit, 4GB warning threshold)
  - 99.89% context window savings for large outputs
- **Port**: N/A (internal module)

### Supporting Services

#### Nginx Reverse Proxy (Service Consolidation)
- **Purpose**: Single HTTPS entry point for all services with path-based routing
- **Architecture**: TLS termination + OAuth2 authentication + backend proxying
- **Key Features**:
  - Self-signed certificates for development (auto-generated via mkcert)
  - Path-based routing with dynamic hostname preservation (`$http_host`)
  - OAuth2-Proxy integration for JupyterLab SSO (Keycloak PKCE authentication)
  - Dual path routing for Keycloak v2 compatibility (`/auth/*` and `/realms/*`)
  - SSH port forwarding support with explicit redirect URI configuration
- **Port**: 443 (HTTPS), 80 (HTTP redirect)
- **Domain**: `api.agentic.local` (hosts file entry)
- **Status**: Production-Ready - Port forwarding OAuth2 fix implemented

##### Access Patterns

**1. External FQDN Access (Production)**:
```bash
# Via FQDN (requires hosts file entry)
echo "127.0.0.1 api.agentic.local" | sudo tee -a /etc/hosts

# Access services
https://api.agentic.local/jupyter        # JupyterLab (OAuth2 SSO)
https://api.agentic.local/streamlit      # Streamlit UI
https://api.agentic.local/openwebui      # OpenWebUI
https://api.agentic.local/mgmt-ui        # Management UI
https://api.agentic.local/v1             # Agent Gateway API
```

**2. SSH Port Forwarding (Remote Development)**:
```bash
# Forward local port 8443 to remote server's HTTPS port 443
ssh -L 8443:localhost:443 user@remote-server

# Access via forwarded port (OAuth2 redirect URIs pre-configured)
https://localhost:8443/jupyter           # JupyterLab (OAuth2 works!)
https://localhost:8443/streamlit         # Streamlit UI
https://localhost:8443/openwebui         # OpenWebUI
https://localhost:8443/mgmt-ui          # Management UI
https://localhost:8443/v1                # Agent Gateway API

# Common alternative ports also supported:
# - https://localhost:8080 (alternative HTTPS port)
# - https://localhost:8000 (development servers)
# - https://localhost:443 (direct HTTPS)
```

**3. Custom Port Forwarding (Advanced)**:
```bash
# Add custom ports to .env (requires credential regeneration)
echo "CUSTOM_OAUTH_PORTS=9443,9090" >> .env

# Regenerate Keycloak configuration
make fix-credentials

# Access via custom port
ssh -L 9443:localhost:443 user@remote-server
https://localhost:9443/jupyter
```

##### OAuth2 Redirect URI Configuration

**Critical Implementation Detail**: Keycloak 26.3.2 does NOT support port wildcards (`:*`) in redirect URIs. Invalid patterns like `https://localhost:*/oauth2/callback` are silently ignored.

**Solution**: Bootstrap script (`scripts/deps/bootstrap_keycloak.py`) uses explicit port lists:
- **Default Ports**: 8443, 8080, 8000, 443, 80 (covers 95% of SSH tunnel use cases)
- **Dynamic Ports**: `CUSTOM_OAUTH_PORTS` environment variable for additional ports
- **NGINX Integration**: All locations use `$http_host` for host header preservation
- **OAuth2-Proxy**: Dynamically constructs `redirect_uri` from `Host` header

**Service-Port Mappings** (via NGINX reverse proxy):
- **JupyterLab**: `/jupyter/` -> oauth2_proxy:4180 -> jupyterlab:8888 (OAuth2-Proxy)
- **Streamlit**: `/streamlit/` -> streamlit_app:8503 (direct proxy)
- **OpenWebUI**: `/openwebui/` -> openwebui:8902 (direct proxy)
- **Management UI**: `/mgmt-ui/` -> agent_gateway_mgmt_ui:8502 (direct proxy)
- **Agent Gateway**: `/v1/`, `/a2a/` -> agent_gateway:8081 (direct proxy)

##### Managing Redirect URIs Dynamically

**Use Case**: Add/remove redirect URIs for new IP addresses or hostnames without restarting services.

**Python Implementation (Recommended)**:
```bash
# List all redirect URIs
docker exec orchestration_service python3 /app/scripts/nginx_proxy/manage_redirect_uris.py list

# Add redirect URI for new IP/hostname
docker exec orchestration_service python3 /app/scripts/nginx_proxy/manage_redirect_uris.py add <your-server-ip>

# Remove old/test redirect URI
docker exec orchestration_service python3 /app/scripts/nginx_proxy/manage_redirect_uris.py remove test.example.com
```

**Bash Implementation (Quick Add)**:
```bash
# Add redirect URI only
./scripts/nginx_proxy/register_jupyterlab_oauth_redirect_uri.sh <your-server-ip>
```

**Features** (v2):
- **Zero downtime**: No service restarts (hot-reload via Admin API)
- **Idempotent**: Safe to run multiple times (checks for existing URIs)
- **Instant**: Changes take effect in ~3-5 seconds
- **Remove support**: Python implementation includes removal capability
- **Proper authentication**: Uses KC_ADMIN_CLI_SECRET

**See**: `docs/guides/OAUTH2_REDIRECT_URI_MANAGEMENT.md` for detailed usage and troubleshooting.

##### OAuth2-Proxy vs Direct Proxy Pass-Through

**When OAuth2-Proxy is Used** (Browser-Based SSO Authentication):
- **JupyterLab** (`/jupyter/`): Interactive notebook environment requiring user authentication
  - Flow: NGINX -> OAuth2-Proxy -> Keycloak (authentication) -> JupyterLab
  - User Experience: Browser redirect to Keycloak login, OAuth2 authorization code flow with PKCE
  - Session Management: OAuth2-Proxy manages session cookies (`_oauth2_proxy` cookie)
  - Token Handling: OAuth2-Proxy validates tokens and proxies requests with user context

**When Direct Proxy Pass-Through is Used** (Service Authentication):
- **Agent Gateway** (`/v1/`, `/a2a/`): API endpoints using JWT bearer tokens
  - Flow: NGINX -> Agent Gateway (validates JWT directly)
  - Authentication: `Authorization: Bearer <jwt_token>` header
  - No browser redirects or session cookies

- **Streamlit, OpenWebUI, Management UI** (`/streamlit/`, `/openwebui/`, `/mgmt-ui/`):
  - Flow: NGINX -> Service (service handles own authentication)
  - Authentication: Service-specific mechanisms (API keys, session tokens, etc.)
  - No OAuth2-Proxy involvement

**Key Decision Factors**:
| Factor | OAuth2-Proxy | Direct Proxy |
|--------|--------------|--------------|
| **User Type** | Human users (browser) | API clients / services |
| **Auth Method** | OAuth2 / OIDC (Keycloak) | JWT bearer / API keys |
| **Session Type** | Browser cookies | Stateless tokens |
| **Redirect Flow** | Yes (to Keycloak) | No (API only) |
| **Use Cases** | Interactive UIs (JupyterLab) | Programmatic APIs |

**Configuration Locations**:
- **OAuth2-Proxy Config**: `deployment/local/docker-compose/docker-compose.core.yaml` (oauth2_proxy service)
- **NGINX OAuth2-Proxy Integration**: `infra/nginx/api.local.conf.template` (lines 396-437, `/jupyter/` location)
- **NGINX Direct Proxy**: `infra/nginx/api.local.conf.template` (lines 116-142 `/v1/`, lines 309-337 `/streamlit/`)
- **Keycloak Client Config**: `scripts/deps/bootstrap_keycloak.py` (jupyterlab-client with redirectUris)

**Adding OAuth2-Protected Services** (Future):
If you need to add a new service with OAuth2-Proxy authentication:
1. Add OAuth2-Proxy integration in NGINX config (similar to `/jupyter/` location)
2. Configure Keycloak client in `bootstrap_keycloak.py` with redirect URIs
3. Ensure NGINX uses `$http_host` for Host header preservation
4. Add explicit ports for SSH port forwarding support (8443, 8080, 8000, etc.)

##### References

**OAuth2 Port Forwarding & NGINX Proxy**:
- **OAuth2 Redirect URI Fix**: See implementation documentation
  - **Critical Finding**: Keycloak 26.3.2 does NOT support port wildcards (`:*`)
  - Official Keycloak source code analysis (RedirectUtils.java)
  - Explicit port list solution (8443, 8080, 8000, 443, 80) with `CUSTOM_OAUTH_PORTS` dynamic support
  - OAuth2-Proxy dynamic redirect_uri behavior
  - Service logs and error analysis

- **Authentication Flow**: `docs/implementation-reports/JUPYTERLAB_AUTHENTICATION_FLOW_WITH_PORT_FORWARDING.md`
  - Complete OAuth2 authorization code flow with PKCE
  - NGINX `$http_host` hostname preservation for port-forwarded access
  - OAuth2-Proxy reverse-proxy mode configuration
  - Keycloak dynamic hostname resolution via `X-Forwarded-Host`
  - Step-by-step flow diagrams for both FQDN and SSH tunnel access

**Keycloak Bootstrap & Security**:
- **Bootstrap Authentication Fix**: See implementation documentation
  - Admin-CLI secret auto-discovery from PostgreSQL database
  - Eliminated manual secret configuration requirement
  - `scripts/deps/discover_admin_cli_secret_internal.sh` implementation

- **Security Improvements**: See implementation documentation
  - **Critical Fix**: Eliminated hardcoded credentials in docker-compose.yaml
  - Environment-driven credential management (12-factor app compliance)
  - PostgreSQL password now sourced from `.env` (not hardcoded as "password")
  - OWASP Top 10 and CIS Docker Benchmark alignment

**OAuth2-Proxy Integration & Dependencies**:
- **OAuth2-Proxy Implementation**: `docs/implementation-reports/JUPYTERLAB_KEYCLOAK_SSO_VIA_OAUTH2_PROXY_IMPLEMENTATION_REPORT.md`
  - JupyterLab SSO integration via OAuth2-Proxy
  - PKCE (Proof Key for Code Exchange) security enhancement

- **Startup Dependency Fix**: `docs/implementation-plans/OAUTH2_PROXY_NGINX_STARTUP_DEPENDENCY_FIX.md`
  - Fixed OAuth2-Proxy/NGINX circular dependency
  - Health check-based startup ordering

#### Identity & Access Management (Keycloak)
- Central authentication with JWT tokens
- RBAC via groups: admin, gateway-service, notebook-users
- Client credentials for service-to-service auth
- Port: 8180 (direct), also accessible via `https://api.agentic.local/auth`

#### Gateway Registry
- Service discovery for A2A communication
- Health checking and failover
- PostgreSQL-backed persistence
- Port: 8086

#### Observability (Langfuse v3)
- Distributed tracing for agent execution
- Performance monitoring with ClickHouse
- Token usage and cost tracking
- Multi-agent session tracing (5/5 E2E tests passing)
- **Current Status**: **PARTIAL** - Checkpoint tracking fixed, authentication still pending
  - **Fixed**: Checkpoint tracking now uses correct `update_current_trace()` API (eliminated 47 ERROR messages)
  - **Fixed**: Multi-agent session tracing instrumentation complete
  - **Pending**: Self-hosted OTLP endpoint authentication failing (401 errors - Langfuse GitHub Issue #9628)
- **Workarounds Available**: Use Langfuse Cloud or disable with `OBSERVABILITY_BACKEND=none`
- **Setup**: `make langfuse-init-complete` (generates credentials + initializes org/project)
- **References**:
  - Checkpoint fixes: `docs/implementation-reports/OBSERVABILITY_CHECKPOINT_FIX_20260117.md`
  - Authentication issue: `docs/fixes/observability-langfuse-integration/LANGFUSE_V3_FINAL_STATUS.md`

### Federated Platform Integration

ADEPT integrates with external identity providers and DOE facility services via federated MCP server stacks. Key integration tracks:

- **Globus IdP**: OIDC federation with Keycloak for institutional login + 28 Globus API tools (Transfer, Search, Compute, Flows, Groups)
- **SPIFFE/SPIRE**: Zero-trust workload identity for Slurm HPC authentication (485 tests)
- **External MCP Stacks**: EMSL Sandbox, Slurm HPC, Biofoundation, VFM, Academy -- 29 registered tools

**References**:
- Federated Platform Integration Tracker: `docs/implementation-plans/FEDERATED_PLATFORM_INTEGRATION_TRACKER.md`
- Globus IdP Integration Plan: `docs/implementation-plans/GLOBUS_IDP_INTEGRATION_PLAN.md`
- RC Deployment Tracker: `examples/docs/SESSION_TRACKER_RC_FAMOUS_INTEGRATION.md`

### Docker Network Architecture

**CRITICAL**: The platform uses a four-tier Docker network architecture for security isolation and service segmentation.

#### Network Segmentation

| Network | Services | Purpose |
|---------|----------|---------|
| `adept_frontend_network` | nginx_proxy, OAuth2 proxy, Management UI, Streamlit | User-facing services (external access) |
| `adept_application_network` | agent_gateway, orchestration_service, Keycloak, MCP servers, registry | Business logic tier (service-to-service) |
| `adept_data_network` | PostgreSQL, Redis | Data persistence tier (database access) |
| `adept_integration_network` | Langfuse, RAGFlow, 3rd-party integrations | External services integration |
| `agentic_framework_network` | **[DEPRECATED - EMPTY]** | Legacy network (do not use) |

#### Network Creation

Networks are created automatically by `scripts/init-shared-network.sh` during Phase 2 (Infrastructure) of the startup sequence:

```bash
# Networks created in order
1. agentic_framework_network (legacy, deprecated)
2. adept_frontend_network (user-facing)
3. adept_application_network (business logic)
4. adept_data_network (persistence)
5. adept_integration_network (3rd-party services)
```

#### Test Container Network Access

**IMPORTANT**: Validation test containers must use the dual-network pattern to access both internal services and nginx_proxy:

```bash
# Correct pattern (used by DOCKER_RUN_VALIDATE_BASE)
docker run --rm \
  --network=adept_application_network \
  --network=adept_frontend_network \
  -v "$(pwd)/src":/app/src:ro \
  agentic-framework-deps-base \
  /app/.venv/bin/pytest tests/e2e/test_example.py -v
```

**Why Dual Networks?**
- `adept_application_network`: Access internal services (Keycloak, agent_gateway, orchestration_service)
- `adept_frontend_network`: Access nginx_proxy as external clients (via api.agentic.local)
- Docker DNS automatically resolves `api.agentic.local` to nginx_proxy (no manual DNS configuration)

#### Access Patterns

| Client Type | Network | URL Pattern | Use Case |
|-------------|---------|-------------|----------|
| External (SDK, browser, curl) | Host -> nginx_proxy | `https://api.agentic.local/v1/...` | Production, external integrations |
| Test containers | Dual network | `http://agent_gateway:8081/v1/...` or `https://api.agentic.local/v1/...` | E2E tests, validation |
| Local development | Host port | `http://localhost:8083/v1/...` | Quick iteration, debugging |
| Internal services | Application network | `http://agent_gateway:8081/v1/...` | Service-to-service communication |

#### Kubernetes Compatibility

**NOTE**: This network architecture is Docker Compose specific. For Kubernetes deployments:
- Networks are managed via NetworkPolicies and Service mesh
- `scripts/init-shared-network.sh` is not used
- See `docs/kubernetes/` or `infra/helm/` for K8s networking configuration

**References**:
- Network Script: `scripts/init-shared-network.sh`

### Tool Execution Factory Architecture

The platform implements a sophisticated tool execution factory pattern that intelligently routes tool calls between synchronous and asynchronous execution modes based on tool classification.

#### Two-Tier Tool Classification System

**Tier 1: Synchronous Tools** (8 tools - immediate execution)
- **Planning Tools** (4): CreateApprovedPlan, ExecuteApprovedPlan, UpdatePlanWithReasoning, CancelPlan
- **Task Management Tools** (2): CheckTaskStatus, CancelTask
- **RAG Management Tools** (2): ListKnowledgeBases, CreateKnowledgeBase

**Tier 2: Asynchronous Tools** (All others - background execution with task tracking)
- Scientific computation tools (BLAST, UniProt, PubChem)
- File processing tools (CSV RAG, document processing)
- HPC pipelines (Nextflow, video transcription, GitXray)
- Sandbox code execution
- External dynamically registered tools (HTTP, MCP, stdio protocols)

#### External Tool Protocols

External tools registered via `agentic tools register` or `POST /v1/tools/register` support three invocation protocols:

| Protocol | Factory | Transport | When to Use |
|----------|---------|-----------|-------------|
| `http` | `_create_http_tool()` | Raw HTTP POST `json=kwargs` | REST APIs, webhooks |
| `mcp` | `_create_mcp_tool()` | MCP JSON-RPC via `fastmcp.Client` | FastMCP/MCP servers (Streamable HTTP) |
| `stdio` | `_create_stdio_tool()` | Subprocess stdin/stdout | Local CLI tools |

**MCP protocol**: Uses FastMCP `Client` to perform the full MCP handshake (initialize -> tools/call) over Streamable HTTP. Required for any tool served by a FastMCP server (e.g., OpenTrons MCP Server). The `http` protocol sends raw JSON POST which FastMCP endpoints reject with 404.

**Key file**: `src/agentic_framework_pkg/orchestration_service/external_tool_manager.py`

**OpenTrons MCP Server Lifecycle** (Makefile automation):

```bash
# From project root
make opentrons-setup          # Build + start + register + verify
make opentrons-rebuild        # Rebuild (no-cache) + re-register tool
make opentrons-teardown       # Stop + deregister
make opentrons-health         # Health check
make opentrons-smoke-test     # E2E smoke test via Response API
```

**Key file**: `examples/opentrons_mcp_server/Makefile` (delegates via root Makefile `opentrons-*` targets)

#### Tool Execution Factory Components

**Key Files**:
- `src/agentic_framework_pkg/orchestration_service/tool_execution/tool_execution_factory.py` - Factory pattern implementation
- `src/agentic_framework_pkg/orchestration_service/tool_execution/async_task_manager_executor.py` - Async executor with PostgreSQL task tracking
- `src/agentic_framework_pkg/orchestration_service/tool_execution/task_management_tools.py` - CheckTaskStatus and CancelTask implementations

**Architecture Benefits**:
- **User Experience**: Instant feedback for planning/management operations, no waiting for task IDs
- **Resource Efficiency**: Long-running operations don't block agent execution
- **Task Monitoring**: All async operations tracked in PostgreSQL with real-time status updates
- **Override System**: Users can override default classification via environment variables

**Environment Configuration**:
```bash
# Override default tool classification (comma-separated list)
SYNCHRONOUS_TOOL_OVERRIDES="MyCustomTool,AnotherTool"
```

**Validation Tests**:
```bash
make validate-unit-task-management-tools    # 17 unit tests
make validate-e2e-task-management-tools     # 3 e2e tests (Response API)
```

### Gurobi Optimization in Sandbox Code

The sandbox subprocess runs with a restricted 5-variable environment. Container-level env vars like `GRB_LICENSE_FILE` are NOT inherited. All Gurobi code executed via `execute_code` must include a license search prefix before `import gurobipy`:

```python
import os as _os
_GUROBI_LICENSE_PATHS = [
    '/app/data/gurobi.lic',
    '/app/data/uploaded_files/gurobi.lic',
    '/opt/gurobi/gurobi.lic',
]
for _p in _GUROBI_LICENSE_PATHS:
    if _os.path.isfile(_p):
        _os.environ["GRB_LICENSE_FILE"] = _p
        break
```

The LLM agent generates this prefix automatically. For a complete coding agent prompt and workflow templates, see `examples/emsl_sandbox/docs/EMSL_GUROBI_WORKFLOW_GUIDE.md` Section 6.

Administrator setup (license file, token server DNS, exec user identity): see the "Gurobi Optimization Support" section in the Systems Administrator Onboarding guide.

### Task Management System

The task management system provides real-time monitoring and control of asynchronous tool executions.

#### CheckTaskStatus Tool

**Purpose**: Query status of background tasks without blocking agent execution

**Usage**:
```python
# Agent conversation
User: "Check the status of task a7b0a44f-9ae6-45dd-a0dc-afacfc41bfd6"
Agent: Calls CheckTaskStatus synchronously
Response: {
  "task_id": "a7b0a44f-9ae6-45dd-a0dc-afacfc41bfd6",
  "status": "running",
  "progress": "45%",
  "created_at": "2025-12-25T10:30:00Z"
}
```

**Key Features**:
- **Synchronous execution** - No nested task creation
- **Real-time status** - Queries PostgreSQL `async_tasks` table directly
- **Multiple status states**: pending, running, completed, failed, cancelled
- **Result retrieval** - Returns full output for completed tasks

#### CancelTask Tool

**Purpose**: Cancel long-running background tasks

**Usage**:
```python
# Agent conversation
User: "Cancel task a7b0a44f-9ae6-45dd-a0dc-afacfc41bfd6"
Agent: Calls CancelTask synchronously
Response: "Task a7b0a44f-9ae6-45dd-a0dc-afacfc41bfd6 has been cancelled successfully"
```

**Key Features**:
- **Synchronous execution** - Immediate cancellation confirmation
- **Terminal state validation** - Rejects cancellation of completed/failed tasks
- **Database atomicity** - Updates task status in single transaction
- **Session-aware** - Respects session isolation boundaries

#### Task Database Schema

Tasks are tracked in PostgreSQL table `async_tasks`:
```sql
CREATE TABLE async_tasks (
  task_id UUID PRIMARY KEY,
  tool_name VARCHAR(255),
  status VARCHAR(50),  -- pending, running, completed, failed, cancelled
  result TEXT,
  error TEXT,
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  session_id VARCHAR(255)  -- Session isolation
);
```

---

### Session Management and Context Window Management

Dual-layer retention system for conversation history: indefinite historical retention in PostgreSQL plus token-managed active context for LLMs.

**Architecture**:
- **Historical Retention Layer**: PostgreSQL-backed storage (4 tables: `user_sessions`, `session_messages`, `tool_outputs`, `context_archives`)
- **Active Context Layer**: Token-managed window with intelligent summarization and session forking
- **Session Lifecycle**: `active` -> `archived` -> `pending_deletion` -> `deleted`
- **Automated Cleanup**: Daily scheduler, configurable retention policies (`indefinite`, `30d`, `90d`, `1y`)

**Key Configuration** (`.env`):
```bash
SESSION_PERSISTENCE_ENABLED=true
SESSION_DEFAULT_RETENTION_POLICY=indefinite
SESSION_AUTO_ARCHIVE_THRESHOLD_DAYS=90
SESSION_DELETION_GRACE_PERIOD_DAYS=30
```

**Running Tests**:
```bash
make validate-phase1-unit-tests           # All session management tests (96 tests)
make validate-unit-retention-policy       # Retention policy tests
make validate-unit-cleanup-scheduler      # Cleanup scheduler tests
make validate-unit-session-models         # Session model tests
```

**Documentation**:
- Session Lifecycle: `docs/architecture/SESSION_LIFECYCLE.md`
- Migration Script: `src/agentic_framework_pkg/orchestration_service/persistence/migrations/001_create_session_tables.sql`

---

### Langfuse Observability Credentials

The platform uses Langfuse for comprehensive observability and tracing. Credentials are auto-generated during initialization.

#### Auto-Generated Credentials

##### 1. API Credentials (ADEPT -> Langfuse Communication)
These are automatically generated and stored in `.env` after running `make langfuse-init-complete`:

```bash
# Langfuse Observability Configuration (Auto-generated)
OBSERVABILITY_BACKEND=langfuse
LANGFUSE_PUBLIC_KEY=pk-lf-[32-char-hex-string]    # Example: pk-lf-fed353d12e44104a04eb2753443c250b
LANGFUSE_SECRET_KEY=sk-lf-[32-char-hex-string]    # Example: sk-lf-26b8778db50693a22d418b2a04b9bd99
LANGFUSE_HOST=http://langfuse-web:3001             # Internal Docker network URL
```

##### 2. Langfuse Web UI Access
Default admin user created during headless initialization:

| Field | Value | Notes |
|-------|-------|-------|
| **URL** | http://localhost:3001 | Browser access from host |
| **Email** | admin@adept.local | Default admin email |
| **Password** | admin_password | Change in production! |
| **Organization** | ADEPT | Auto-created organization |
| **Project** | ADEPT-Default | Default project for traces |

##### 3. Service Integration Points
All ADEPT services automatically use these credentials via environment variables:

- **Orchestration Service**: Traces agent execution, LLM calls, and tool usage
- **MCP Servers**: Instrument tool executions with performance metrics
- **Agent Gateway**: Request/response tracing with session context
- **SmartLogger**: Automatic log-to-trace conversion via `logger_config.py`

##### 4. Observability Features Enabled

| Feature | Implementation | Status |
|---------|---------------|--------|
| **SmartLogger** | Drop-in replacement for Python logging | Active |
| **@observe decorator** | Function-level tracing (Langfuse native) | Active |
| **@observable_tool** | MCP tool execution instrumentation | Active |
| **Session Context** | Multi-tier session ID propagation | Active |
| **Cost Tracking** | Token usage and LLM cost monitoring | Active |

##### 5. Credential Management Commands

```bash
# Check if credentials exist
make langfuse-check-credentials

# Bootstrap new credentials (if missing)
make langfuse-bootstrap

# Force regenerate credentials (careful!)
make langfuse-bootstrap-force

# Complete initialization (credentials + database)
make langfuse-init-complete
```

##### 6. Troubleshooting Observability

If traces aren't appearing in Langfuse:

1. **Verify credentials are loaded**:
   ```bash
   docker exec orchestration_service env | grep LANGFUSE
   ```

2. **Check Langfuse health**:
   ```bash
   make langfuse-health
   curl http://localhost:3001/api/public/health
   ```

3. **Restart services to reload credentials**:
   ```bash
   make restart
   ```

4. **View Langfuse logs**:
   ```bash
   docker logs langfuse-web --tail 50
   docker logs langfuse-worker --tail 50
   ```

### Keycloak Service Credential Bootstrapping

ADEPT uses Keycloak for authentication and automatically manages service client credentials through the `ServiceCredentialsManager`.

#### Auto-Generated Service Credentials

Service API keys follow the pattern: `sk-service-{service_name}-{32-char-random-string}`

**Managed Services**:
- **OpenWebUI**: `sk-service-openwebui-[random]`
- **n8n**: `sk-service-n8n-[random]`
- **Gateway Registry**: `sk-service-registry-[random]`

#### Credential Generation Process

1. **Initial Bootstrap** (during `make start`):
   - `ServiceCredentialsManager` registers service clients with Keycloak
   - Generates unique API keys for each service
   - Stores keys in service environment variables
   - Configures `SERVICE_API_KEYS_CONFIG` JSON structure

2. **Auto-Recovery** (if credentials become invalid):
   - Background validation runs every 5 minutes
   - Detects credential drift (e.g., after Keycloak restart)
   - Re-registers missing clients automatically
   - Rotates API keys as needed

3. **Key Rotation Behavior**:
   - Old keys are replaced with new keys during recovery
   - New keys are distributed to service containers
   - Orchestration service validates new credentials
   - **Important**: This is expected behavior, not a bug!

#### Credential Validation

```bash
# Check service credential health
make validate-credentials

# View current OpenWebUI credential
docker exec openwebui env | grep OPENWEBUI_SERVICE_API_KEY

# View orchestration service validation logs (every 5 minutes)
docker logs orchestration_service --since 10m | grep "credentials validated"
```

#### Credential Drift Troubleshooting

**Symptoms**:
- Service reports 401 authentication errors
- Old API key no longer working
- Orchestration service shows credential validation failures

**Solution**:
```bash
# Manual credential fix (if auto-recovery fails)
make fix-credentials

# Check Keycloak client list
docker exec keycloak /opt/keycloak/bin/kcadm.sh get clients \
  -r agentic-framework-realm \
  --server http://localhost:8180 \
  --user admin --password admin
```

#### Service API Key Configuration

Each service receives its credential via environment variables:

```bash
# OpenWebUI example
OPENWEBUI_SERVICE_API_KEY=sk-service-openwebui-khuPvegW1JLskGJVxF2ofPFgmjPeMYVy

SERVICE_API_KEYS_CONFIG={
  "sk-service-openwebui-khuPvegW1JLskGJVxF2ofPFgmjPeMYVy": {
    "client_id": "openwebui-client",
    "groups": ["gateway-agents"],
    "user_id": "service-openwebui",
    "username": "openwebui-service",
    "description": "OpenWebUI service API key for Agent Gateway access"
  }
}
```

#### Key Rotation vs User Authentication

**Two Separate Systems**:

1. **Service-to-Service Authentication** (Service API Keys):
   - Used by OpenWebUI/n8n to call Agent Gateway
   - Managed by `ServiceCredentialsManager`
   - Automatic key rotation is normal

2. **User Authentication** (JWT Tokens):
   - Used by end users to login to OpenWebUI/Streamlit
   - Managed by Keycloak SSO
   - Independent of service credentials

If users report "credential not working", determine which system:
- Service credential issue -> Check `SERVICE_API_KEYS_CONFIG`
- User authentication issue -> Check Keycloak user sessions

#### Related Files

- `src/agentic_framework_pkg/core/service_credentials_manager.py` - Auto-recovery logic
- `scripts/deps/service_health_manager.py` - Manual credential management CLI
- `tests/e2e/test_service_health_management.py` - Credential validation tests

---

## Development Workflow

### Daily Development Cycle

```bash
# Morning: Start and verify
make start && make validate-service-health

# During development: Service-specific rebuilds (faster than full rebuild)
make rebuild-orchestrator   # After changing orchestration code
make rebuild-mcp-servers    # After changing MCP tools
make rebuild-gateway        # After changing gateway

# End of day
make stop
```

See [Critical Commands Reference](#critical-commands-reference) for the full list of lifecycle and validation commands.

### LangGraph Integration Examples

#### Out-of-Box Functionality

LangGraph examples now work immediately after `make start` without SSL certificate setup.

**Default Configuration**:
```python
# examples/langgraph_adept_quickstart.py
AGENT_GATEWAY_URL = os.getenv("AGENT_GATEWAY_URL", "http://localhost:8083/v1")
```

**Access Pattern Recommendations**:
1. **Development (Default)**: `http://localhost:8083/v1`
   - No SSL certificate setup required
   - Works immediately after `make start`
   - Recommended for local development

2. **Production SSL**: `https://api.agentic.local/v1`
   - Requires SSL certificate trust configuration
   - Set: `export AGENT_GATEWAY_URL=https://api.agentic.local/v1`
   - Recommended for production deployments

3. **Internal HTTP (K8s)**: `http://agent_gateway:8081/v1`
   - Container-only access pattern
   - Used inside Docker/K8s networks
   - Recommended for service-to-service communication

#### SSL Certificate Setup (Production Only)

For production deployments requiring HTTPS:

```bash
# macOS: Trust self-signed certificate
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain \
  data/nginx_certs/api.agentic.local.crt

# Linux: Trust self-signed certificate
sudo cp data/nginx_certs/api.agentic.local.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates
```

#### Running Examples

```bash
# Quick validation (all tests)
cd examples && python scripts/validate-langgraph-examples.py

# Run individual examples
python examples/langgraph_adept_quickstart.py
python examples/langgraph_adept_integration.py
```

**Environment Variable Override**:
```bash
# Use external HTTPS (requires SSL trust)
export AGENT_GATEWAY_URL=https://api.agentic.local/v1
python examples/langgraph_adept_quickstart.py

# Use internal HTTP (container-only)
docker run --rm --network=adept_application_network \
  -v "$(pwd)/examples":/app/examples:ro \
  -e AGENT_GATEWAY_URL=http://agent_gateway:8081/v1 \
  agentic-framework-deps-base \
  python /app/examples/langgraph_adept_quickstart.py
```

**References**:
- Examples README: `examples/README.md`
- Validation Tests: 8 tests in `validate-langgraph-examples.py`

### Adding New Features

#### 1. Adding a New MCP Tool

```python
# 1. Create tool in appropriate server
# File: src/agentic_framework_pkg/mcp_server/tools/my_new_tool.py

from mcp import Tool
import mcp.types as types

@mcp.tool()
async def my_new_tool(
    query: str = types.string(description="Input query")
) -> str:
    """Description of what this tool does."""
    # Implementation here
    return f"Result for: {query}"

# 2. Register in server's main.py
# File: src/agentic_framework_pkg/mcp_server/main.py
# Add to TOOLS list: my_new_tool

# 3. Rebuild and restart
make rebuild-mcp-servers
```

#### 2. Sandbox ExecuteCode MCP Tool Configuration

The Sandbox ExecuteCode tool provides secure, isolated code execution for Python, JavaScript, and shell scripts.

##### Execution Modes

| Mode | Setting | Recommended | Notes |
|------|---------|-------------|-------|
| **Subprocess** | `EXECUTION_METHOD=subprocess` | Yes (default) | Stable, fast startup, works with async checkpointer |
| **Docker-in-Docker** | `EXECUTION_METHOD=docker-in-docker` | Short tasks only | Strongest isolation but checkpoint issues with sessions >60s |

##### Key Environment Variables (.env)

```bash
EXECUTION_METHOD=subprocess           # Recommended for stability
SUBPROCESS_MEMORY_LIMIT_GB=30         # Memory limit for subprocess mode
SANDBOX_DEFAULT_TIMEOUT=120           # Default execution timeout (seconds)
SANDBOX_MAX_TIMEOUT=1800              # Maximum allowed timeout (30 minutes)
SANDBOX_MEMORY_LIMIT=30g              # Docker container memory limit (DinD mode)
HOST_SHARED_UPLOADS_PATH=             # Absolute host path for DinD volume mounts (auto-detected if empty)
```

##### Usage Example

```python
result = await execute_code(
    code="""
import cobra.io.sbml
model = cobra.io.read_sbml_model('/app/data/uploaded_files/model.xml')
solution = model.optimize()
print(f'Objective value: {solution.objective_value}')
    """,
    language="python",
    execution_timeout=600,  # 10 minutes for complex models
)
```

Plots are saved to `/app/data/uploaded_files/plots/` and accessible via the agent gateway. Use `generate_plot=True` to enable plot capture.

##### Troubleshooting

- **MemoryError**: Increase `SUBPROCESS_MEMORY_LIMIT_GB` or `SANDBOX_MEMORY_LIMIT`
- **Docker Permission Denied**: `sudo chmod 666 /var/run/docker.sock` (or add user to docker group)
- **Timeout Issues**: Increase `execution_timeout` parameter or `SANDBOX_MAX_TIMEOUT` in `.env`
- **Rebuild after changes**: `make rebuild-sandbox`

##### EMSL Hybrid Cloud and Kubernetes Deployments

The EMSL sandbox extends this architecture to hybrid cloud (Podman on Rocky 9 VM) and Kubernetes (standalone Helm chart in `infra/helm/emsl-sandbox/`).

**Key differences from local sandbox**: Rootless Podman, VFS storage driver, subprocess-only execution, local CA TLS certificates.

**Documentation**:
- Operations guide: `examples/emsl_sandbox/docs/EMSL_DEPLOYMENT_OPERATIONS_GUIDE.md`
- K8s Helm chart: `infra/helm/emsl-sandbox/`

#### 3. Modifying the Main Agent

```python
# File: orchestration_service/scientific_workflow/langchain_agent.py

# Key areas to modify:
# - System prompt: Lines 260-330
# - Tool configuration: Lines 400-500
# - Agent initialization: Lines 600-700

# After changes:
make rebuild-orchestrator
```

#### 4. Adding API Endpoints

```python
# Tier 1: Add proxy endpoint
# File: agent_gateway/routers/v1/my_endpoint.py
@router.post("/my-endpoint")
async def proxy_my_endpoint(request: Request):
    return await proxy_request(request, "orchestration_service")

# Tier 2: Add business logic
# File: orchestration_service/routers/v1/my_endpoint.py
@router.post("/my-endpoint")
async def handle_my_endpoint(data: MyModel):
    # Actual implementation
    return {"result": "success"}
```

### Testing

For complete testing strategies, container patterns, and validation targets, see the [Testing and Validation](#testing-and-validation) section.

---

## Critical Commands Reference

### Lifecycle Management

```bash
# Primary commands
make start          # Start all services
make stop           # Stop services
make restart        # Restart services
make rebuild        # Full rebuild (no cache)
make teardown       # Remove containers, networks, volumes
make erase          # Nuclear option - removes everything

# Service-specific rebuilds (faster iteration)
make rebuild-gateway        # Tier 1
make rebuild-orchestrator   # Tier 2
make rebuild-mcp-servers           # All MCP servers
make rebuild-registry      # Gateway registry
make rebuild-streamlit-app-v2  # UI
```

### Validation & Health

```bash
# Health checks
make validate-service-health      # Overall health
make validate-credentials         # Check auth
make fix-credentials             # Fix auth drift
make validate-mcp-tools-discovery # Tool availability

# Testing
make validate                    # All E2E tests
make validate-unit-all          # All unit tests
make validate-response-api-tool-calls  # Critical API test
make validate-multi-agent       # Multi-agent features
```

### Context Management and Storage Validation

```bash
# Ephemeral storage system (16 tests)
make validate-ephemeral-storage-complete

# Post-task fork trigger (22 tests)
make validate-post-task-context-management-all

# Ephemeral storage (all components including quota)
make validate-ephemeral-storage-all

# Large output handling
make validate-large-output-handling-all
```

### Debugging & Logs

```bash
# View logs
docker logs orchestration_service -f --tail 100
docker logs agent_gateway -f --tail 100
docker logs mcp_server -f --tail 100

# Interactive debugging
docker exec -it orchestration_service bash
docker exec -it mcp_server bash

# Check service status
docker ps --format "table {{.Names}}\t{{.Status}}"
```

### Code Quality

```bash
# Format code (container-based for consistency)
docker run --rm -v "$(pwd)/src":/app/src -w /app \
  agentic-framework-deps-base /bin/bash -c \
  "pip install black && black /app/src/"

# Lint code
docker run --rm -v "$(pwd)/src":/app/src -w /app \
  agentic-framework-deps-base /bin/bash -c \
  "pip install ruff && ruff check /app/src/"
```

---

## Troubleshooting Guide

### Common Issues & Solutions

#### 1. Services Won't Start

```bash
# Check for port conflicts
lsof -i :8081  # Gateway
lsof -i :8180  # Keycloak
lsof -i :5432  # PostgreSQL

# Clean restart
make erase
make build
make start
```

#### 2. Authentication Failures

```bash
# Fix credential drift
make fix-credentials

# Verify Keycloak is healthy
curl http://localhost:8180/health

# Check JWT token
docker logs agent_gateway | grep "JWT"
```

#### 3. Tool Execution Failures

```bash
# Check MCP server health
docker logs mcp_server --tail 50

# Verify tool discovery
make validate-mcp-tools-discovery

# Test specific tool
docker exec -it mcp_server python -c "
from tools.my_tool import my_tool
import asyncio
asyncio.run(my_tool('test'))
"
```

#### 4. Context Overflow Issues (Resolved)

**Symptoms**:
- LLM requests fail with token limit errors
- Workflow interruption with "context too long" messages

**Solution (Automatic)**:
The platform now automatically handles context overflow with two complementary systems:

1. **Ephemeral Storage** (for large tool outputs):
   - Large outputs (>50k chars) automatically saved to ephemeral storage
   - Only file reference (URL) included in context (99.89% space savings)
   - Retrieve outputs via ReadFile, ListUploadedFiles, or GeneratePresignedURL tools

2. **Post-Task Fork Trigger** (for cumulative context growth):
   - Monitors context health AFTER every tool execution
   - Triggers session fork automatically at 80% token threshold (default: 120k/150k tokens)
   - User receives SSE notification with fork recommendation

**Configuration** (.env):
```bash
# Ephemeral storage (enabled by default)
ENABLE_EPHEMERAL_STORAGE=true

# Post-task fork trigger (enabled by default)
POST_TASK_FORK_ENABLED=true
POST_TASK_FORK_THRESHOLD_PERCENT=0.8  # Fork at 80% of max_tokens
POST_TASK_FORK_SAFETY_MARGIN=10000    # Safety margin in tokens

# Context management (enabled by default)
ENABLE_CONTEXT_MANAGEMENT=true
CONTEXT_MAX_TOKENS=150000              # Maximum tokens before fork
```

**Validation**:
```bash
make validate-ephemeral-storage-complete
make validate-post-task-context-management-all
```

**References**:
- `docs/implementation-reports/EPHEMERAL_STORAGE_TEST_RESULTS.md`
- `docs/CHANGELOG.md`

#### 5. File Upload/RAG Issues

**Symptom**: "Invalid or unknown file_id"

**Solution**: Session synchronization fix applied
- Files auto-process if not indexed
- Retry logic for file system delays
- Content-based file IDs for stability

### Debug Checklists

#### Service Won't Start Checklist
- [ ] Check Docker is running
- [ ] Verify networks exist: `docker network ls | grep adept`
- [ ] Check port availability
- [ ] Review .env configuration
- [ ] Check disk space: `df -h`
- [ ] Review service logs

#### Test Failure Checklist
- [ ] Using correct networks: `adept_application_network` + `adept_frontend_network` (dual-network pattern)
- [ ] Using internal service names (not localhost)
- [ ] Correct credentials (notebook-user/notebook-password)
- [ ] Services healthy: `make validate-service-health`
- [ ] No URL duplication (/v1/v1 issue)

### Bootstrap Flow and Credentials Architecture (Docker Compose Deployment)

For detailed information about the Docker Compose bootstrap process and credential symlink architecture:
- **CLAUDE.md -> Environment Configuration -> Credentials Management**
  - Two-location credential architecture for Docker Compose
  - `.env` and `.env-keycloak-credentials-dir` symlink management
  - Bootstrap flow phases (0a-4) during `quick-start-adept-and-subsystems.sh`
  - Credential sync workflows between compose directory and project root

**Quick Commands for Docker Compose Credentials**:
```bash
# Verify credential symlinks in docker-compose directory
ls -la deployment/local/docker-compose/.env*

# Fix broken symlinks (automatic in quick-start script)
./scripts/quick-start-adept-and-subsystems.sh

# Manually sync credentials from compose directory to project root
# (Required for validation tests that run from project root)
make sync-credentials
```

---

## Platform Status and Roadmap

### Recent Completions (February 2026)

#### Ephemeral Storage System
- **Status**: PRODUCTION READY (16/16 tests passing)
- **Description**: Comprehensive ephemeral file storage system eliminating context window pollution
- **Impact**: 99.89% context window savings, zero overflows for large tool outputs
- **Validation**: `make validate-ephemeral-storage-complete`
- **Key Features**:
  - Two-tier storage (plots + ephemeral)
  - Three-tier output routing (SMALL <5k, MEDIUM 5k-50k, LARGE >50k chars)
  - Streaming output buffer with SSE notifications
  - Storage quota management (5GB hard limit, automatic 7-day cleanup)

#### Tiktoken-Based Post-Task Fork Trigger
- **Status**: PRODUCTION READY (22/22 tests passing)
- **Description**: Accurate token counting with proactive session fork monitoring
- **Impact**: Eliminates context overflow by triggering forks at 80% token threshold
- **Validation**: `make validate-post-task-context-management-all`
- **Key Features**:
  - Accurate token counting with tiktoken (within 2% of actual API)
  - Post-task context health monitoring (AFTER tool execution, BEFORE adding to context)
  - Message hash caching (5-minute TTL for performance)
  - Fork threshold configuration via `POST_TASK_FORK_THRESHOLD_PERCENT` (default: 0.8)

#### Configuration Parity Fix
- **Status**: COMPLETE
- **Description**: Full synchronization between .env and .env.example files
- **Impact**: Improved developer discoverability, comprehensive configuration documentation
- **Changes**: 18 variables added to .env, 9 added to .env.example, 8 duplicates removed

---

For detailed information about the current state, recent changes, and future plans, please refer to the following documentation:

### [Known Issues and Current State](./KNOWN_ISSUES.md)

Comprehensive overview of the platform's operational status:
- **Working Features**: Fully operational production-ready features including Nginx Service Consolidation with JupyterLab SSO
- **Partial/In-Progress**: Features under development or validation
- **Known Issues**: Critical and non-critical issues with workarounds
- **Test Coverage Status**: E2E and unit test coverage metrics

### [Changelog](./CHANGELOG.md)

Chronological record of major changes organized by development session:
- Session-by-session implementation log
- Bug fixes and enhancements (including OAuth2-Proxy and Nginx startup dependency fix)
- Architecture improvements
- Test coverage improvements

### [Roadmap](./ROADMAP.md)

Planned enhancements and future work:
- **Completed Features**:
  - Session Management System (all 3 phases complete)
  - NGINX Service Consolidation + JupyterLab SSO with OAuth2-Proxy
  - SSH Port Forwarding OAuth2 Support
  - Keycloak Bootstrap Automation + Security Improvements
- **Near-Term Improvements**: Next 1-2 weeks (UI session management, external tool registration, SDK improvements)
- **Active Implementation Plans**:
  - Presigned URL implementation with X-Accel-Redirect (NGINX internal redirect)
  - See: NGINX Reverse Proxy section for OAuth2 & port forwarding architecture
- **Long-Term Future Work**: Phase 7+ initiatives

---

## Best Practices

### Development Guidelines

1. **State Management**
   - NEVER add state to MCP servers
   - All state belongs in orchestration service
   - Use PostgreSQL for persistence

2. **Authentication**
   - Always validate JWT tokens at gateway
   - Forward user context in headers
   - Use service accounts for internal calls

3. **Error Handling**
   ```python
   # Always use graceful degradation
   try:
       result = await risky_operation()
   except SpecificError as e:
       logger.warning(f"Operation failed: {e}")
       result = fallback_value
   ```

4. **Session Management**
   - Always propagate session IDs
   - Use multi-tier sessions correctly:
     - `session_id`: Conversation
     - `mcp_session_id`: Tool execution
     - `multi_agent_session_id`: Multi-agent

5. **Testing**
   - Always test in containers
   - Use Response API, not Assistant API
   - Mock external dependencies
   - Test session isolation

### Context Management Best Practices

Context overflow is handled automatically. See [Context Overflow Issues](#4-context-overflow-issues-resolved) in the Troubleshooting section for configuration details.

Key points:
- **Trust the automatic systems**: Ephemeral storage and post-task fork trigger handle overflow without manual intervention
- **Monitor storage quota**: `docker exec orchestration_service curl -s http://localhost:8084/v1/storage/quota | jq .`
- **Use file retrieval tools** for large outputs: `ReadFile`, `ListUploadedFiles`, `GeneratePresignedURL`
- **Configure fork threshold** via `POST_TASK_FORK_THRESHOLD_PERCENT` (default: 0.8)

### Code Organization

```
src/agentic_framework_pkg/
+-- agent_gateway/          # Tier 1: Auth proxy
|   +-- auth.py            # JWT validation
|   +-- routers/v1/        # Proxy endpoints
+-- orchestration_service/  # Tier 2: Core logic
|   +-- scientific_workflow/  # Main agent
|   +-- multi_agent/       # Multi-agent
|   +-- persistence.py     # State management
+-- mcp_server/            # Tier 3: Tools
|   +-- tools/            # Tool implementations
+-- core/                 # Shared utilities
    +-- llm_agnostic_layer.py  # LLM abstraction
    +-- observability/     # Monitoring (WIP)
```

### Performance Optimization

1. **Service Rebuilds**: Use specific targets, not `make rebuild`
2. **Caching**: Redis for tool configs, embeddings
3. **Async Everything**: Use async/await throughout
4. **Connection Pooling**: PostgreSQL, Redis connections
5. **Token Limits**: Configure per model capabilities

---

## Session Lineage Isolation

When the LLM context window fills, the system forks to a sub-session (context compaction). The orchestration layer manages two categories of session identity:

- **Stable identity** (`mcp_session_id`) -- visible to tools, file system, and Redis metadata. Never changes across forks.
- **Volatile identity** (`session_id` after fork resolution) -- used only for LangGraph checkpoint state management. Follows the fork chain.

### What This Means for AI Engineers

1. **Tools always receive the parent session ID** via `MCPToolWrapper` closure binding. The LLM cannot override the injected `mcp_session_id`.
2. **File paths are fork-agnostic** -- `./data/uploaded_files/sessions/{mcp_session_id}/` uses the stable parent ID.
3. **Multi-agent workers inherit the parent's stable `mcp_session_id`** -- file isolation is shared within a team.
4. **Fork chains are unbounded** -- conversations can be continued indefinitely. Cycle detection (not hop counting) protects against data corruption.
5. **`gateway_session_id` is explicit-only** -- never auto-generated, preventing accidental A2A delegation.

### Key Files

| File | Role |
|------|------|
| `context_compaction_fork_mapping.py` | `persist_fork_mapping()` + `resolve_fork()` with cycle detection |
| `responses.py:276-287` | `original_session_id` preservation for MCP tools |
| `session_hierarchy.py` | `SessionHierarchy` 4-tier data model |
| `mcp_langchain_tools.py:554-569` | `mcp_session_id` injection via closure binding |

**Architecture Reference**: `docs/architecture/SESSION_LINEAGE_ISOLATION_ARCHITECTURE.md`

---

## Compliance and Security Guidelines

### Overview
The ADEPT platform processes scientific data and integrates with third-party LLM providers. Understanding compliance requirements is essential for production deployments.

### Data Classification
**Tier 1: Public Data**
- Open-source scientific datasets (PDB, UniProt, PubChem)
- Published research papers and public APIs
- Example: BLAST query against public NCBI database

**Tier 2: Restricted Data**
- Unpublished research data
- Internal organizational datasets
- Example: Proprietary metabolic models

**Tier 3: Confidential Data** (NOT supported without additional controls)
- PHI, PII, HIPAA-regulated data
- Requires dedicated secure deployment

### LLM Provider Compliance Summary
| Provider | Data Retention | API Training | Compliance Certifications |
|----------|---------------|--------------|---------------------------|
| OpenAI API | 30 days | NO (API guarantee) | SOC 2, GDPR |
| Anthropic | Zero retention | NO | SOC 2, GDPR |
| Azure OpenAI | Customer-controlled | NO | HIPAA, FedRAMP, ISO 27001 |

**Key Principle**: NEVER send Tier 3 data to any LLM provider without explicit DPA and BAA agreements.

### Security Best Practices
- **Input Validation**: Sanitize all user inputs before LLM processing
- **Access Control**: Use Keycloak RBAC groups to enforce least privilege
- **Audit Logging**: Enable Langfuse observability for compliance audits
- **Secrets Management**: Never commit credentials to git repositories
- **Header Security**: X-Forwarded headers validated with allowlist

### X-Forwarded Header Security

**Purpose**: Context-aware URL generation with OWASP-compliant security controls

The platform implements a **Combined Defense approach** for X-Forwarded header handling:

1. **Header Overwrite**: Agent Gateway ALWAYS overwrites client-provided X-Forwarded-* headers (prevents injection attacks)
2. **Allowlist Validation**: Untrusted hosts are rejected and logged (prevents SSRF attacks)
3. **Fail-Safe Fallback**: Invalid hosts fall back to PUBLIC_BASE_URL (prevents service exposure)
4. **Audit Logging**: All security events logged with full context (enables monitoring)

**Configuration** (`.env`):
```bash
# Development configuration with internal Docker hostnames
AGENT_GATEWAY_ALLOWED_HOSTS=localhost,127.0.0.1,*.agentic.local,api.agentic.local,agent_gateway,orchestration_service
AGENT_GATEWAY_VALIDATE_FORWARDED_HOSTS=true
```

**CRITICAL**: The allowlist MUST include internal Docker service hostnames (`agent_gateway`, `orchestration_service`) to support intra-container communication from OpenWebUI, n8n, and other internal services.

**OWASP Coverage**:
- A01 (Broken Access Control) - SSRF prevention via allowlist
- A03 (Injection) - Header injection prevention via overwrite
- A05 (Security Misconfiguration) - Protocol downgrade prevention
- A10 (SSRF) - Internal network access prevention

**Security Features**:
- Header injection prevention (12 attack vectors tested)
- SSRF attack prevention (internal IP rejection)
- Protocol downgrade prevention
- Unicode homograph attack prevention
- Path traversal prevention
- Port scanning prevention

**Production Deployment**:
```bash
# Update .env with production domain (ALWAYS include internal Docker hostnames)
AGENT_GATEWAY_ALLOWED_HOSTS=localhost,*.yourdomain.com,api.yourdomain.com,agent_gateway,orchestration_service
PUBLIC_BASE_URL=https://api.yourdomain.com

# Rebuild services
make rebuild-gateway
make rebuild-orchestrator

# Test
make validate-presigned-url-context-awareness
```

**Documentation**:
- **Security Analysis**: `docs/security/X_FORWARDED_HEADERS_SECURITY_ANALYSIS.md`
- **Configuration Guide**: `docs/configuration/X_FORWARDED_HEADERS_CONFIGURATION_REFERENCE.md`
- **Flow Diagram**: `docs/configuration/X_FORWARDED_HEADERS_FLOW_DIAGRAM.md`

#### Internal Docker Hostname Requirement

**CRITICAL**: The allowlist MUST include internal Docker service hostnames for intra-container communication:

```bash
AGENT_GATEWAY_ALLOWED_HOSTS=localhost,127.0.0.1,*.agentic.local,api.agentic.local,agent_gateway,orchestration_service
```

**Why Required**:
- **OpenWebUI**: Calls agent gateway using `http://agent_gateway:8081/v1/*` for OpenAI-compatible API access
- **n8n**: Calls agent gateway for workflow automation
- **Internal Services**: All service-to-service communication uses Docker service names

**What Happens Without Internal Hostnames**:
```
ERROR: Host 'agent_gateway' rejected by allowlist
-> Falls back to PUBLIC_BASE_URL (https://api.agentic.local)
-> OpenWebUI sessions fail (cannot reach api.agentic.local from within Docker network)
-> Presigned URLs generated with wrong host
```

**Security Note**: Adding internal hostnames is SAFE because:
- Docker network isolation prevents external access
- Authentication (JWT/API keys) still required
- Hostnames only resolvable within Docker network
- HMAC signatures prevent URL tampering

**Test Coverage**: 30/30 unit tests passing (100%)

### Production Deployment Requirements
- [ ] Review and accept LLM provider terms of service
- [ ] Configure data classification policies in `.env`
- [ ] Enable audit logging (Langfuse or CloudWatch)
- [ ] Implement prompt sanitization for Tier 2+ data
- [ ] Document data processing workflows for compliance review

### Related Documentation
For comprehensive compliance documentation, including DPA templates, incident response procedures, and third-party risk assessments, see:
- **Full Compliance Guide**: `docs/COMPLIANCE_GUIDE.md` (coming soon)
- **Security Architecture**: `docs/SECURITY_ARCHITECTURE.md`
- **Known Security Issues**: `docs/KNOWN_ISSUES.md` (Sandbox privileges, nsjail configuration)

---
## Advanced Topics

### Auto-Compaction Strategy (Phase 3A + 3B)

**Session forking is the framework's auto-compaction implementation:**
- **Automatic**: Triggers when conversations exceed token limits
- **Non-destructive**: Preserves full history in parent session
- **Intelligent**: Creates bootstrap context from recent messages
- **Seamless**: Returns fork metadata for client session switching

**Implementation:**
- Phase 3A: Sub-session forking mechanism
- Phase 3B: Fork metadata propagation through Response API

**Key Achievement**: Token-aware session management with 18% improved accuracy through tool schema token estimation.

**Documentation:**
- Architecture: `docs/architecture/SESSION_FORKING_ARCHITECTURE.md`
- API Reference: `docs/api/RESPONSE_API_FORK_METADATA.md`
- Migration Guide: `docs/migration/PHASE3_MIGRATION_GUIDE.md`

### Agent Execution Architecture (LangChain / LangGraph)

Before working with ADEPT's agent system, understand the SDK foundations it builds on:

- **LangChain** provides components -- LLM wrappers, tool interfaces (`BaseTool`), message types, prompt templates. ADEPT uses these throughout.
- **LangGraph** provides the execution runtime -- `StateGraph` with nodes, edges, conditional routing, and checkpointed persistence. All ADEPT agents run as LangGraph graphs.
- **ReAct** (Reasoning + Acting) is the core loop pattern: Think -> Act -> Observe -> repeat. LangGraph's `create_react_agent` implements this as a two-node graph.

ADEPT's main agent extends ReAct with a custom three-node `StateGraph` that adds dual-criteria loop detection (args-aware, distinguishing true stuck loops from productive iteration), context window management, split-stream output handling, and a termination node with 4-tier fallback that can override the LLM's routing decisions. Multi-agent orchestration uses a hierarchical supervisor pattern with two modes: **Graph mode** (custom `StateGraph` with dynamic per-turn routing) and **Router mode** (`create_react_agent` hierarchy with plan-then-execute).

**Full architecture reference**: [`docs/architecture/LANGGRAPH_AGENT_EXECUTION_ARCHITECTURE.md`](architecture/LANGGRAPH_AGENT_EXECUTION_ARCHITECTURE.md)

### Multi-Agent Orchestration

The platform supports sophisticated multi-agent workflows including **cascading multi-agent teams** where Stage 2 teams introspect Stage 1 team execution for operations monitoring, debugging, and cost analysis.

#### Basic Multi-Agent Team Creation

```python
# Create specialized agent team
from agentic_framework_pkg.orchestration_service.multi_agent_manager import RolePersona

roles = [
    RolePersona(
        name="python_developer",
        llm_purpose="coding_agent",  # Uses AWS Bedrock Claude
        system_prompt_template="Expert {role} focusing on clean code. {base_instruction}"
    ),
    "data_scientist"  # Simple string for backward compatibility
]

# Agents get full toolset and coordinate through orchestration
```

#### Cascading Multi-Agent Workflows

Cascading workflows enable Stage 2 teams to analyze Stage 1 team execution using utility introspection tools:

```python
# Stage 1: Task Execution Team
stage1_roles = ["weather_researcher", "coding_agent", "librarian"]
stage1_result = await CreateMultiAgentSession(roles=stage1_roles, execution_mode="router")
stage1_session_id = stage1_result["multi_agent_session_id"]

# Stage 1 executes tasks...
# (produces checkpoints, telemetry traces, session metadata)

# Stage 2: Observability Team (introspects Stage 1)
stage2_roles = ["checkpoint_analyst", "session_analyst", "telemetry_analyst"]
stage2_result = await CreateMultiAgentSession(roles=stage2_roles, execution_mode="router")

# Stage 2 uses utility tools to analyze Stage 1
await QueryUserSessions(user_id=user_id, include_telemetry=True)
await GetSessionHistory(session_id=stage1_session_id)
await QueryLangfuseTelemetry(session_id=stage1_session_id)
```

**Use Cases**:
- **Operations Monitoring**: Ops teams monitor production agent execution in real-time
- **Debugging Analysis**: Debug teams analyze failed workflows using checkpoint history
- **Cost Analysis**: Finance teams review token usage and LLM costs across teams

**Key Features**:
- 72+ checkpoints validated across concurrent teams without collisions
- Full session isolation via multi-tier session IDs
- Cross-session correlation with PostgreSQL + Langfuse telemetry
- Production-ready with 258s E2E test validation

**Documentation**: See `docs/architecture/MULTI_TIER_SESSION_MANAGEMENT.md` for comprehensive architecture details.

### A2A Communication

#### Gateway Mesh Management

The ADEPT framework supports distributed gateway mesh topology with Agent-to-Agent (A2A) communication. Platform engineers can manage gateway peers using CLI commands.

**Prerequisites**:
```bash
export GATEWAY_REGISTRY_URL=http://localhost:8086
```

**A2A CLI Commands**:

```bash
# List registered peers (table format)
agentic a2a list-peers

# Register new peer gateway
agentic a2a register-peer lab-west https://lab-west.example.com/v1 \
  --description "West Coast Lab" \
  --tags "production,us-west-2"

# Update peer capabilities (merge tags)
agentic a2a update-peer lab-west --add-tags "Opentrons"

# Test peer connectivity
agentic a2a test-connection lab-west --verbose

# Remove peer
agentic a2a remove-peer lab-west --yes
```

**Complete Workflow Example**:
```bash
# 1. List existing peers
agentic a2a list-peers

# 2. Register new peer gateway
agentic a2a register-peer test-peer https://test.example.com/v1

# 2.5. Update peer capabilities
agentic a2a update-peer test-peer --add-tags "Opentrons"

# 3. Generate A2A token for peer
agentic a2a generate-token --groups gateway-service

# 4. Test connectivity
agentic a2a test-connection test-peer

# 5. Remove peer when done
agentic a2a remove-peer test-peer --yes
```

**Programmatic Gateway Registration** (Python SDK):

```python
# Register with gateway mesh
await gateway_registry.register(
    gateway_id="my-gateway",
    base_url="http://my-service:8081",
    capabilities=["llm", "tools"]
)

# Delegate to another gateway
result = await delegate_to_gateway(
    gateway_id="remote-gateway",
    request=agent_request
)
```

**References**:
- Implementation: `src/agentic_framework_sdk/cli/a2a_commands.py`
- Unit Tests: `tests/unit/agentic_framework_sdk/cli/test_a2a_commands.py` (22 tests)
- E2E Tests: `tests/e2e/test_a2a_cli_commands.py` (20 tests)

**Learning Resources**:

**[A2A Gateway Mesh Workshop](../examples/a2a-workshop/README.md)** - Hands-on 2-hour workshop covering:
- Federation protocol concepts and architecture
- Gateway mesh communication patterns
- Security testing with JWT tokens and service-to-service authentication
- Credential management with CLI tools
- Practical exercises and validation scripts
- Workshop materials include diagrams, exercises, and demo scripts

**IP-Based VM Federation Guides**:

For federating ADEPT instances across Azure/AWS VMs using only IP addresses:

- **[Quick-Start Checklist](../docs/guides/A2A_IP_BASED_VM_FEDERATION_QUICKSTART.md)** (15-20 min)
  - Self-signed certificate generation with OpenSSL and Subject Alternative Name
  - Credential management setup with auto-discovery
  - Mutual A2A peer registration workflow
  - Quick troubleshooting for common issues

- **[Complete Federation Guide](../docs/guides/A2A_IP_BASED_VM_FEDERATION_GUIDE.md)** (45-60 min)
  - Why self-signed certificates for IP addresses (Let's Encrypt limitations)
  - OpenSSL configuration with IP in SAN
  - Token/secret exchange patterns (spoiler: NO exchange needed!)
  - Comprehensive troubleshooting section
  - Production vs development security considerations

**Credential Management**:

The CLI now supports profile-based credential management for multi-environment workflows:

```bash
# Setup credentials with auto-discovery
agentic auth cred-setup --auto-discover --profile default --force

# Test credentials
agentic auth cred-test --profile default

# Use profile in A2A commands
agentic a2a list-peers --profile production
agentic a2a register-peer <alias> <url> --profile staging
```

**Key Features**:
- Three-tier credential discovery (profile -> ADEPT -> environment variables)
- Secure storage at `~/.adept-agentic/credentials` (chmod 600)
- Backward compatible with environment variables
- Multi-profile support (dev, staging, production)

**Documentation**:
- Implementation Plan: `docs/implementation-plans/CLI_CREDENTIAL_MANAGEMENT_IMPLEMENTATION_PLAN.md`

##### Peer JWKS Federation for Cross-VM Delegation

A2A delegation across VMs requires **dual JWT validation** on the receiving gateway:

1. **Service token** (`keycloak_context_builder.py:95-177`): Gateway-to-gateway auth -- already had peer JWKS federation
2. **User token** (`core/auth.py:347-378`): Forwarded user identity -- added peer JWKS federation

**Why it's needed**: Both VMs use `KEYCLOAK_URL=http://keycloak:8180` (Docker-internal). The token's `iss` claim matches the local Keycloak URL, so JWKS is fetched locally. But the signing kid belongs to the **peer** Keycloak.

**Implementation**: `validate_jwt_multi_stack()` now iterates `A2A_TRUSTED_PEER_JWKS_URLS` when kid not found in local JWKS:

```python
# core/auth.py -- peer JWKS fallback (lines 347-378)
if not rsa_key and A2A_TRUSTED_PEER_JWKS_URLS:
    for peer_jwks_url in A2A_TRUSTED_PEER_JWKS_URLS:
        peer_resp = await httpx.AsyncClient(verify=False).get(peer_jwks_url)
        for key in peer_resp.json().get("keys", []):
            if key["kid"] == token_kid:
                rsa_key = {k: key[k] for k in ("kty", "kid", "use", "n", "e")}
                break
```

**Code References**:
- User token validation: `src/agentic_framework_pkg/core/auth.py:266-378`
- Service token validation: `src/agentic_framework_pkg/agent_gateway/multi_agent/a2a/keycloak_context_builder.py:95-177`
- Unit tests: `tests/unit/.../core/test_auth.py::TestValidateJWTMultiStackPeerJWKS`

**Reference**: [`docs/bugfixes/A2A_CROSS_VM_USER_TOKEN_VALIDATION.md`](bugfixes/A2A_CROSS_VM_USER_TOKEN_VALIDATION.md)

### Custom LLM Integration

```python
# Add new LLM provider in llm_agnostic_layer.py
class MyLLMProvider:
    async def complete(self, messages, **kwargs):
        # Custom implementation
        return response

# Configure in .env
MY_LLM_API_KEY=xxx
MY_LLM_MODEL=my-model-name
```

### Kubernetes Deployment

```bash
# EMSL Sandbox (standalone 3-service stack -- stop-gap deployment)
cd infra/helm/emsl-sandbox
make helm-lint                  # Validate chart
make helm-template              # Dry-run render
helm install emsl-sandbox . --namespace class \
  --set secrets.sandboxFilesToken="$(openssl rand -hex 32)"

# Full ADEPT stack (Azure AKS)
cd infra/azure
pulumi up

# Helm installation (full stack)
helm install agentic-framework ./infra/helm/agentic-framework

# AWS EKS (planned)
cd infra/aws
cdk deploy
```

**Helm Charts Available**:

| Chart | Location | Purpose |
|-------|----------|---------|
| `emsl-sandbox` | `infra/helm/emsl-sandbox/` | Standalone sandbox (Redis + MCP + nginx) for EMSL K8s |
| `agentic-framework` | `infra/helm/agentic-framework/` | Full ADEPT stack (all tiers) |
| `adept-local` | `infra/helm/adept-local/` | Local development (k3d/minikube) |

### Database Management and Schema

The orchestration service uses PostgreSQL for state persistence with automatic schema initialization at startup via `init_db()` (SQLAlchemy `Base.metadata.create_all()`).

**Deployment Scenarios**:

| Scenario | Approach | Partitioning |
|----------|----------|-------------|
| Development / small production (<100K messages) | Automatic via `make start` | No (not needed) |
| Large production (>100K messages) | Manual SQL before first start | Yes (RANGE by `created_at`) |
| Existing deployment upgrade (pre-2026-01-20) | Run migration 007 or `make restart` | No (existing tables unchanged) |

**Key Schema Features** (Phase 2):
- Composite primary key `(id, created_at)` for partition support
- Full-text search via tsvector column with GIN index
- Tool call tracking via `tool_call_ids TEXT[]` array
- Optional monthly RANGE partitioning for scalability

**Quick Commands**:
```bash
# Development: No manual intervention required
make start

# Large-scale production: Run consolidated schema first
psql -h postgres -U admin -d agentic_orchestrator \
  -f src/agentic_framework_pkg/orchestration_service/persistence/migrations/consolidated_initial_schema.sql
make start

# Upgrade existing deployment
psql -h postgres -U admin -d agentic_orchestrator \
  -f src/agentic_framework_pkg/orchestration_service/persistence/migrations/007_update_session_messages_schema_phase2.sql
```

**Comprehensive Guide**: [docs/deployment/DATABASE_DEPLOYMENT_GUIDE.md](deployment/DATABASE_DEPLOYMENT_GUIDE.md) covers deployment scenarios, partitioning deep dive, performance benchmarks, partition maintenance, troubleshooting, and decision matrices.

**Key Files**:
- ORM Models: `src/agentic_framework_pkg/orchestration_service/models/session_models.py`
- Consolidated Schema: `src/.../persistence/migrations/consolidated_initial_schema.sql`
- Migration 007: `src/.../persistence/migrations/007_update_session_messages_schema_phase2.sql`

---

## Getting Help

### Resources
- **CLAUDE.md**: AI assistant instructions and patterns
- **IMPLEMENTATION_STATUS_CHECKPOINT.md**: Current sprint status
- **docs/**: Architecture and design documents
- **tests/e2e/**: Examples of API usage

### Common Workflows

#### "I need to debug a failing tool"
```bash
docker logs mcp_server --tail 100
docker exec -it mcp_server bash
cd /app/src/agentic_framework_pkg/mcp_server
python -c "from tools.my_tool import *; print(my_tool('test'))"
```

#### "I need to add a new API endpoint"
1. Add proxy in `agent_gateway/routers/v1/`
2. Add logic in `orchestration_service/routers/v1/`
3. Add tests in `tests/e2e/`
4. Rebuild: `make rebuild-gateway rebuild-orchestrator`

#### "Tests are failing with auth errors"
```bash
make fix-credentials
make validate-credentials
# If still failing, check Keycloak:
docker logs keycloak --tail 50
```

#### "I need to see what the agent is thinking"
```bash
# Enable debug logging
docker exec -it orchestration_service bash
export LOG_LEVEL=DEBUG
# Or check PostgreSQL for conversation state
```

---

## Quick Reference Card

### Must-Remember Items

| What | Command/Value |
|------|--------------|
| **First-Time/Clean Start** | `./scripts/quick-start-adept-and-subsystems.sh` |
| **Restart After Changes** | `make start` (assumes images exist) |
| **Default Password** | `notebook-password` |
| **Gateway URL (internal)** | `http://agent_gateway:8081/v1` |
| **Main UI** | http://localhost:8503 |
| **Fix Auth Issues** | `make fix-credentials` |
| **Disable Langfuse (Recommended)** | `OBSERVABILITY_BACKEND=none` in .env |
| **Langfuse UI** | http://localhost:3001 |
| **Clean Restart** | `make erase && make build && make start` |
| **Test in Container** | Always! Never local pytest |
| **Response API** | Use `client.responses.*` not `client.beta.*` |

**When to use each start command:**
- **First-Time/Clean Start**: Use `quick-start-adept-and-subsystems.sh` for initial setup, after `make erase`, or when credential/symlink issues occur. This script is idempotent and handles:
  - Pre-flight symlink validation (`.env`, `.env-keycloak-credentials-dir`)
  - Image builds (with AWS EC2 rate limit mitigation)
  - Langfuse observability setup
  - Keycloak credential generation
  - Complete service startup with health validation
- **Restart After Changes**: Use `make start` for quick restarts when images already exist and no infrastructure changes needed (rebuilds, credential regeneration, etc.)

### Architecture Rules
1. **Tier 1**: Auth only, no logic
2. **Tier 2**: All business logic and state
3. **Tier 3**: Stateless tools only
4. **Session IDs**: Always propagate all three types
5. **Testing**: Container network with internal names
6. **Sandbox**: Use subprocess mode (stable), avoid docker-in-docker for long runs
7. **Observability**: Currently disabled due to Langfuse 401 auth issues

---

## Testing and Validation

### Test Execution Commands

```bash
# Run all validation tests
make validate

# Service-specific validation
make validate-data                    # Data-plane authentication
make validate-mgmt                   # Management-plane operations
make validate-service-health         # Credential validation
make validate-streamlit-v2           # Streamlit v2 interface tests
make validate-response-api-tool-calls # Critical Response API test
make validate-multi-agent            # Multi-agent features
make validate-unit-all               # All unit tests

# Integration tests
make validate-session33-phase2-database  # Database integration tests
make validate-session33-phase2-auth      # Auth integration tests

# Task management tests
make validate-unit-task-management-tools  # 17 unit tests
make validate-e2e-task-management-tools   # 3 E2E tests

# Clean output (filter pip noise)
make validate-e2e 2>&1 | grep -v "Requirement already satisfied"
```

### Response API vs Assistants API

**Always use Response API** for all new tests and implementations:
```python
# Response API - Modern, stateless, OpenAI-compatible
import httpx

async with httpx.AsyncClient() as client:
    response = await client.post(
        "http://agent_gateway:8081/v1/responses/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "messages": [{"role": "user", "content": "Run a BLAST search..."}],
            "stream": False,
            "model": "agentic-framework:scientific-agent-v1"
        }
    )
    result = response.json()
    assistant_message = result["choices"][0]["message"]["content"]
```

Do NOT use the Assistants API (`client.beta.threads.*`, `client.beta.threads.runs.*`) for new work. It requires complex state management and polling loops.

### Network and Authentication Configuration for Tests

```python
# Correct test setup for container network
BASE_URL = "http://agent_gateway:8081/v1"  # Internal service name, includes /v1
KEYCLOAK_URL = "http://keycloak:8180"

# Authentication (user credentials)
client_id = "login-client"
username = "notebook-user"
password = "notebook-password"

# Token retrieval
async def get_user_token(username: str, password: str) -> str:
    response = requests.post(
        f"{KEYCLOAK_URL}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": client_id,
            "username": username,
            "password": password
        }
    )
    return response.json()["access_token"]
```

### Container Test Patterns

```bash
# Unit tests with ephemeral dependencies
docker run --rm --user $(id -u):$(id -g) \
  -v "$(pwd)/src":/app/src:ro \
  -v "$(pwd)/tests":/app/tests:ro \
  -w /tmp \
  agentic-framework-deps-base /bin/bash -c "
    python3 -m venv /tmp/test_venv && \
    /tmp/test_venv/bin/pip install -q pytest pytest-asyncio && \
    PYTHONPATH=/app/src:/app/tests /tmp/test_venv/bin/pytest /app/tests/unit/ -v && \
    rm -rf /tmp/test_venv
  "

# E2E tests with dual-network access
docker run --rm \
  --network=adept_application_network \
  --network=adept_frontend_network \
  -v "$(pwd)/tests":/app/tests:ro \
  -w /tmp \
  agentic-framework-deps-base /bin/bash -c "
    python3 -m venv /tmp/e2e_venv && \
    /tmp/e2e_venv/bin/pip install -q pytest pytest-asyncio httpx && \
    /tmp/e2e_venv/bin/pytest /app/tests/e2e/ -v && \
    rm -rf /tmp/e2e_venv
  "
```

### Testing Best Practices

**Key Principles**:
- Use container-based testing with read-only mounts (`:ro`)
- Use ephemeral `/tmp` storage for test dependencies
- Tests MUST use dual networks (`adept_application_network` + `adept_frontend_network`) for access to internal services and nginx_proxy
- Default test credentials: `notebook-user` / `notebook-password`
- Always sync credentials before tests: `make sync-credentials`

**Host vs Container Test Execution**:

| Execution Mode | When to Use | Prerequisites |
|----------------|-------------|---------------|
| Container (canonical) | CI/CD, validation gates, canonical evidence | Docker running, `agentic-framework-deps-base` image |
| Host (convenience) | Quick iteration, debugging, local development | `conda activate adept-session` (bootstrapped by Ansible `prepare-rocky-vm.yml`) |

Container-based targets (e.g., `make test-all-docker`, `make test-asopb`) are the canonical test execution method and include all required dependencies (`pytest-asyncio`, `transformers`, `detoxify`, etc.). Host-based targets (suffixed `-host`) require the `adept-session` conda environment which is provisioned during VM bootstrap via the Ansible playbook. See `docs/development/CODE_HYGIENE.md` Section 3.6 for full details.

**Test Classification Methodology**:

ADEPT uses strict test classification to ensure proper test organization and execution:

1. **Unit Tests** (`tests/unit/`):
   - Use `@patch` mocks for external dependencies (Streamlit, HTTP clients, databases)
   - Test functions/classes in isolation without real services
   - Fast execution (<1s per test)
   - Example: `test_get_user_token()` with mocked `requests.post`

2. **Integration Tests** (`tests/integration/`):
   - Test multi-component interactions with real databases
   - No HTTP mocks, but may use test fixtures
   - Medium execution time (5-30s per test)
   - Example: Session persistence with PostgreSQL

3. **E2E Tests** (`tests/e2e/`):
   - **CRITICAL: NO MOCKS ALLOWED** - Use real service integration
   - Test full request/response flows through all tiers
   - Requires running services (Keycloak, PostgreSQL, agent_gateway)
   - Slow execution (30s-5min per test)
   - Example: Keycloak authentication flow with real token validation

**Test Organization Example**:
```bash
# Unit test with mocks (CORRECT)
tests/unit/agentic_framework_pkg/streamlit_app_v2/test_chat_unit.py
# Uses @patch for requests.post, streamlit session_state

# E2E test without mocks (CORRECT)
tests/e2e/test_streamlit_app_v2.py
# Real Keycloak authentication, real database queries, no @patch
```

**Common Mistake**: Using `@patch` mocks in E2E tests
```python
# WRONG - E2E test should not use mocks
@patch('requests.post')  # E2E tests must use real HTTP calls
def test_keycloak_auth_e2e(mock_post):
    pass

# CORRECT - E2E test uses real services
def test_keycloak_auth_e2e():
    response = requests.post(f"{KEYCLOAK_URL}/realms/master/...")
    assert response.status_code == 200
```

**Detailed Testing Documentation**: See `docs/testing/` for comprehensive testing strategies, integration test infrastructure, test runbooks, and best practices.

### Makefile Validation Target Patterns

#### Correct Pattern: Use Pre-Installed Packages

**IMPORTANT**: All validation targets should use packages pre-installed in the `agentic-framework-deps-base` image. **NEVER** use `pip install` in validation targets that use `DOCKER_RUN_VALIDATE_BASE`.

**CORRECT Pattern**:
```makefile
validate-my-test:
	@$(DOCKER_RUN_VALIDATE_BASE) /app/.venv/bin/pytest tests/e2e/my_test.py -v
```

**INCORRECT Pattern** (DO NOT USE):
```makefile
validate-my-test:
	@$(DOCKER_RUN_VALIDATE_BASE) /bin/bash -c "\
		/app/.venv/bin/pip install -q pytest-asyncio httpx && \
		pytest tests/e2e/my_test.py -v"
```

**Why This Is Important**:
- `DOCKER_RUN_VALIDATE_BASE` runs as non-root user (`--user $(id -u):$(id -g)`)
- `/app/.venv` is inside the container image (read-only)
- User cannot modify the venv -> Permission denied errors
- Tests fail before they even run

#### Adding Missing Dependencies

If a test fails with `ModuleNotFoundError`:

**Step 1**: Add package to `infra/dockerfiles/Dockerfile.deps-base`
```dockerfile
RUN pip install --no-cache-dir \
    # Existing packages...
    new-package-name \
    && rm -rf /root/.cache/pip
```

**Step 2**: Rebuild base image
```bash
make rebuild  # Rebuilds all images including deps-base
```

**Step 3**: Re-run test
```bash
make validate-my-test
# Should now pass without pip install
```

#### Exception: Ephemeral venv Pattern

For tests requiring isolated dependencies or special dependency combinations:

```makefile
validate-my-test:
	@$(DOCKER_RUN_VALIDATE_BASE) /bin/bash -c "\
		python3 -m venv /tmp/my_venv && \
		/tmp/my_venv/bin/pip install -q special-package && \
		/tmp/my_venv/bin/pytest tests/unit/my_test.py && \
		rm -rf /tmp/my_venv"
```

**When to Use Ephemeral venv**:
- Unit tests requiring isolated dependencies
- Tests that install the SDK itself (`pip install -e /app`)
- Special dependency combinations not in deps-base

**Why This Works**:
- Creates new venv in writable `/tmp` directory
- User has full write access to `/tmp`
- Ephemeral venv deleted after test completes

#### Validation Target Architecture Principles

1. **Immutable Container venvs**: Container venv is read-only (security + reproducibility)
2. **Pre-installed Dependencies**: All test dependencies in agentic-framework-deps-base
3. **Fast Execution**: No pip install overhead (~0.5-5 seconds per test file)
4. **Reproducible**: Same deps every run (no version drift)

**References**:
- Docker Testing Reference: `docs/testing/DOCKER_TEST_EXECUTION_REFERENCE.md`

---

## Examples and Notebooks

### Code Examples (`examples/`)

The `examples/` directory contains production-ready code examples demonstrating ADEPT integration patterns. All examples work in **STANDALONE mode** without requiring ADEPT framework installation.

#### Installation

**Standalone Mode** (Recommended for external integrations):
```bash
# Install minimal dependencies
pip install -r examples/requirements.txt

# Or build Docker image
docker build -t adept-examples:standalone --target standalone examples/
```

**Full Mode** (Optional - for session tracking):
```bash
# Install full ADEPT framework
pip install -e .

# Or build Docker image with framework
docker build -t adept-examples:full --target full -f examples/Dockerfile .
```

#### Service Token Authentication

**File**: `examples/openai_client_service_token_example.py`

**Purpose**: Demonstrate OpenAI-compatible client usage with service API tokens (alternative to user JWT).

**Features**:
- **STANDALONE**: Works without ADEPT framework installation
- **Service Token Auth**: Long-lived bearer tokens (90 days default)
- **No Login UI**: Ideal for automation, CI/CD, external services
- **Session Tracking** (Optional): Gracefully degrades if ADEPT not available
- **Pattern Comparison**: Side-by-side with Streamlit Chat.py (user JWT)
- **Zero-Downtime**: Instant token creation/revocation via Redis

**Redis Enhancement**: Service tokens now stored in **Redis Database 1** for:
- **Instant synchronization** across services (no SIGHUP needed)
- **Zero-downtime operations** (no service restarts)
- **210x faster** token management (0.5ms vs 105ms)
- **0% failure rate** (eliminated 20% SIGHUP failures)

**Usage**:
```bash
# 1. Create service token (instant activation via Redis)
make create-service-token NAME=my-automation GROUPS=notebook-users TTL_DAYS=90

# 2. Set environment variable
export ADEPT_SERVICE_API_TOKEN="sk-service-..."

# 3. Run standalone example (token immediately usable)
python examples/openai_client_service_token_example.py
```

**Service Token vs User JWT**:

| Feature | Service Token | User JWT |
|---------|---------------|----------|
| Authentication | Bearer sk-service-* | Keycloak OAuth2 flow |
| Lifespan | 90 days (default) | 8 hours |
| Refresh | Not required | Required |
| Use Case | Automation, services | Interactive UI |
| Standalone | Yes | No |
| Storage | Redis DB 1 | Keycloak database |
| Performance | 0.01ms (cached) | OIDC flow overhead |

**When to Use**:
- External service integration (n8n, OpenWebUI, custom tools)
- CI/CD pipelines and automation scripts
- Long-running background processes
- Testing and validation without user authentication

**Key Functions**:
- `get_openai_client_with_service_token()` - STANDALONE (no ADEPT required)
- `create_adept_session()` - OPTIONAL (session tracking if ADEPT available)

#### LangGraph Integration Examples

**Purpose**: Show how to integrate ADEPT's OpenAI-compatible API into LangGraph applications using litellm.

**Files**:
1. **[langgraph_adept_quickstart.py](../examples/langgraph_adept_quickstart.py)** (~60 lines)
   - Minimal example for rapid prototyping
   - Simple authentication, API call, and single-agent workflow
   - Perfect for getting started quickly

2. **[langgraph_adept_integration.py](../examples/langgraph_adept_integration.py)** (500+ lines)
   - Production-ready multi-agent workflow
   - Three classes: `ADEPTAuthenticator`, `ADEPTSessionManager`, `ADEPTLiteLLMClient`
   - Multi-agent workflow: Researcher -> Data Analyst -> Visualizer
   - Token refresh support, error handling

3. **[README.md](../examples/README.md)**
   - Quick start guide
   - Troubleshooting common issues
   - Advanced usage patterns

**Key Features Demonstrated**:
- Keycloak JWT authentication
- Automatic session management (no manual session_id or user_id required)
- Langfuse telemetry (automatic tracing)
- Multi-agent LangGraph workflows
- Conditional routing between agents

**Usage**:
```bash
# Set credentials
export KEYCLOAK_USERNAME="notebook-user"
export KEYCLOAK_PASSWORD="your_password"

# Run quick start (minimal example)
python examples/langgraph_adept_quickstart.py

# Run full integration (production-ready)
python examples/langgraph_adept_integration.py
```

**Important**: ADEPT is NOT an LLM proxy - it implements its own model called `agentic-framework:scientific-agent-v1`. Always use this model name in litellm calls.

**Documentation**: See [LangGraph Integration Guide](../docs/integration/LANGGRAPH_ADEPT_INTEGRATION_GUIDE.md) for comprehensive documentation.

---

### Interactive Notebooks (`notebooks/`)

The `notebooks/` directory provides comprehensive Jupyter notebook tutorials organized by user role.

#### Learning Paths

**[00-setup/](../notebooks/00-setup/) - Getting Started** (Required for all users)
- Environment verification and setup
- Authentication with Keycloak
- Basic connectivity tests
- **Start here**: `00_environment_setup.ipynb` -> `01_authentication.ipynb`

**[01-end-user/](../notebooks/01-end-user/) - End User Journey**
For users leveraging ADEPT's capabilities:
- Chat with AI agents
- File operations (upload, process, download)
- Scientific workflows (bioinformatics, chemistry)
- Multi-agent collaboration
- Advanced use cases

**[02-developer/](../notebooks/02-developer/) - Developer Guide**
For developers building on ADEPT:
- SDK usage and best practices
- Building custom MCP tools
- Creating custom agents
- API integration patterns
- Testing strategies
- Framework extension

**[03-operator/](../notebooks/03-operator/) - Operator Manual**
For system administrators and DevOps:
- Deployment strategies
- Monitoring and health checks
- Security configuration
- Scaling and optimization
- Troubleshooting guides
- Multi-stack management

#### Quick Start with Notebooks

```bash
# 1. Start JupyterLab (if not already running)
make start

# 2. Access JupyterLab
open http://localhost:8888
# Token: Check logs with `docker logs jupyterlab`

# 3. Begin with setup notebooks
# Navigate to: 00-setup/00_environment_setup.ipynb

# 4. Choose your learning path
# - End Users: Continue to 01-end-user/
# - Developers: Proceed to 02-developer/
# - Operators: Jump to 03-operator/
```

#### Key Notebook Concepts

**Multi-Tier Session Management**:
- `session_id` - Basic conversation/thread session
- `mcp_session_id` - MCP tool execution session
- `multi_agent_session_id` - Multi-agent coordination
- `gateway_session_id` - Inter-gateway communication

**API Protocols Covered**:
- OpenAI API - Compatible with OpenAI SDKs
- Response API - Simplified chat completions
- Assistant API - Stateful conversation management
- MCP Protocol - Model Context Protocol for tools
- A2A Protocol - Agent-to-Agent communication

**Security Model**:
- Keycloak - Identity and access management
- JWT Tokens - Stateless authentication
- RBAC - Role-based access control
- TLS/SSL - Encrypted communications

#### Notebook Conventions

Each notebook follows these conventions:
- **Setup Cell**: Import statements and configuration
- **Authentication Cell**: Token management
- **Helper Functions**: Reusable utilities
- **Examples**: Interactive demonstrations
- **Exercises**: Hands-on practice
- **Cleanup**: Resource cleanup

**Documentation**: See [notebooks/README.md](../notebooks/README.md) for complete notebook documentation.

---

### Integration Documentation

**Comprehensive Guides**:
- **[LangGraph Integration Guide](../docs/integration/LANGGRAPH_ADEPT_INTEGRATION_GUIDE.md)**: Complete documentation for LangGraph integration
  - Authentication patterns
  - Session management (automatic)
  - Langfuse telemetry
  - Multi-agent workflows
  - Troubleshooting

---

## Related Documentation

### Security Documentation

For X-Forwarded header security (OWASP-compliant allowlist, SSRF prevention, header injection prevention), see the [X-Forwarded Header Security](#x-forwarded-header-security) section under Compliance and Security Guidelines.

Additional security documentation:
- **[ASOPB and Release Pipeline Tutorial](tutorials/DEVELOPER_ONBOARDING_ASOPB_AND_RELEASE.md)**: Security scanning, ASPI scoring, MCP server development with security best practices, and the release pipeline
- **[ASPI Scoring Reference](security/ASPI_SCORING_REFERENCE.md)**: Scan types, gate thresholds, domain weights, FP suppression stack
- **[CVE Triage Guide](guides/CVE_TRIAGE_GUIDE.md)**: Investigate, classify, and remediate CVE findings from scans
- **[Compensating Controls Guide](guides/COMPENSATING_CONTROLS_GUIDE.md)**: Suppress false positives with integrity-verified fingerprints
- **[Pre-Release Review Guide](../scripts/release/PRE_RELEASE_REVIEW_GUIDE.md)**: 5-phase release verification workflow
- **[Security Analysis](security/X_FORWARDED_HEADERS_SECURITY_ANALYSIS.md)**: OWASP Top 10 coverage and attack vector analysis
- **[Configuration Guide](configuration/X_FORWARDED_HEADERS_CONFIGURATION_REFERENCE.md)**: Complete configuration reference
- **[Flow Diagram](configuration/X_FORWARDED_HEADERS_FLOW_DIAGRAM.md)**: Environment variable propagation

### API Documentation

- **[OpenAPI 3.1.0 API Documentation](api/)**: Complete API reference for all endpoints
  - **[openapi.json](api/openapi.json)**: Public API specification (70+ endpoints)
    - Response API (recommended), Chat Completions, Assistants API (deprecated)
    - Threads, Messages, Runs, Run Steps
    - Models, Files, Embeddings
    - Knowledge Bases (RAGFlow/ChromaDB)
    - Tools, Gateways (A2A), User Keys, MCP Protocol
  - **[openapi-admin.json](api/openapi-admin.json)**: Admin API specification
    - Tool management (register, update, delete, ACL)
    - Session management (statistics, cleanup)
    - Internal service-to-service APIs
  - **[Usage Examples](api/examples/)**:
    - [Authentication Guide](api/examples/authentication.md) - Keycloak JWT, RBAC
    - [Response API Examples](api/examples/response-api.md) - Chat completions, streaming, tools
    - [Knowledge Base Operations](api/examples/knowledge-bases.md) - RAG workflows
  - **Tools**: [Validation Script](../scripts/generate-api-docs.sh) - Docker-based spec validation and HTML generation

### Operations & Deployment

- **[Systems Administrator Onboarding](SYSTEMS_ADMINISTRATOR_ONBOARDING.md)**: User management, credential rotation, Keycloak admin, OAuth2 configuration, service health, and troubleshooting
- **[ASOPB CI Configuration Reference](ci/ASOPB_CI_CONFIGURATION.md)**: GitHub Actions workflow triggers, job execution tiers, conditional ML scanning, GHCR authentication, and troubleshooting
- **[Client-Side Certificate Trust Guide](guides/CLIENT_CERTIFICATE_TRUST.md)**: Trust ADEPT's self-signed TLS cert on macOS/Linux/Windows for Node.js, Python, curl, and browsers
- **[Ansible Deployment Guide](../deployment/ansible/README.md)**: VM preparation, stack lifecycle, and multi-cloud deployment playbooks
- **[Domain SME Guide](DOMAIN_SME_VIBE_CODING_GUIDE.md)**: Interactive AI-powered development workflows for domain experts

### For Other Audiences

#### Data Scientists & Domain SMEs
- **[SkyPilot DevTools Onboarding](../devtools/skypilot/ONBOARDING.md)**: CDK + Ansible EC2 deployment for PNNL `adept_VPC` (~50-100 min end-to-end)
  - Two-step provisioning (CDK infrastructure + Ansible OS config after PNNL Nessus hooks)
  - Multi-context state isolation per AWS account/provider
  - Host-local `ec2-*` Makefile targets for SSH-based management (sync, exec, stats)
  - CloudWatch auto-stop for cost control
  - All EC2/CDK/Ansible targets live in `devtools/Makefile.internal`, conditionally included into the root Makefile via `-include` (skipped in public releases). Run `make help-internal` from the project root to list them.
- **[AWS VM Deployment Guide](../devtools/AWS_VM_DEPLOYMENT_GUIDE.md)**: Legacy CDK deployment for non-PNNL accounts (chatGEM, etc.)
- **[Domain SME Vibe Coding Guide](DOMAIN_SME_VIBE_CODING_GUIDE.md)**: Interactive AI-powered development workflows
  - Prerequisites link to AWS deployment guide
  - Natural language coding patterns
  - Metabolic modeling case studies

#### Training Materials
- **[ADEPT Onboarding Presentation](presentations/ADEPT_Onboarding_Extended_2025-11-08.md)**: Full 80-slide training deck
- **ADEPT_Onboarding_PPT_Outline.md**: Presentation outline for trainers
- **Onboarding_Recommendations.md**: Strategic recommendations for improving onboarding

### Platform Engineer vs End User

This guide is specifically for **Platform AI Engineers** who will:
- Develop and maintain the ADEPT platform locally with Docker
- Add new features and tools
- Debug system issues
- Optimize performance
- **Work from their local development machine** (not AWS)

For **end users** (data scientists, domain experts) who need AWS-deployed environments:
1. Start with **[SkyPilot DevTools Onboarding](../devtools/skypilot/ONBOARDING.md)** to provision EC2 infrastructure (PNNL accounts)
   - Or **[AWS VM Deployment Guide](../devtools/AWS_VM_DEPLOYMENT_GUIDE.md)** for non-PNNL accounts
2. Then proceed to **[Domain SME Vibe Coding Guide](DOMAIN_SME_VIBE_CODING_GUIDE.md)** for application usage
3. Refer to presentation materials for training and workshops

**Key Difference**:
- **Platform Engineers** (this guide): Local Docker development, no AWS required
- **Domain Scientists** (other guides): AWS EC2 deployment required for remote access and collaboration

**Document Version**: 1.6 (2026-03-30)
**Maintainer**: ADEPT Framework Team

---

## Conclusion

Welcome to the ADEPT Extended platform! This guide should get you productive quickly. Remember:
- Start with `make start` and explore the Streamlit UI
- Use Response API for all new development
- Keep tools stateless, state in orchestration
- Test in containers with proper network configuration
- **Use subprocess execution mode** for stable sandbox operations
- **Langfuse observability** is currently disabled due to authentication issues
- Check IMPLEMENTATION_STATUS_CHECKPOINT.md for latest updates

---
