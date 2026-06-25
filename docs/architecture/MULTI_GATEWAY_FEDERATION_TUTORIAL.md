# Multi-Gateway Federation Tutorial: Establishing Trust Between Independent Instances

## Overview

This tutorial provides a comprehensive guide for establishing mutual trust and registration between multiple Agent Gateway instances, where each instance operates with its own independent Keycloak identity management system. This federated architecture enables secure Agent-to-Agent (A2A) communication across organizationally separate deployments.

## Use Case: Federated Multi-Organization Deployment

### Scenario

- **Organization A** operates Gateway Instance A with Keycloak A
- **Organization B** operates Gateway Instance B with Keycloak B
- Both organizations want to enable cross-gateway agent communication while maintaining independent identity management

### Architecture Principles

1. **Autonomous Identity Management**: Each gateway maintains sovereignty over user/service authentication
2. **Mutual Trust Establishment**: Operators explicitly configure trust relationships via Management UI
3. **JWT-based Federation**: Cross-instance authentication uses service-to-service tokens
4. **A2A Mesh Communication**: Registered gateways can invoke agents across instances

## Prerequisites

### For Each Gateway Instance

1. **Deployed Services** (via Docker Compose):
   - Keycloak (port 8180)
   - Agent Gateway (port 8081)
   - Orchestration Service (port 8000)
   - Gateway Management UI (port 8502)
   - PostgreSQL (for Gateway Registry persistence)

2. **Network Accessibility**:
   - Public URLs for cross-instance communication
   - Internal URLs for service-to-service calls within instance

3. **Admin Credentials**:
   - Keycloak admin account
   - Gateway admin user account

## Step-by-Step Federation Setup

### Phase 1: Prepare Each Gateway Instance

#### Instance A Setup

1. **Access Management UI**:
   ```
   http://instance-a.example.com:8502
   ```

2. **Login as Admin**:
   - Use Keycloak A credentials
   - Verify admin role in Keycloak A

3. **Document Instance Information**:
   ```json
   {
     "alias": "org-a-gateway",
     "public_url": "https://gateway-a.example.com:8081",
     "internal_url": "http://agent_gateway:8081",
     "capabilities": ["scientific-workflow", "multi-agent"]
   }
   ```

4. **Create Service Client for Federation** (via Management UI → Client Management):
   - Client ID: `federation-service-org-b`
   - Purpose: Allow Organization B to authenticate to this instance
   - **IMPORTANT**: Save the generated Client Secret securely
   - Assign role: `gateway-service` (enables A2A communication)

#### Instance B Setup

Follow identical steps for Instance B:
```json
{
  "alias": "org-b-gateway",
  "public_url": "https://gateway-b.example.com:8081",
  "internal_url": "http://agent_gateway:8081",
  "capabilities": ["bioinformatics", "hpc-workflow"]
}
```

Create service client:
- Client ID: `federation-service-org-a`
- Assign role: `gateway-service`

### Phase 2: Exchange Trust Credentials

This is a **manual operator-to-operator** exchange via secure channel:

**Organization A sends to Organization B**:
```json
{
  "keycloak_url": "https://keycloak-a.example.com:8180",
  "realm": "master",
  "client_id": "federation-service-org-b",
  "client_secret": "<SECRET_FROM_PHASE_1>",
  "token_endpoint": "https://keycloak-a.example.com:8180/realms/master/protocol/openid-connect/token"
}
```

**Organization B sends to Organization A**:
```json
{
  "keycloak_url": "https://keycloak-b.example.com:8180",
  "realm": "master",
  "client_id": "federation-service-org-a",
  "client_secret": "<SECRET_FROM_PHASE_1>",
  "token_endpoint": "https://keycloak-b.example.com:8180/realms/master/protocol/openid-connect/token"
}
```

### Phase 3: Register Remote Gateways via Management UI

#### On Instance A: Register Instance B

1. **Access Management UI** (`http://instance-a.example.com:8502`)

2. **Navigate to Gateway Registration**:
   - Look for "Gateway Registry" or "Remote Gateway Management" section
   - This uses the Gateway Registry service internally

3. **Register Remote Gateway**:
   ```
   Gateway Alias: org-b-gateway
   Public URL: https://gateway-b.example.com:8081
   Internal URL: (leave blank for remote gateways)
   Capabilities: bioinformatics, hpc-workflow

   Authentication Configuration:
   - Token Endpoint: https://keycloak-b.example.com:8180/realms/master/protocol/openid-connect/token
   - Client ID: federation-service-org-a
   - Client Secret: <ORG_B_PROVIDED_SECRET>
   ```

4. **Save Configuration**:
   - The Management UI will call the Gateway Registry API:
     ```
     POST /v1/gateways
     Authorization: Bearer <ADMIN_TOKEN>
     ```
   - Gateway info is persisted to PostgreSQL

#### On Instance B: Register Instance A

Mirror the process with Instance A's credentials:
```
Gateway Alias: org-a-gateway
Public URL: https://gateway-a.example.com:8081
Internal URL: (leave blank)
Capabilities: scientific-workflow, multi-agent

Authentication Configuration:
- Token Endpoint: https://keycloak-a.example.com:8180/realms/master/protocol/openid-connect/token
- Client ID: federation-service-org-b
- Client Secret: <ORG_A_PROVIDED_SECRET>
```

### Phase 3B: Register Remote Gateways via CLI Tool (Alternative)

For automation or scriptable deployments, you can use the Gateway Registry CLI tool instead of the Management UI.

#### Prerequisites

1. **Install Python dependencies**:
   ```bash
   pip install httpx
   ```

2. **Obtain Admin Token**:
   ```bash
   # Get admin token from your local Keycloak
   export ADMIN_TOKEN=$(curl -s -X POST "https://keycloak-a.example.com:8180/realms/master/protocol/openid-connect/token" \
     -d "grant_type=password" \
     -d "client_id=admin-cli" \
     -d "username=admin" \
     -d "password=admin" | jq -r '.access_token')
   ```

#### On Instance A: Register Instance B via CLI

```bash
# From the agentic_framework repository root
python -m agentic_framework_pkg.gateway_registry.cli \
  --registry-url "http://localhost:8086" \
  register \
  --alias "org-b-gateway" \
  --public-url "https://gateway-b.example.com:8081" \
  --capabilities "bioinformatics,hpc-workflow"

# Output:
{
  "alias": "org-b-gateway",
  "public_url": "https://gateway-b.example.com:8081",
  "internal_url": null,
  "capabilities": ["bioinformatics", "hpc-workflow"],
  "health_status": "unknown",
  "created_at": "2025-11-06T08:30:00Z"
}
```

#### On Instance B: Register Instance A via CLI

```bash
python -m agentic_framework_pkg.gateway_registry.cli \
  --registry-url "http://localhost:8086" \
  register \
  --alias "org-a-gateway" \
  --public-url "https://gateway-a.example.com:8081" \
  --capabilities "scientific-workflow,multi-agent"
```

#### List All Registered Gateways

```bash
python -m agentic_framework_pkg.gateway_registry.cli \
  --registry-url "http://localhost:8086" \
  list

# Output:
[
  {
    "alias": "org-a-gateway",
    "public_url": "https://gateway-a.example.com:8081",
    "health_status": "healthy"
  },
  {
    "alias": "org-b-gateway",
    "public_url": "https://gateway-b.example.com:8081",
    "health_status": "healthy"
  }
]
```

#### Unregister Gateway (if needed)

```bash
python -m agentic_framework_pkg.gateway_registry.cli \
  --registry-url "http://localhost:8086" \
  unregister \
  --alias "org-b-gateway"

# Output:
Gateway 'org-b-gateway' unregistered successfully.
```

**Note**: The CLI tool currently has a placeholder for token authentication (`get_admin_token()` function). In production, you should:
1. Modify the CLI to accept `ADMIN_TOKEN` as an environment variable
2. Or use a proper OAuth client credentials flow
3. Management UI handles this authentication automatically

### Phase 4: Verify Federation

#### Test Cross-Gateway Discovery

**From Instance A**:
1. Access Management UI
2. Navigate to "Registered Gateways"
3. Verify `org-b-gateway` appears with status `Active`

**From Instance B**:
1. Verify `org-a-gateway` appears with status `Active`

#### Test A2A Communication

**Option 1: Via Management UI Health Check**
- Use the "Test Gateway Connection" button
- Should show successful JWT acquisition and health check

**Option 2: Via API**
From Instance A, call:
```bash
# Get auth token from Instance A's Keycloak
TOKEN_A=$(curl -s -X POST "https://keycloak-a.example.com:8180/realms/master/protocol/openid-connect/token" \
  -d "grant_type=password" \
  -d "client_id=admin-cli" \
  -d "username=admin" \
  -d "password=admin" | jq -r '.access_token')

# List registered gateways
curl -X GET "https://gateway-a.example.com:8081/v1/gateways/" \
  -H "Authorization: Bearer $TOKEN_A"

# Expected response:
[
  {
    "alias": "org-a-gateway",
    "public_url": "https://gateway-a.example.com:8081",
    "health_status": "healthy"
  },
  {
    "alias": "org-b-gateway",
    "public_url": "https://gateway-b.example.com:8081",
    "health_status": "healthy"
  }
]
```

#### Test Cross-Gateway Agent Invocation

**From User on Instance A to Agent on Instance B**:

1. User authenticates to Instance A's Keycloak
2. Calls Instance A's Agent Gateway:
   ```bash
   curl -X POST "https://gateway-a.example.com:8081/v1/chat/completions" \
     -H "Authorization: Bearer $USER_TOKEN_A" \
     -H "Content-Type: application/json" \
     -d '{
       "model": "agentic-framework:bioinformatics-agent@org-b-gateway",
       "messages": [{"role": "user", "content": "Run BLAST analysis"}]
     }'
   ```

3. **Behind the Scenes**:
   - Gateway A recognizes `@org-b-gateway` suffix
   - Looks up `org-b-gateway` registration
   - Obtains service token from Keycloak B using stored credentials
   - Proxies request to Gateway B with B's service token
   - Gateway B validates token against its Keycloak B
   - Orchestration Service B executes agent
   - Response proxied back to User via Gateway A

## Architecture Details

### Trust Chain

```
User@OrgA                        Gateway A                     Gateway B                      Agent@OrgB
   |                                 |                             |                              |
   |-- Auth to Keycloak A --------->|                             |                              |
   |<-- JWT (OrgA) ------------------|                             |                              |
   |                                 |                             |                              |
   |-- Agent Request --------------->|                             |                              |
   |    (JWT OrgA)                   |                             |                              |
   |                                 |                             |                              |
   |                                 |-- Request Service Token --->|                              |
   |                                 |   (Client Credentials)      |                              |
   |                                 |                             |                              |
   |                                 |<-- Service JWT (OrgB) ------|                              |
   |                                 |                             |                              |
   |                                 |-- Proxy Agent Request ----->|                              |
   |                                 |   (Service JWT OrgB)        |-- Validate JWT B ----------->|
   |                                 |                             |                              |
   |                                 |                             |<-- Execute Agent ------------|
   |                                 |                             |                              |
   |<-- Agent Response (via A) ------|<-- Response -----------------|                              |
```

### Security Considerations

1. **Token Scope Isolation**:
   - User tokens never cross instance boundaries
   - Only service-to-service tokens used for A2A calls
   - Each Keycloak validates its own tokens

2. **Credential Storage**:
   - Service client secrets stored encrypted in Gateway Registry DB
   - Never exposed in API responses
   - Management UI masks secrets after initial creation

3. **Audit Logging**:
   - All cross-gateway calls logged with source instance
   - Keycloak audit logs maintained independently per instance

4. **Revocation**:
   - Operators can delete gateway registration via Management UI
   - Deleted registration immediately blocks cross-gateway calls
   - Keycloak client can be disabled independently

## Troubleshooting

### Federation Health Check Failures

**Symptom**: Gateway shows as `Unreachable` in Management UI

**Diagnostic Steps**:
1. Verify network connectivity:
   ```bash
   curl -I https://gateway-b.example.com:8081/health
   ```

2. Test token acquisition:
   ```bash
   curl -X POST "https://keycloak-b.example.com:8180/realms/master/protocol/openid-connect/token" \
     -d "grant_type=client_credentials" \
     -d "client_id=federation-service-org-a" \
     -d "client_secret=<SECRET>"
   ```

3. Check Gateway Registry logs:
   ```bash
   docker logs gateway_registry | grep "org-b-gateway"
   ```

### JWT Validation Errors

**Symptom**: `401 Unauthorized` on cross-gateway calls

**Causes**:
- Client secret mismatch
- Client disabled in remote Keycloak
- Role `gateway-service` not assigned to client

**Fix**:
1. Re-verify client configuration in remote Keycloak
2. Regenerate client secret if needed
3. Update registration in Management UI with new secret

### Token Expiration

**Symptom**: Intermittent `401` errors after period of inactivity

**Solution**:
- Gateway automatically refreshes service tokens
- Check `TOKEN_REFRESH_INTERVAL` environment variable
- Default: 300 seconds (5 minutes)

## Advanced Configuration

### Multi-Region Deployment

For gateways in different geographic regions:

1. **Use Regional Keycloak Replicas** (if using Keycloak clustering)
2. **Configure Longer Token Lifetimes** for high-latency links
3. **Set Timeout Overrides** in gateway registration:
   ```json
   {
     "timeout_settings": {
       "connect_timeout": 30,
       "read_timeout": 300
     }
   }
   ```

### Role-Based A2A Access Control

Restrict which gateways can call specific agents:

1. **Define Gateway Roles** in Keycloak:
   - `gateway-service` (basic A2A)
   - `gateway-sensitive` (access to sensitive agents)

2. **Update Client Role Assignments** via Management UI
3. **Configure Agent ACLs** to require specific roles

### Federation Monitoring

**Enable Metrics Collection**:
```yaml
# docker-compose-gateway.yaml
services:
  agent_gateway:
    environment:
      - ENABLE_FEDERATION_METRICS=true
      - METRICS_PORT=9090
```

**View Metrics** (Prometheus format):
```
# HELP agentic_framework_federation_calls_total Total A2A calls per gateway
# TYPE agentic_framework_federation_calls_total counter
agentic_framework_federation_calls_total{source="org-a-gateway",target="org-b-gateway"} 1523
```

## Summary

This tutorial covered:
- **Phase 1**: Independent gateway preparation with dedicated Keycloak instances
- **Phase 2**: Secure credential exchange between operators
- **Phase 3**: Gateway registration via Management UI
- **Phase 4**: Verification of federation and A2A communication

The federated architecture maintains organizational autonomy while enabling seamless cross-instance agent orchestration. Operators retain full control over trust relationships and can revoke federation at any time via the Management UI.

## Next Steps

- [Gateway Management UI User Guide](./agent_gateway_mgmt.md)
- [Multi-Stack Deployment Guide](./multi-stack-deployment-guide.md)
- [A2A Security Architecture](./sso-mfa-architecture.md)
