# Authentication Guide

## Overview

The ADEPT Agentic Framework uses Keycloak for authentication with JWT bearer tokens. This guide covers obtaining and using authentication tokens for API access.

## Authentication Flows

### 1. ROPC Flow (End Users)

Resource Owner Password Credentials (ROPC) flow is used for end-user authentication.

```bash
# Configuration
export KEYCLOAK_URL="http://localhost:8180"
export USERNAME="your-username"
export PASSWORD="your-password"
export CLIENT_ID="login-client"

# Obtain token
TOKEN=$(curl -s -X POST "${KEYCLOAK_URL}/realms/agentic-framework/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "client_id=${CLIENT_ID}" \
  -d "grant_type=password" \
  -d "username=${USERNAME}" \
  -d "password=${PASSWORD}" \
  | jq -r '.access_token')

echo "Token obtained: ${TOKEN:0:50}..."
```

### 2. Client Credentials Flow (Services)

Service-to-service authentication uses Client Credentials flow.

```bash
# Service credentials (from .env-keycloak-credentials)
export CLIENT_ID="your-service-client-id"
export CLIENT_SECRET="your-service-client-secret"

# Obtain token
TOKEN=$(curl -s -X POST "${KEYCLOAK_URL}/realms/agentic-framework/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "client_id=${CLIENT_ID}" \
  -d "client_secret=${CLIENT_SECRET}" \
  -d "grant_type=client_credentials" \
  | jq -r '.access_token')

echo "Service token obtained"
```

## Using Tokens

### cURL

```bash
# Basic request with token
curl -X POST http://localhost:8080/v1/responses/chat/completions \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

### Python (OpenAI SDK)

```python
import os
from openai import OpenAI

# Use JWT token as API key
client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key=os.getenv("KEYCLOAK_TOKEN"),
    default_headers={"Authorization": f"Bearer {os.getenv('KEYCLOAK_TOKEN')}"}
)

# Make requests (token automatically included)
response = client.responses.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

### JavaScript/TypeScript

```typescript
import axios from 'axios';

const token = process.env.KEYCLOAK_TOKEN;

const response = await axios.post(
  'http://localhost:8080/v1/responses/chat/completions',
  {
    model: 'gpt-4',
    messages: [{ role: 'user', content: 'Hello!' }]
  },
  {
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    }
  }
);
```

## Token Management

### Token Expiration

Keycloak tokens expire after a configured duration (typically 5-60 minutes). Check token validity:

```bash
# Decode JWT to check expiration
echo ${TOKEN} | cut -d. -f2 | base64 -d 2>/dev/null | jq .exp

# Compare with current time
CURRENT_TIME=$(date +%s)
TOKEN_EXP=$(echo ${TOKEN} | cut -d. -f2 | base64 -d 2>/dev/null | jq -r .exp)

if [[ ${TOKEN_EXP} -gt ${CURRENT_TIME} ]]; then
  echo "Token is valid"
else
  echo "Token expired - refresh needed"
fi
```

### Token Refresh

```bash
# Get refresh token during initial authentication
REFRESH_TOKEN=$(curl -s -X POST "${KEYCLOAK_URL}/realms/agentic-framework/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "client_id=${CLIENT_ID}" \
  -d "grant_type=password" \
  -d "username=${USERNAME}" \
  -d "password=${PASSWORD}" \
  | jq -r '.refresh_token')

# Use refresh token to get new access token
NEW_TOKEN=$(curl -s -X POST "${KEYCLOAK_URL}/realms/agentic-framework/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "client_id=${CLIENT_ID}" \
  -d "grant_type=refresh_token" \
  -d "refresh_token=${REFRESH_TOKEN}" \
  | jq -r '.access_token')
```

## RBAC and Groups

The JWT token includes a `groups` claim that determines API access:

### Token Structure

```json
{
  "exp": 1704672000,
  "iat": 1704668400,
  "sub": "user-uuid-123",
  "preferred_username": "scientist1",
  "email": "scientist1@example.com",
  "groups": [
    "user",
    "data-scientists"
  ],
  "realm_access": {
    "roles": ["user"]
  }
}
```

### Group Permissions

| Group | Access Level |
|-------|-------------|
| `admin` | Full access including `/admin/*` and `/v1/tools/register` |
| `user` | Standard user access to public APIs |
| `data-scientists` | Scientific tools and knowledge bases |
| `notebook-users` | JupyterLab access |
| `gateway-service` | Service-to-service communication |

### Checking Your Groups

```bash
# Decode token to see groups
echo ${TOKEN} | cut -d. -f2 | base64 -d 2>/dev/null | jq .groups
```

## Environment Variables

Create a `.env` file for local development:

```bash
# Keycloak Configuration
KEYCLOAK_URL=http://localhost:8180
KEYCLOAK_REALM=agentic-framework
KEYCLOAK_CLIENT_ID=login-client

# User Credentials (for testing)
TEST_USERNAME=scientist1
TEST_PASSWORD=password

# API Configuration
API_BASE_URL=http://localhost:8080/v1
```

Load and use:

```bash
source .env

# Get token
export KEYCLOAK_TOKEN=$(curl -s -X POST "${KEYCLOAK_URL}/realms/${KEYCLOAK_REALM}/protocol/openid-connect/token" \
  -d "client_id=${KEYCLOAK_CLIENT_ID}" \
  -d "grant_type=password" \
  -d "username=${TEST_USERNAME}" \
  -d "password=${TEST_PASSWORD}" \
  | jq -r '.access_token')
```

## Troubleshooting

### Error: 401 Unauthorized

**Cause**: Invalid or expired token

**Solution**:
```bash
# Obtain a fresh token
export KEYCLOAK_TOKEN=$(curl -s -X POST "${KEYCLOAK_URL}/realms/agentic-framework/protocol/openid-connect/token" \
  -d "client_id=login-client" \
  -d "grant_type=password" \
  -d "username=${USERNAME}" \
  -d "password=${PASSWORD}" \
  | jq -r '.access_token')
```

### Error: 403 Forbidden

**Cause**: User lacks required group membership

**Solution**: Contact admin to add you to the required group (e.g., `data-scientists` for KB access)

### Error: Invalid Client

**Cause**: Client ID or secret incorrect

**Solution**: Verify credentials in `.env-keycloak-credentials` directory

### Token Validation Failure

**Cause**: Keycloak not accessible or realm misconfigured

**Solution**:
```bash
# Check Keycloak health
curl http://localhost:8180/health

# Verify realm configuration
curl http://localhost:8180/realms/agentic-framework/.well-known/openid-configuration
```

## Security Best Practices

1. **Never commit tokens** to version control
2. **Use environment variables** for credentials
3. **Rotate credentials regularly** (every 90 days)
4. **Use Client Credentials flow** for service accounts
5. **Implement token refresh** for long-running applications
6. **Monitor token expiration** and refresh proactively
7. **Use HTTPS** in production deployments
8. **Limit token scope** to required permissions

## Advanced: Service-to-Service Authentication

For internal service communication, use secure headers:

```bash
# Service makes request with user context forwarding
curl -X POST http://orchestration_service:8084/v1/responses/completions \
  -H "X-Service-API-Key: ${SERVICE_API_KEY}" \
  -H "X-Forwarded-User-Token: ${USER_JWT}" \
  -H "X-Forwarded-User-Id: ${USER_ID}" \
  -H "X-Forwarded-User-Groups: user,data-scientists" \
  -H "Content-Type: application/json" \
  -d '{ ... }'
```

## Next Steps

- [Response API Examples](./response-api.md)
- [Knowledge Base Operations](./knowledge-bases.md)
- [Admin Tool Management](../README.md#example-4-admin-tool-registration)
