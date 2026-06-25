# OBot.ai — ADEPT Integration via Auth Proxy

## Setup

1. Start the ADEPT auth proxy:

   ```bash
   adept-auth-proxy --port 19283 --auth-method password --username <user> --password <pass>
   ```

2. In OBot.ai, configure a custom OpenAI-compatible model provider:

   - **Base URL**: `http://localhost:19283/v1`
   - **Model ID**: `agentic-framework:scientific-agent-v1`
   - **API Key**: `not-needed-proxy-handles-auth`

3. Create an agent using the ADEPT model provider.

## Notes

- OBot.ai supports standard OpenAI-compatible endpoints
- The auth proxy handles ADEPT authentication (API key, JWT, or Keycloak ROPC)
- Tool calling is supported via the ADEPT Responses API
