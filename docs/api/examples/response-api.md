# Response API Examples

## Overview

The Response API is the **recommended interface** for chat completions in the ADEPT Agentic Framework. It provides a simplified, OpenAI-compatible API with full support for:
- Multi-turn conversations
- Tool calling (MCP tools)
- Streaming responses
- Session management
- Multi-agent orchestration

**Why Use Response API?**
- Simpler than Assistants API (no thread/run management)
- Better streaming support
- Direct tool execution
- Lower latency
- Active development focus

## Basic Usage

### Simple Chat Completion

```bash
curl -X POST http://localhost:8080/v1/responses/chat/completions \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4",
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "What is the capital of France?"}
    ]
  }'
```

**Response**:
```json
{
  "id": "resp_abc123",
  "object": "chat.completion",
  "created": 1704668400,
  "model": "gpt-4",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "The capital of France is Paris."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 25,
    "completion_tokens": 8,
    "total_tokens": 33
  }
}
```

### Python Example

```python
import os
from openai import OpenAI

# Initialize client
client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key=os.getenv("KEYCLOAK_TOKEN")
)

# Create completion
response = client.responses.chat.completions.create(
    model="gpt-4",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Explain quantum computing in simple terms."}
    ],
    temperature=0.7,
    max_tokens=500
)

print(response.choices[0].message.content)
```

## Advanced Features

### 1. Multi-Turn Conversations

Maintain conversation context by including message history:

```python
messages = [
    {"role": "system", "content": "You are a helpful math tutor."},
    {"role": "user", "content": "What is 25 * 4?"},
    {"role": "assistant", "content": "25 * 4 = 100"},
    {"role": "user", "content": "Now multiply that by 3"}
]

response = client.responses.chat.completions.create(
    model="gpt-4",
    messages=messages
)

print(response.choices[0].message.content)  # "100 * 3 = 300"
```

### 2. Session Management

Use session IDs for persistent state:

```python
import uuid

# Create session ID for this conversation
session_id = str(uuid.uuid4())
mcp_session_id = str(uuid.uuid4())

response = client.responses.chat.completions.create(
    model="gpt-4",
    messages=[
        {"role": "user", "content": "Remember that my favorite color is blue"}
    ],
    session_id=session_id,
    mcp_session_id=mcp_session_id
)

# Later in the conversation (same session)
response = client.responses.chat.completions.create(
    model="gpt-4",
    messages=[
        {"role": "user", "content": "What is my favorite color?"}
    ],
    session_id=session_id,
    mcp_session_id=mcp_session_id
)

print(response.choices[0].message.content)  # "Your favorite color is blue."
```

### 3. Streaming Responses

Enable streaming for real-time output:

```python
stream = client.responses.chat.completions.create(
    model="gpt-4",
    messages=[
        {"role": "user", "content": "Write a short poem about AI"}
    ],
    stream=True
)

for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end='', flush=True)
```

**cURL Example**:
```bash
curl -X POST http://localhost:8080/v1/responses/chat/completions \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "Count to 10"}],
    "stream": true
  }' \
  --no-buffer
```

### 4. Tool Calling with MCP Tools

The Response API automatically has access to 18+ built-in MCP tools:

```python
response = client.responses.chat.completions.create(
    model="gpt-4",
    messages=[
        {"role": "user", "content": "Search UniProt for information about hemoglobin"}
    ]
)

# The assistant will:
# 1. Recognize it needs the uniprot_search tool
# 2. Call the tool automatically
# 3. Incorporate results into response

print(response.choices[0].message.content)
```

**Available Built-in Tools**:
- `uniprot_search` - Protein database search
- `pubchem_search` - Chemical compound search
- `blast_search` - Sequence alignment
- `websearch` - Web search
- `csv_rag_tool` - CSV data analysis
- `alphafold_predict` - Protein structure prediction
- `execute_code` - Sandbox code execution
- `file_upload`, `file_read`, `file_write` - File operations
- And more...

### 5. Temperature and Sampling Control

```python
# Deterministic output (low temperature)
response = client.responses.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "What is 2+2?"}],
    temperature=0.0
)

# Creative output (high temperature)
response = client.responses.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "Write a creative story"}],
    temperature=1.5
)

# With top_p (nucleus sampling)
response = client.responses.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "Generate ideas"}],
    temperature=0.9,
    top_p=0.95
)
```

### 6. Max Tokens Control

```python
# Short response
response = client.responses.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "Explain gravity"}],
    max_tokens=100
)

# Long-form response
response = client.responses.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "Write a detailed essay on climate change"}],
    max_tokens=2000
)
```

## Scientific Workflows

### Example: Protein Research Pipeline

```python
# Step 1: Search for protein
response = client.responses.chat.completions.create(
    model="gpt-4",
    messages=[
        {"role": "system", "content": "You are a bioinformatics assistant with access to protein databases and analysis tools."},
        {"role": "user", "content": "Find information about human insulin and analyze its structure"}
    ]
)

# The assistant will:
# 1. Call uniprot_search to find human insulin
# 2. Extract the sequence
# 3. Optionally call alphafold_predict for structure prediction
# 4. Provide comprehensive analysis

print(response.choices[0].message.content)
```

### Example: Data Analysis with CSV RAG

```python
# Step 1: Upload CSV file
with open("experimental_data.csv", "rb") as f:
    file_response = client.files.create(file=f, purpose="assistants")
    file_id = file_response.id

# Step 2: Analyze with RAG tool
response = client.responses.chat.completions.create(
    model="gpt-4",
    messages=[
        {"role": "user", "content": f"Analyze the data in file {file_id}. What are the main trends?"}
    ],
    mcp_session_id=str(uuid.uuid4())
)

print(response.choices[0].message.content)
```

### Example: Code Execution in Sandbox

```python
response = client.responses.chat.completions.create(
    model="gpt-4",
    messages=[
        {"role": "user", "content": """
Write and execute Python code to:
1. Generate 1000 random numbers from a normal distribution
2. Calculate mean and standard deviation
3. Create a histogram
        """}
    ],
    mcp_session_id=str(uuid.uuid4())  # Isolated sandbox session
)

# The assistant will:
# 1. Write Python code
# 2. Execute it in sandbox_mcp_server
# 3. Return results and visualizations

print(response.choices[0].message.content)
```

## Multi-Agent Orchestration

Leverage multi-agent capabilities for complex tasks:

```python
response = client.responses.chat.completions.create(
    model="gpt-4",
    messages=[
        {"role": "system", "content": "You can delegate tasks to specialist agents when needed."},
        {"role": "user", "content": """
I need help with a drug discovery project:
1. Find information about target protein EGFR
2. Search PubChem for known inhibitors
3. Analyze their chemical properties
4. Generate a summary report
        """}
    ]
)

# The system will:
# 1. Create a multi-agent session
# 2. Assign tasks to specialist agents (chemist, data analyst)
# 3. Coordinate their work
# 4. Synthesize results

print(response.choices[0].message.content)
```

## Error Handling

### Python Error Handling

```python
from openai import OpenAI, APIError, AuthenticationError, RateLimitError

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key=os.getenv("KEYCLOAK_TOKEN")
)

try:
    response = client.responses.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": "Hello"}]
    )
    print(response.choices[0].message.content)

except AuthenticationError as e:
    print(f"Authentication failed: {e}")
    print("Please obtain a fresh Keycloak token")

except RateLimitError as e:
    print(f"Rate limit exceeded: {e}")
    print("Please wait before retrying")

except APIError as e:
    print(f"API error occurred: {e}")
    print(f"Status code: {e.status_code}")
    print(f"Error type: {e.type}")
```

### Common Error Responses

**401 Unauthorized**:
```json
{
  "error": {
    "message": "Invalid authentication credentials",
    "type": "authentication_error",
    "code": "invalid_token"
  }
}
```

**403 Forbidden**:
```json
{
  "error": {
    "message": "User lacks required permissions",
    "type": "permission_denied",
    "code": "insufficient_permissions"
  }
}
```

**400 Bad Request**:
```json
{
  "error": {
    "message": "Missing required parameter: messages",
    "type": "invalid_request_error",
    "param": "messages"
  }
}
```

## Performance Optimization

### 1. Connection Pooling

```python
from openai import OpenAI
import httpx

# Create client with connection pooling
http_client = httpx.Client(
    limits=httpx.Limits(
        max_keepalive_connections=20,
        max_connections=100
    )
)

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key=os.getenv("KEYCLOAK_TOKEN"),
    http_client=http_client
)
```

### 2. Async Requests

```python
from openai import AsyncOpenAI
import asyncio

async def main():
    client = AsyncOpenAI(
        base_url="http://localhost:8080/v1",
        api_key=os.getenv("KEYCLOAK_TOKEN")
    )

    # Run multiple requests concurrently
    tasks = [
        client.responses.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": f"Question {i}"}]
        )
        for i in range(5)
    ]

    responses = await asyncio.gather(*tasks)

    for response in responses:
        print(response.choices[0].message.content)

asyncio.run(main())
```

### 3. Batch Processing

```python
questions = [
    "What is photosynthesis?",
    "Explain DNA replication",
    "What are enzymes?",
    "Describe cell division"
]

# Process in batch
messages_batch = [
    [{"role": "user", "content": q}]
    for q in questions
]

responses = []
for messages in messages_batch:
    response = client.responses.chat.completions.create(
        model="gpt-4",
        messages=messages,
        max_tokens=200
    )
    responses.append(response.choices[0].message.content)

for i, answer in enumerate(responses):
    print(f"Q{i+1}: {questions[i]}")
    print(f"A{i+1}: {answer}\n")
```

## Next Steps

- [Knowledge Base Operations](./knowledge-bases.md)
- [Assistants API (Deprecated)](./assistants-api.md)
- [MCP Protocol Usage](./mcp-protocol.md)
- [API Reference](../openapi.json)
