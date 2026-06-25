# A2A Gateway Mesh - Architecture Deep Dive

**Purpose**: Technical architecture documentation for A2A communication between independent ADEPT instances.

---

## Table of Contents

1. [Core Architectural Principles](#core-architectural-principles)
2. [Instance Independence](#instance-independence)
3. [A2A Protocol](#a2a-protocol)
4. [Authentication Flow](#authentication-flow)
5. [Gateway Registry](#gateway-registry)
6. [Network Topology](#network-topology)
7. [Security Model](#security-model)

---

## Core Architectural Principles

### Principle 1: Complete Independence

Each ADEPT instance is **completely autonomous and idempotent**:

```
ADEPT Instance = {
    PostgreSQL database (state),
    Redis cache (sessions),
    Keycloak realm (identity),
    Agent Gateway (auth proxy),
    Orchestration Service (brain),
    MCP Servers (tools),
    Gateway Registry (peer discovery),
    nginx_proxy (TLS termination)
}
```

**Key Properties**:
- ✅ Can start independently
- ✅ Can stop independently
- ✅ No shared infrastructure
- ✅ No external dependencies (except LLM APIs)

### Principle 2: Zero Shared State

**No shared resources between instances**:
- ❌ No shared PostgreSQL databases
- ❌ No shared Redis caches
- ❌ No shared Docker networks (except for testing convenience)
- ❌ No shared Keycloak realms
- ❌ No shared file systems

**Benefits**:
- State isolation (no cross-contamination)
- Fault isolation (one instance failure doesn't affect others)
- Data sovereignty (each organization owns their data)
- Compliance (HIPAA, GDPR, FedRAMP boundaries)

### Principle 3: A2A Protocol Only

**Single interaction mechanism**:
- Phase 1: Mutual registration (peer discovery)
- Phase 2: Task delegation (inter-gateway RPC)

**NOT used for interaction**:
- ❌ Direct database queries
- ❌ Shared message queues
- ❌ File system synchronization
- ❌ Direct service-to-service HTTP calls

---

## Instance Independence

### Full Stack per Instance

Each ADEPT instance runs the complete three-tier architecture:

```
┌──────────────────────────────────────────┐
│  ADEPT Instance (Self-Contained)         │
│                                          │
│  Tier 1: Agent Gateway                   │
│    ├── Authentication (JWT validation)   │
│    ├── RBAC (group-based authorization)  │
│    └── Proxying (to Tier 2)              │
│                                          │
│  Tier 2: Orchestration Service           │
│    ├── ScientificWorkflowAgent           │
│    ├── Multi-agent orchestration         │
│    ├── LangGraph checkpointing           │
│    └── Session management                │
│                                          │
│  Tier 3: MCP Tool Servers                │
│    ├── Scientific tools (BLAST, etc.)    │
│    ├── HPC pipelines (Nextflow)          │
│    ├── Sandbox execution                 │
│    ├── Opentrons (liquid handling)       │
│    ├── Academy (federated agents)        │
│    └── Custom domain tools               │
│                                          │
│  Infrastructure Services                 │
│    ├── PostgreSQL (state persistence)    │
│    ├── Redis (session cache)             │
│    ├── Keycloak (identity provider)      │
│    ├── nginx_proxy (TLS termination)     │
│    └── Gateway Registry (peer discovery) │
│                                          │
└──────────────────────────────────────────┘
```

### Configuration Isolation

**Separate Configuration Files**:
```
instance-a/.env:
  PUBLIC_HOSTNAME=gateway-a.api.agentic.local
  INSTANCE_ID=gateway-a
  POSTGRES_PORT=5432
  REDIS_PORT=6379
  KEYCLOAK_PORT=8180

instance-b/.env:
  PUBLIC_HOSTNAME=gateway-b.api.agentic.local
  INSTANCE_ID=gateway-b
  POSTGRES_PORT=5433
  REDIS_PORT=6380
  KEYCLOAK_PORT=9180
```

**Separate Credentials**:
```
instance-a/.env-keycloak-credentials-dir/
  ├── GATEWAY_CLIENT_SECRET (unique to instance A)
  ├── VALIDATION_RUNNER_CLIENT_SECRET (unique to instance A)
  └── SERVICE_API_KEYS_CONFIG (instance A tokens)

instance-b/.env-keycloak-credentials-dir/
  ├── GATEWAY_CLIENT_SECRET (unique to instance B)
  ├── VALIDATION_RUNNER_CLIENT_SECRET (unique to instance B)
  └── SERVICE_API_KEYS_CONFIG (instance B tokens)
```

---

## A2A Protocol

### Phase 1: Mutual Registration (Current)

**Goal**: Peer discovery and metadata storage

**Flow**:
```
Gateway A                           Gateway B
    |                                   |
    | 1. Generate service token         |
    |    (gateway-service group)        |
    |                                   |
    | 2. Register peer                  |
    |    POST /v1/gateway-registry      |
    |    {                              |
    |      alias: "gateway-b",          |
    |      public_url: "https://B/v1",  |
    |      tags: ["aws", "production"]  |
    |    }                              |
    |---------------------------------->|
    |                                   |
    |    200 OK (peer registered)       |
    |<----------------------------------|
    |                                   |
    | 3. Test connectivity              |
    |    GET https://B/v1/models        |
    |    Authorization: Bearer <token>  |
    |---------------------------------->|
    |                                   |
    |    200 OK (models list)           |
    |<----------------------------------|
```

**Components**:
1. **Service Token**: Long-lived bearer token (365 days) with `gateway-service` group
2. **Gateway Registry**: Stores peer metadata (alias, URL, capabilities, health)
3. **Authentication**: Keycloak validates service tokens at both gateways
4. **Connectivity Test**: Validates peer is reachable and responding

### Phase 2: Task Delegation (Planned)

**Goal**: Inter-instance RPC for distributed workloads

**Planned Flow**:
```
User → Gateway A: "Run protein folding simulation"
    |
Gateway A checks: Does this need specialized GPU?
    |
Gateway A queries: Which peers have GPU capabilities?
    |
Gateway A selects: Gateway B (has "gpu" tag)
    |
Gateway A delegates:
    POST https://B/v1/delegate
    {
      task_id: "task-123",
      operation: "protein_folding",
      parameters: {...},
      callback_url: "https://A/v1/callback"
    }
    |
Gateway B executes task using local MCP tools
    |
Gateway B returns results:
    POST https://A/v1/callback
    {
      task_id: "task-123",
      status: "completed",
      result: {...}
    }
    |
Gateway A returns to user: "Task completed successfully"
```

**Status**: Design phase, implementation pending

---

## Authentication Flow

### Service Token Generation

**Process**:
```
Admin/Script
    ↓
make create-service-token NAME=a2a-gateway-a GROUPS=gateway-service TTL_DAYS=365
    ↓
orchestration_service container
    ↓
scripts/deps/create_service_api_token.py
    ↓
1. Authenticates with Keycloak (using KC_ADMIN_CLI_SECRET)
2. Generates random 32-char token: sk-service-a2a-gateway-a-{random}
3. Stores in Redis Database 1 (instant sync)
4. Writes to SERVICE_API_KEYS_CONFIG file (backup)
5. Returns token to admin
    ↓
Token ready for A2A authentication
```

### Token Validation

**Process**:
```
Gateway A → Gateway B Request
    |
    | Authorization: Bearer sk-service-a2a-gateway-a-...
    ↓
Gateway B: agent_gateway/auth.py
    ↓
1. Check BOOTSTRAP_TOKENS (hardcoded, 0.01ms)
2. Check TokenCache (1-hour in-memory, 0.01ms, 99% hit rate)
3. Check Redis Database 1 (0.15ms, atomic)
4. Check FILE (SERVICE_API_KEYS_CONFIG, 0.01ms, fallback)
    ↓
Token found? → Extract groups (gateway-service)
    ↓
Validate groups allow endpoint access
    ↓
Return 200 OK or 401 Unauthorized
```

**Security Properties**:
- ✅ Stateless validation (no session storage)
- ✅ Fast validation (0.01ms cached, 0.15ms uncached)
- ✅ Group-based authorization (RBAC)
- ✅ Long-lived tokens (no refresh required)

---

## Gateway Registry

### Purpose

**Gateway Registry** provides peer discovery and health tracking:
- Store peer metadata (alias, URL, capabilities, tags)
- Track peer health status (last check timestamp)
- Query available peers (by capability, tag, region)

### Database Schema

```sql
CREATE TABLE gateway_registry (
    id UUID PRIMARY KEY,
    alias VARCHAR(255) UNIQUE NOT NULL,        -- Human-readable identifier
    public_url TEXT NOT NULL,                  -- Peer's Agent Gateway URL
    capabilities TEXT[],                       -- List of tags and descriptions
    last_health_check TIMESTAMP,               -- Last successful connectivity test
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### API Operations

**Register Peer**:
```bash
POST /v1/gateway-registry
{
  "alias": "aws-gateway",
  "public_url": "https://10.0.0.1/v1",
  "capabilities": [
    "description:AWS EC2 Production Gateway",
    "tag:aws",
    "tag:ec2",
    "tag:us-east-1"
  ]
}
```

**List Peers**:
```bash
GET /v1/gateway-registry
# Returns: [{"alias": "aws-gateway", "public_url": "https://...", ...}]
```

**Remove Peer**:
```bash
DELETE /v1/gateway-registry/<alias>
# Idempotent (returns success even if peer doesn't exist)
```

---

## Network Topology

### Single-Instance Architecture

```
┌─────────────────────────────────────────┐
│  ADEPT Instance                         │
│                                         │
│  adept_frontend_network                 │
│    ├── nginx_proxy (TLS termination)    │
│    └── oauth2_proxy (SSO)               │
│                                         │
│  adept_application_network              │
│    ├── agent_gateway (auth proxy)       │
│    ├── orchestration_service (brain)    │
│    ├── gateway_registry (peers)         │
│    ├── keycloak (identity)              │
│    └── MCP servers (tools)              │
│                                         │
│  adept_data_network                     │
│    ├── postgres (state)                 │
│    └── redis (cache)                    │
│                                         │
└─────────────────────────────────────────┘
```

### Multi-Instance Mesh Topology

```
┌─────────────┐         ┌─────────────┐         ┌─────────────┐
│  Instance A │◄───────►│  Instance B │◄───────►│  Instance C │
│  (Azure VM) │         │  (AWS EC2)  │         │  (GCP VM)   │
│             │         │             │         │             │
│  Registry:  │         │  Registry:  │         │  Registry:  │
│  - B, C     │         │  - A, C     │         │  - A, B     │
└─────────────┘         └─────────────┘         └─────────────┘
      ▲                       ▲                       ▲
      │                       │                       │
      └───────────────────────┼───────────────────────┘
                              │
                         A2A Protocol
                    (HTTPS, service tokens)
```

**Properties**:
- **Decentralized**: No central coordinator
- **Peer-to-Peer**: Any instance can delegate to any other
- **Symmetric**: All instances have equal capabilities (no master/slave)
- **Scalable**: Add new instances without reconfiguring existing ones

---

## Security Model

### Authentication Layers

**Layer 1: TLS Encryption**
- All A2A communication over HTTPS
- Self-signed certificates (development)
- CA-signed certificates (production)

**Layer 2: Service Token Authentication**
- Long-lived bearer tokens (365 days)
- Keycloak validation at each gateway
- Group-based authorization (gateway-service group)

**Layer 3: Request Validation**
- Schema validation on all API calls
- HMAC signature validation (future)
- Rate limiting (future)

### Authorization Model

**Service Token Groups**:
- `gateway-service`: Required for A2A operations
- `admin`: Full administrative access (not used for A2A)
- `notebook-users`: End-user access (not used for A2A)

**Endpoint Access Control**:
```python
# agent_gateway/auth.py
ENDPOINT_GROUP_REQUIREMENTS = {
    "/v1/models": ["notebook-users", "gateway-service"],
    "/v1/threads": ["notebook-users", "gateway-service"],
    "/v1/responses/chat/completions": ["notebook-users", "gateway-service"],
    "/admin/gateway-registry": ["admin", "gateway-service"],
}
```

### Credential Isolation

**Each instance has unique credentials**:
- GATEWAY_CLIENT_SECRET (agent gateway service account)
- VALIDATION_RUNNER_CLIENT_SECRET (gateway registry operations)
- KC_ADMIN_CLI_SECRET (admin operations)
- SERVICE_API_KEYS_CONFIG (service tokens)

**No credential sharing between instances**:
- Instance A's tokens don't work on Instance B
- Each instance validates tokens against its own Keycloak
- A2A requires service tokens generated on each instance

---

## Gateway Registry

### Purpose

**Centralized peer discovery** within each instance:
- Store metadata about remote peer gateways
- Track peer health and availability
- Query peers by capabilities, tags, region
- Enable intelligent task routing (Phase 2)

### Data Model

```python
class GatewayRegistration:
    alias: str              # Human-readable identifier (e.g., "aws-gateway")
    public_url: str         # Peer's Agent Gateway URL (e.g., "https://10.0.0.1/v1")
    capabilities: List[str] # Tags and descriptions (e.g., ["tag:aws", "description:..."])
    last_health_check: datetime  # Last successful connectivity test
    created_at: datetime
    updated_at: datetime
```

### Operations

**CRUD Operations**:
- **Create**: `POST /v1/gateway-registry` - Register new peer
- **Read**: `GET /v1/gateway-registry` - List all peers
- **Update**: `PUT /v1/gateway-registry/<alias>` - Update peer metadata (future)
- **Delete**: `DELETE /v1/gateway-registry/<alias>` - Remove peer

**Query Operations** (Future):
- Filter by tags: `GET /v1/gateway-registry?tags=aws,gpu`
- Filter by region: `GET /v1/gateway-registry?region=us-west-2`
- Health status: `GET /v1/gateway-registry/<alias>/health`

---

## A2A Protocol

### Phase 1: Registration (Current)

**Capabilities**:
- Register peer gateway with alias and URL
- Store peer metadata (description, tags)
- List all registered peers
- Test connectivity to peer
- Remove peer registration

**API Endpoints**:
```
POST   /v1/gateway-registry          # Register peer
GET    /v1/gateway-registry          # List peers
GET    /v1/gateway-registry/<alias>  # Get peer details
DELETE /v1/gateway-registry/<alias>  # Remove peer
```

**CLI Commands**:
```bash
agentic a2a register-peer <alias> <url> [--tags <tags>]
agentic a2a list-peers [--format table|json]
agentic a2a test-connection <alias> [--verbose]
agentic a2a remove-peer <alias> [--yes]
```

### Phase 2: Task Delegation (Planned)

**Capabilities** (Design):
- Delegate task to remote peer
- Track task execution status
- Receive results via callback
- Handle peer failures and retries

**Planned API**:
```
POST /v1/delegate                    # Delegate task to remote peer
GET  /v1/delegate/<task_id>/status   # Check delegation status
POST /v1/callback                    # Receive results from peer
```

**Planned Flow**:
```
1. User sends request to Gateway A
2. Gateway A analyzes: "Needs GPU capabilities"
3. Gateway A queries registry: "Which peers have tag:gpu?"
4. Gateway A selects Gateway B (has GPU)
5. Gateway A delegates: POST https://B/v1/delegate {task...}
6. Gateway B executes task using local MCP tools
7. Gateway B sends results: POST https://A/v1/callback {result...}
8. Gateway A returns to user
```

---

## Network Topology

### Physical Deployment Models

#### Model 1: Multi-Cloud (Azure + AWS)

```
Azure East US                          AWS US-East-1
10.0.0.2                            10.0.0.1
    │                                      │
    │    Internet or VPN/VPC Peering      │
    └─────────────────────────────────────┘
```

**Use Case**: Geographic distribution, cloud redundancy

#### Model 2: Multi-Region (Single Cloud)

```
AWS US-West-2          AWS US-East-1          AWS EU-West-1
10.0.1.100             10.0.2.100             10.0.3.100
    │                      │                      │
    └──────────────────────┴──────────────────────┘
              AWS Transit Gateway
```

**Use Case**: Low-latency regional access, compliance boundaries

#### Model 3: Hybrid Cloud (On-Premises + Cloud)

```
On-Premises Data Center    AWS Commercial      AWS GovCloud
192.168.1.100              10.20.30.40         10.50.60.70
    │                          │                   │
    │                          │                   │
    └──────────────────────────┴───────────────────┘
         VPN/Direct Connect    │    Isolated Network
```

**Use Case**: Data sovereignty, compliance (HIPAA, FedRAMP), cost optimization

### Port Requirements

**Minimum Firewall Rules**:

From Instance A to Instance B:
- **Port 443** (HTTPS): A2A communication via nginx_proxy
- **OR Port 8083** (HTTP): Direct agent_gateway access (development only)

**Security Best Practices**:
- ✅ Use HTTPS in production (port 443 via nginx_proxy)
- ✅ Restrict source IP (use CIDR blocks for peer IPs)
- ✅ Use security groups/NSG rules (never open to 0.0.0.0/0)
- ❌ Don't expose PostgreSQL, Redis, or internal services

---

## Security Model

### Threat Model

**Threats Addressed**:
1. **Unauthorized Access**: Service token authentication
2. **Man-in-the-Middle**: TLS encryption
3. **Token Theft**: Long-lived tokens stored securely
4. **Cross-Instance Contamination**: State isolation via independent databases

**Threats NOT Addressed** (Future Work):
1. **Token Replay**: No HMAC request signing yet
2. **Rate Limiting**: No DoS protection for A2A endpoints
3. **Audit Logging**: No centralized audit trail for A2A operations

### Security Best Practices

**Service Token Management**:
- ✅ Generate unique token per peer relationship
- ✅ Use long TTL (365 days) for stable deployments
- ✅ Rotate tokens annually or after security incidents
- ✅ Store tokens in secret managers (AWS Secrets Manager, HashiCorp Vault)
- ❌ Don't commit tokens to version control
- ❌ Don't share tokens between instances

**Network Security**:
- ✅ Use TLS for all A2A communication (HTTPS)
- ✅ Restrict firewall rules to known peer IPs
- ✅ Use VPN or VPC peering for cross-cloud communication
- ❌ Don't expose internal services (PostgreSQL, Redis)
- ❌ Don't use HTTP in production

**Credential Rotation**:
```bash
# Annual rotation workflow
# 1. Generate new token
./01_generate_a2a_token.sh --name a2a-gateway-a-v2 --ttl-days 365

# 2. Update peer configurations
# (Store new token in peer's configuration)

# 3. Verify new token works
./03_test_connectivity.sh --peer-alias peer-gateway

# 4. Revoke old token
make revoke-service-token TOKEN=sk-service-a2a-gateway-a-v1-...
```

### Cross-VM JWKS Federation (Session 80)

When ADEPT instances delegate tasks across VMs via A2A, **two JWT validation steps** occur on the receiving gateway:

1. **Service token validation** (`keycloak_context_builder.py`) -- Gateway-to-gateway authentication
2. **User token validation** (`core/auth.py:validate_jwt_multi_stack()`) -- Forwarded user identity

**The Problem**: Both VMs use `KEYCLOAK_URL=http://keycloak:8180` (Docker-internal hostname). When the issuer claim matches the local Keycloak URL, JWKS is fetched from the **local** Keycloak -- which doesn't have the peer VM's signing keys.

**The Fix**: `validate_jwt_multi_stack()` now has peer JWKS federation. If a kid isn't found in local JWKS, it iterates `A2A_TRUSTED_PEER_JWKS_URLS` to fetch peer JWKS endpoints and merge keys.

**Configuration**:
```bash
# On Azure VM (.env)
A2A_TRUSTED_PEER_JWKS_URLS=https://10.0.0.1/realms/master/protocol/openid-connect/certs

# On AWS VM (.env)
A2A_TRUSTED_PEER_JWKS_URLS=https://10.0.0.2/realms/master/protocol/openid-connect/certs
```

**Verification**: Check logs for `[A2A_USER_TOKEN]` prefix entries showing peer JWKS fallback.

**Architecture Diagrams**: See `docs/workshop/diagrams/a2a_peer_jwks_*.mmd` for rendered diagrams.

**Full Details**: [`docs/bugfixes/SESSION_80_A2A_CROSS_VM_USER_TOKEN_VALIDATION.md`](../../../docs/bugfixes/SESSION_80_A2A_CROSS_VM_USER_TOKEN_VALIDATION.md)

---

## Scalability Considerations

### Horizontal Scaling

**Within Single Instance**:
- Agent Gateway: Scale horizontally (stateless, load balanced)
- Orchestration Service: Scale horizontally (stateless orchestration logic)
- MCP Servers: Scale based on workload (CPU/GPU requirements)

**Across Instances**:
- Add new peer gateways without reconfiguring existing ones
- Full mesh topology: N*(N-1) peer registrations for N instances
- Star topology: Central hub with spoke instances (simpler, single point of failure)

### Performance Metrics

**Target Metrics** (Phase 2):
- A2A latency: <500ms for task delegation
- Throughput: >100 tasks/second per gateway
- Peer discovery: <100ms to query registry
- Health checks: <5 seconds per peer

---

## Production Considerations

### High Availability

**Single Instance HA**:
- Multiple agent_gateway replicas behind load balancer
- PostgreSQL replication (primary + standby)
- Redis Sentinel for cache HA

**Multi-Instance HA**:
- Peer failover: Redirect tasks to healthy peers
- Health monitoring: Automated peer health checks
- Circuit breaker: Disable failing peers automatically

### Monitoring

**Metrics to Track**:
- A2A request latency (p50, p95, p99)
- Peer health status (up/down, response time)
- Token expiration dates (alert 30 days before)
- Task delegation success rate (Phase 2)

**Alerting**:
- Peer connectivity failures
- Token expiration warnings
- Gateway Registry unavailability
- Abnormal A2A traffic patterns

---

## Related Documentation

- **Workshop Guide**: `../README.md` - Hands-on setup instructions (Phases 1-3)
- **Quick Reference**: `QUICK_REFERENCE.md` - One-page command guide
- **Phase 2 Design**: `../../../docs/implementation-plans/session-52/14_PHASE2_REVISED_INDEPENDENT_INSTANCES.md`
- **Opentrons MCP Server**: `../../opentrons_mcp_server/README.md` - Phase 2 tool server
- **Academy MCP Server**: `../../academy_mcp_server/README.md` - Phase 3 tool server
- **Systems Admin Guide**: `../../../docs/SYSTEMS_ADMINISTRATOR_ONBOARDING.md`

---

**Last Updated**: February 16, 2026
**Version**: 1.1
**Status**: Phase 1 Complete, Phase 2 (Opentrons) Complete, Phase 3 (Academy) Complete
