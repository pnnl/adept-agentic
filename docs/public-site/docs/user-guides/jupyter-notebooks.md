# JupyterLab and Notebooks

ADEPT integrates JupyterLab as a first-class scientific computing environment, providing authenticated access to the full platform API directly from notebooks.

## Overview

JupyterLab runs as part of the ADEPT stack with:

- Single sign-on via Keycloak (OAuth2/OIDC)
- Direct access to the ADEPT API for agent interactions
- Pre-configured scientific Python environment
- Session-scoped file access for uploaded data

## Accessing JupyterLab

JupyterLab is available through the ADEPT web interface after authentication. Access is controlled by Keycloak group membership -- users in the `notebook-users` group are granted access.

## Authentication

JupyterLab authenticates through the same OAuth2 flow as all other ADEPT services:

1. User navigates to the JupyterLab URL
2. OAuth2 proxy redirects to Keycloak login
3. After authentication, a session cookie grants access
4. API calls from notebooks use the same user identity

!!! tip "Token Access"
    Your Keycloak token is available within the notebook environment for making authenticated API calls to other ADEPT services.

## Using ADEPT from Notebooks

### Chat with the Agent

```python
import httpx

BASE_URL = "https://your-adept-server.example.com/v1"
TOKEN = "your-jwt-token"
headers = {"Authorization": f"Bearer {TOKEN}"}

# Create a thread
resp = httpx.post(f"{BASE_URL}/threads", headers=headers)
thread_id = resp.json()["id"]

# Send a message via the Responses API
resp = httpx.post(f"{BASE_URL}/responses/chat/completions", headers=headers, json={
    "model": "default",
    "messages": [{"role": "user", "content": "Analyze my dataset"}],
    "thread_id": thread_id,
    "stream": False,
})
print(resp.json()["choices"][0]["message"]["content"])
```

### Upload Files

```python
with open("experiment_data.csv", "rb") as f:
    resp = httpx.post(f"{BASE_URL}/files", headers=headers,
        files={"file": ("experiment_data.csv", f, "text/csv")},
        data={"purpose": "assistants"})
file_id = resp.json()["id"]
```

### Query RAG Indexes

```python
resp = httpx.post(f"{BASE_URL}/responses/chat/completions", headers=headers, json={
    "model": "default",
    "messages": [{"role": "user", "content": "What are the key findings in my paper?"}],
    "thread_id": thread_id,
    "stream": False,
})
print(resp.json()["choices"][0]["message"]["content"])
```

## Tips

!!! info "Session Continuity"
    Use the same `thread_id` across multiple cells to maintain conversation context. The agent remembers prior messages and uploaded files within a thread.

- **Large files**: For files over 100 MB, consider splitting them or using batch processing tools.
- **Streaming**: Set `"stream": True` and iterate over the SSE response for real-time output in long-running analyses.
- **Multi-agent teams**: Create specialized teams (e.g., biologist + data scientist) via the `CreateMultiAgentSession` tool for complex analyses.
- **Kernel restarts**: Thread state persists server-side, so restarting your kernel does not lose conversation history.
