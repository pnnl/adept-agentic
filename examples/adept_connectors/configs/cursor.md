# Cursor — ADEPT Integration via Auth Proxy

## Setup

1. Start the ADEPT auth proxy:

   ```bash
   adept-auth-proxy --port 19283 --auth-method password --username <user> --password <pass>
   ```

2. In Cursor, open **Settings > Models > OpenAI API Key**:

   - **API Key**: `not-needed-proxy-handles-auth`
   - **Base URL**: `http://localhost:19283/v1`

3. Select model: `agentic-framework:scientific-agent-v1`

## Notes

- Cursor requires a non-empty API key field — any placeholder string works
- The auth proxy handles all ADEPT authentication transparently
- SSE streaming is fully supported
