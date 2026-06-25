# Dependencies and Service Management Scripts

This directory contains essential scripts for managing dependencies, bootstrapping services, and maintaining system health.

## Service Bootstrap Scripts

### `bootstrap_keycloak.py`
Bootstraps Keycloak identity provider with required clients, groups, and service accounts.

**Usage:**
```bash
python scripts/deps/bootstrap_keycloak.py
```

**Features:**
- Creates service clients (agent-gateway, openwebui, n8n, etc.)
- Sets up RBAC groups and permissions
- Generates and stores client credentials
- Validates Keycloak configuration

### `add_keycloak_user.py` ⭐ **New**
Manages Keycloak user creation and updates with CLI interface.

**Usage:**
```bash
# Create user with notebook-users group
python scripts/deps/add_keycloak_user.py \
    --username alice \
    --password alice-password \
    --groups notebook-users \
    --email alice@example.com

# Create user with multiple groups
python scripts/deps/add_keycloak_user.py \
    --username bob \
    --password bob-password \
    --groups notebook-users,streamlit-users \
    --email bob@example.com

# Update existing user (add to admin group)
python scripts/deps/add_keycloak_user.py \
    --username alice \
    --groups notebook-users,admin \
    --update

# List available groups
python scripts/deps/add_keycloak_user.py --list-groups

# Dry-run mode (preview changes)
python scripts/deps/add_keycloak_user.py \
    --username test-user \
    --password test-pass \
    --groups notebook-users \
    --dry-run
```

**Features:**
- **User Creation:** Create new users with specified groups and credentials
- **User Updates:** Update existing user groups and passwords
- **Group Validation:** Verify groups exist before user creation
- **Email Verification:** Automatically verify user emails
- **Dry-Run Mode:** Preview changes without applying them
- **Password Validation:** Enforce minimum security requirements
- **Multiple Groups:** Assign users to multiple groups simultaneously

**Makefile Integration:**
```bash
# Convenient make target
make add-user USERNAME=alice PASSWORD=alice-password GROUPS=notebook-users

# With multiple groups
make add-user USERNAME=bob PASSWORD=bob-pass GROUPS=notebook-users,admin

# Update existing user
make add-user USERNAME=alice GROUPS=notebook-users,admin UPDATE=true
```

**When to Use:**
- Onboarding new scientists/engineers with notebook-users group
- Adding admin users with elevated permissions
- Creating test users for validation
- Updating user group memberships
- Managing multi-group access for users

### `create_service_api_token.py` ⭐ **New**
Creates service API tokens for bearer token authentication (alternative to user JWT tokens).

**Usage:**
```bash
# Create service token (90-day default)
python scripts/deps/create_service_api_token.py \
    --name my-automation-service \
    --groups notebook-users \
    --description "CI/CD pipeline automation"

# Create token with custom TTL (30 days)
python scripts/deps/create_service_api_token.py \
    --name short-lived-service \
    --groups gateway-agents \
    --ttl-days 30

# List all tokens
python scripts/deps/create_service_api_token.py --list

# Revoke token
python scripts/deps/create_service_api_token.py --revoke sk-service-my-automation-abc123
```

**Features:**
- **Service Token Generation:** Create long-lived bearer tokens (90 days default)
- **TTL Support:** Configurable expiration (1 hour to 1 year)
- **Group Assignment:** Assign service identity to Keycloak groups
- **Token Revocation:** Deactivate expired or compromised tokens
- **List Tokens:** View all active, expired, and revoked tokens
- **Metadata Tracking:** Track creation date, expiration, service name, groups

**Service Token vs User JWT:**
| Feature | Service Token | User JWT Token |
|---------|---------------|----------------|
| Authentication | Bearer sk-service-* | Keycloak OAuth2 flow |
| Lifespan | 90 days (default) | 8 hours (access token) |
| Refresh | Not required | Required (refresh_token) |
| Use Case | Services, automation | End-user interactive |
| Identity | Service username | Actual user (sub) |
| Complexity | Low (just API key) | High (OIDC flow) |

**Makefile Integration:**
```bash
# Create service token
make create-service-token NAME=my-service GROUPS=notebook-users TTL_DAYS=90

# List tokens
make list-service-tokens

# Revoke token
make revoke-service-token TOKEN=sk-service-...
```

**When to Use:**
- External services calling ADEPT API (n8n, OpenWebUI, custom integrations)
- CI/CD pipelines and automation scripts
- Long-running background processes
- Non-interactive API access
- Testing and validation runners
- Any scenario where user login UI is not feasible

**Example:**
See `examples/openai_client_service_token_example.py` for complete usage pattern mimicking Streamlit Chat.py but with service tokens.

### `wait_for_postgres.py`
Waits for PostgreSQL database to become available before starting dependent services.

**Usage:**
```bash
python scripts/deps/wait_for_postgres.py
```

## Service Health Management

### `service_health_manager.py` ⭐ **New**
Comprehensive service health management addressing credential drift and tool discovery validation.

**Key Features:**
- **Credential Validation:** Checks OpenWebUI, n8n, and registry service client auth
- **Automatic Credential Refresh:** Prevents auth failures from token expiration
- **MCP Tool Discovery:** Validates dynamic tool discovery from MCP servers
- **Health Monitoring:** Background validation loops and health checks
- **Auto-Recovery:** Attempts to fix credential and connectivity issues

**Usage:**
```bash
# Validate all service credentials
python scripts/deps/service_health_manager.py --validate-credentials

# Attempt to fix credential issues automatically
python scripts/deps/service_health_manager.py --fix-credentials

# Discover and validate MCP tools
python scripts/deps/service_health_manager.py --discover-tools

# Comprehensive health check with recommendations
python scripts/deps/service_health_manager.py --health-check

# Get results in JSON format
python scripts/deps/service_health_manager.py --health-check --json
```

**When to Use:**
- After Keycloak restarts (credential drift)
- When services report authentication failures
- Before production deployments (validation)
- For operational monitoring and troubleshooting
- When MCP servers are added/modified

## Database Management

### `migrate_checkpoint_versioning.py`
Handles LangGraph checkpoint schema migrations and versioning.

### `init-multiple-dbs.sh` and `init-multiple-dbs-enhanced.sh`
PostgreSQL database initialization scripts for multi-database setup.

## Kubernetes Deployment

Place Kubernetes client bundle files here for target cluster deployments.

## Dependencies

All scripts require:
- Python 3.11+
- Access to PostgreSQL, Redis, and Keycloak services
- Proper environment variables and credentials configured

## Integration with Docker Compose

These scripts are automatically invoked during:
- `make start` (bootstrap and wait scripts)
- Service container startup (dependency management)
- Health check endpoints (service monitoring)

## Troubleshooting

### Credential Issues
```bash
# Check credential status
python scripts/deps/service_health_manager.py --validate-credentials

# Fix automatically
python scripts/deps/service_health_manager.py --fix-credentials
```

### Service API Key 401 After Bootstrap (Session 87)

If services return 401 `"Invalid service API key"` after stack startup, the cause is a
**startup race condition**: `SERVICE_API_KEYS` is loaded at module import time, and the
bootstrap `*-setup` containers may regenerate credential files *after* workers have already
started. The running workers retain stale keys in memory.

**Quick fix** (no rebuild required):
```bash
# SIGHUP reload all workers — targets spawned multiprocessing workers, not just PID 1
make reload-service-tokens
```

**Full fix** (regenerate + reload):
```bash
# Regenerates credentials, force-recreates containers, then sends SIGHUP
make fix-credentials
```

`fix-credentials` automatically calls `reload-service-tokens` after `--force-recreate`.

**Details**: `docs/bugfixes/SESSION_87_SERVICE_API_KEY_STARTUP_RACE_CONDITION.md`

### Tool Discovery Issues
```bash
# Validate MCP tool availability
python scripts/deps/service_health_manager.py --discover-tools
```

### Overall System Health
```bash
# Comprehensive diagnostic
python scripts/deps/service_health_manager.py --health-check --json
```

### User Management Issues
```bash
# List available groups before creating user
python scripts/deps/add_keycloak_user.py --list-groups

# Preview user creation (dry-run)
python scripts/deps/add_keycloak_user.py \
    --username test-user \
    --password test-pass \
    --groups notebook-users \
    --dry-run

# Fix "user already exists" error
python scripts/deps/add_keycloak_user.py \
    --username alice \
    --groups notebook-users \
    --update

# Verify user authentication after creation
export KEYCLOAK_USERNAME=alice
export KEYCLOAK_PASSWORD=alice-password
python examples/scripts/validate-langgraph-examples.py
```