# AG-UI Clients — ADEPT Integration

## Direct Connection (No Proxy Needed)

AG-UI clients can connect directly to the ADEPT AG-UI endpoint:

```
Endpoint: http://localhost:8083/v1/ag-ui/run
```

## Via Auth Proxy

If your AG-UI client doesn't handle Keycloak auth natively:

1. Start the auth proxy:

   ```bash
   adept-auth-proxy --port 19283
   ```

2. Point the AG-UI client at:

   ```
   http://localhost:19283/v1/ag-ui/run
   ```

The proxy injects auth headers and forwards the JSONL stream transparently.

## Protocol

AG-UI uses JSONL streaming over HTTP POST. The ADEPT endpoint is fully
AG-UI-compatible:

- `POST /v1/ag-ui/run` — Start a run (JSONL response stream)
- Events: `RUN_STARTED`, `TEXT_MESSAGE_*`, `TOOL_CALL_*`, `RUN_FINISHED`

See `docs/architecture/AG_UI_PROTOCOL_ARCHITECTURE.md` for details.
