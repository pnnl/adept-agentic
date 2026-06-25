# Comprehensive RAG Workflow User Guide

> **⚠️ IMPORTANT NOTICE: The Assistants API is deprecated. This guide uses the Response API (/v1/responses/chat/completions) exclusively.**

## Table of Contents
1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [RAG Workflow via CLI](#rag-workflow-via-cli)
4. [RAG Workflow via Python SDK](#rag-workflow-via-python-sdk)
5. [RAG Workflow via Streamlit](#rag-workflow-via-streamlit)
6. [RAG Workflow via JupyterLab](#rag-workflow-via-jupyterlab)
7. [RAG Workflow via RAGFlow UI](#rag-workflow-via-ragflow-ui)
8. [Embedding Model Configuration](#embedding-model-configuration)
9. [Validation and Testing](#validation-and-testing)
10. [Architecture Reference](#architecture-reference)
11. [Troubleshooting](#troubleshooting)

## Overview

The ADEPT framework provides five different user interfaces for interacting with RAG (Retrieval-Augmented Generation) capabilities using the modern Response API. Each interface offers unique advantages:

- **CLI**: Command-line interface for automation and scripting
- **Python SDK**: Programmatic access for custom applications
- **Streamlit**: Web-based conversational interface
- **JupyterLab**: Interactive notebook environment for data science
- **RAGFlow UI**: Visual knowledge base management with enterprise features

All interfaces share the same backend infrastructure:
- Document processing through MCP tool servers
- Vector storage in ChromaDB or RAGFlow
- Hybrid search combining dense and sparse retrieval
- Session isolation for multi-tenancy
- Keycloak-based authentication

## Prerequisites

### System Requirements
- Docker and Docker Compose installed
- 16GB RAM minimum (32GB recommended)
- 50GB available disk space
- Network access to ports 80, 443, 8503, 8888, 9080, 9380

### Authentication Setup
All interfaces use Keycloak SSO. Default credentials:
- **Admin User**: `admin` / `admin`
- **Notebook User**: `notebook` / `notebook-password`
- **Test User**: `test_user` / `test123`
- **Paul User**: `paul` / `Paul123!`

### Enable RAGFlow (IMPORTANT)
```bash
# Edit .env file to enable RAGFlow
echo "ENABLE_RAGFLOW=true" >> .env

# Configure token limits to prevent errors
echo "RAGFLOW_MAX_CHUNK_SIZE=500" >> .env
echo "RAGFLOW_CHUNK_OVERLAP=50" >> .env
```

### Service Status Verification
```bash
# Check all services are running
make status

# Verify RAGFlow is enabled and running
grep ENABLE_RAGFLOW .env  # Should show: ENABLE_RAGFLOW=true
grep RAGFLOW_UI_ENABLED .env  # Should show: RAGFLOW_UI_ENABLED=true
```

## RAG Workflow via CLI

### Installation
```bash
# Install the CLI SDK
pip install -e src/

# Or use Docker container
docker run --rm -it agentic-framework-deps-base:latest bash
```

### Basic RAG Workflow (Modern Response API)
```bash
# 1. Authenticate
export KEYCLOAK_URL=http://keycloak:8180
export AGENT_GATEWAY_URL=https://api.agentic.local
agentic-cli auth login --username notebook --password notebook-password

# 2. Upload document for RAG processing
agentic-cli files upload ./documents/research_paper.pdf --purpose file-extract

# 3. Process document and create RAG index using Response API
agentic-cli chat --query "Process the uploaded file file_abc123 using ProcessUploadedFile tool to create a searchable RAG index"

# 4. Query the RAG index using Response API
agentic-cli chat --query "Using the RAG index, summarize the key findings from the research paper"

# 5. Advanced RAG query with specific context
agentic-cli chat --query "Query the RAG index for information about methodology and results sections"
```

### Advanced Features (Response API)
```bash
# Use MCP tools directly with Response API
agentic-cli chat --query "Process file_abc123 with ProcessUploadedFile tool and create a RAG index"

# Multi-file RAG index creation
agentic-cli chat --query "Create a unified RAG index from files: file_1, file_2, file_3 using CreateRAGIndex tool"

# Query specific index with semantic search
agentic-cli chat --query "Use QueryRAGIndex tool on index_xyz to find information about machine learning techniques"

# Chain multiple RAG operations
agentic-cli chat --query "First process file_abc123, then create a RAG index, and finally query it for 'neural networks'"
```

**Reference**: `tests/e2e/test_cli_rag_e2e_workflow.py`

## RAG Workflow via Python SDK

### Setup
```python
# Using the modern Response API - no Assistants API models needed
from agentic_framework_sdk import OpenAI
import httpx

# Option 1: Using SDK with OpenAI client
# First get JWT token
async with httpx.AsyncClient(verify=False) as http_client:
    token_url = "http://keycloak:8180/realms/agentic/protocol/openid-connect/token"
    auth_data = {
        "grant_type": "password",
        "client_id": "agentic-framework",
        "username": "notebook",
        "password": "notebook-password"
    }
    response = await http_client.post(token_url, data=auth_data)
    token = response.json()["access_token"]

# Create OpenAI client with JWT
client = OpenAI(
    api_key=token,
    base_url="https://api.agentic.local",
    timeout=60.0
)

# Option 2: Direct HTTP client for full control
headers = {'Authorization': f'Bearer {token}'}
```

### Document Processing (Modern Response API)
```python
# Upload document for RAG processing
with open("research_paper.pdf", "rb") as f:
    file = await client.files.create(
        file=f,
        purpose="file-extract"  # Use file-extract for RAG processing
    )
print(f"Uploaded: {file.id}")

# Process document using Response API to create RAG index
response = await client.responses.chat.completions.create(
    model="gpt-4",
    messages=[
        {
            "role": "user",
            "content": f"Process file {file.id} using ProcessUploadedFile tool to create a searchable RAG index"
        }
    ],
    stream=False
)
print(f"RAG Index Created: {response.choices[0].message.content}")
```

### Querying with Response API
```python
# Query the RAG index using Response API
response = await client.responses.chat.completions.create(
    model="gpt-4",
    messages=[
        {
            "role": "user",
            "content": "What are the main conclusions of this research? Use the RAG index to provide detailed answers."
        }
    ],
    stream=False
)

# Get the answer
answer = response.choices[0].message.content
print(f"Answer: {answer}")

# Streaming responses for real-time output
stream_response = await client.responses.chat.completions.create(
    model="gpt-4",
    messages=[
        {
            "role": "user",
            "content": "Provide a detailed summary of the methodology section from the RAG index"
        }
    ],
    stream=True
)

# Process streaming response
async for chunk in stream_response:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

### MCP Tool Integration with Response API
```python
# Direct MCP tool usage via Response API with explicit tool calls
response = await client.responses.chat.completions.create(
    model="gpt-4",
    messages=[
        {
            "role": "user",
            "content": "Process the uploaded file and create a comprehensive RAG index"
        }
    ],
    tools=[
        {
            "type": "function",
            "function": {
                "name": "ProcessUploadedFile",
                "description": "Process uploaded file for RAG indexing",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string"},
                        "auto_detect_type": {"type": "boolean", "default": True}
                    },
                    "required": ["file_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "CreateRAGIndex",
                "description": "Create searchable RAG index from processed files",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_ids": {"type": "array", "items": {"type": "string"}},
                        "index_name": {"type": "string"},
                        "chunk_size": {"type": "integer", "default": 1000},
                        "chunk_overlap": {"type": "integer", "default": 200}
                    },
                    "required": ["file_ids"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "QueryRAGIndex",
                "description": "Query the RAG index with semantic search",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "index_id": {"type": "string"},
                        "query": {"type": "string"},
                        "top_k": {"type": "integer", "default": 5}
                    },
                    "required": ["index_id", "query"]
                }
            }
        }
    ],
    tool_choice="auto",  # Let the model decide which tools to use
    stream=False
)

# Process tool calls if any
if response.choices[0].message.tool_calls:
    for tool_call in response.choices[0].message.tool_calls:
        print(f"Tool called: {tool_call.function.name}")
        print(f"Arguments: {tool_call.function.arguments}")
```

**Reference**: `src/agentic_framework_sdk/client.py`

## RAG Workflow via Streamlit

### Access
Navigate to: http://localhost:8503

### Workflow Steps

1. **Login**
   - Enter username: `notebook`
   - Enter password: `notebook-password`
   - Click "Login"

2. **Upload Documents**
   - Click "📁 File Upload" in sidebar
   - Select document(s) to upload
   - Choose "file-extract" as purpose
   - Click "Upload"

3. **Process with RAG Tools**
   - Go to "💬 Chat" tab
   - Type: "Process the uploaded file with ProcessUploadedFile tool"
   - System automatically creates RAG index
   - Wait for confirmation message

4. **Query Documents**
   - Type your query: "Summarize the uploaded document"
   - System uses QueryFileContent tool automatically
   - Results retrieved from RAG index
   - Press Enter

5. **Advanced RAG Features**
   - Use "@" to reference specific files
   - Enable "Show tool calls" to see RAG operations
   - Download processed results

### Session Management
- Each conversation maintains isolated RAG indexes
- Session ID shown in sidebar
- Files organized by `mcp_session_id`

**Reference**: `src/agentic_framework_pkg/streamlit_app_v2/`

## RAG Workflow via JupyterLab

### Access
Get the token URL:
```bash
docker compose logs jupyterlab | grep token
# Navigate to: http://127.0.0.1:8888/lab?token=<token>
```

### Notebook Setup
```python
# Cell 1: Setup
import sys
sys.path.append('/app/src')

from agentic_framework_sdk.client import AgenticFrameworkClient
import asyncio
import pandas as pd

# Cell 2: Initialize
client = AgenticFrameworkClient(
    base_url="http://agent_gateway:8081/v1",
    username="notebook",
    password="notebook-password",
    keycloak_url="http://keycloak:8180"
)

await client.authenticate()
```

### Document Analysis Workflow
```python
# Cell 3: Upload and process documents using Response API
files = []
for doc in ['paper1.pdf', 'paper2.pdf', 'paper3.pdf']:
    with open(f'/shared/{doc}', 'rb') as f:
        file = await client.files.create(file=f, purpose="file-extract")
        files.append(file.id)
        print(f"Uploaded: {file.filename} -> {file.id}")

# Cell 4: Process files to create RAG indexes using Response API
for file_id in files:
    response = await client.responses.chat.completions.create(
        model="gpt-4",
        messages=[
            {
                "role": "system",
                "content": "You are an expert at processing research papers for RAG indexing."
            },
            {
                "role": "user",
                "content": f"Process file {file_id} using ProcessUploadedFile tool to create a searchable RAG index"
            }
        ],
        stream=False
    )
    print(f"Processed and indexed: {file_id}")

# Cell 5: Comparative analysis using Response API
queries = [
    "What methodologies are used across all papers?",
    "Compare the findings between paper1 and paper2",
    "What are the common themes across all documents?"
]

results = {}
for query in queries:
    # Query using Response API with RAG context
    response = await client.responses.chat.completions.create(
        model="gpt-4",
        messages=[
            {
                "role": "system",
                "content": "You are an expert at synthesizing research from multiple papers. Use the RAG indexes to find relevant information."
            },
            {
                "role": "user",
                "content": f"Using the RAG indexes from files {files}, answer: {query}"
            }
        ],
        stream=False
    )

    # Extract answer from response
    results[query] = response.choices[0].message.content

# Cell 6: Visualize results
df = pd.DataFrame(results.items(), columns=['Query', 'Response'])
display(df)
```

### Data Processing Pipeline
```python
# Cell 7: CSV to RAG pipeline using Response API
import json

# Upload CSV
with open('/shared/dataset.csv', 'rb') as f:
    csv_file = await client.files.create(file=f, purpose="file-extract")

# Process with MCP tools using Response API
response = await client.responses.chat.completions.create(
    model="gpt-4",
    messages=[
        {
            "role": "user",
            "content": f"""Process the CSV file {csv_file.id} using these steps:
            1. Use ProcessUploadedFile to load it
            2. Create a RAG index from the data
            3. Generate summary statistics
            """
        }
    ],
    stream=False
)
```

**Reference**: `notebooks/` directory

## RAG Workflow via RAGFlow UI

### Access
Navigate to: http://localhost:9382

### Authentication
RAGFlow UI uses Keycloak SSO:
1. Click "Login with SSO"
2. Redirected to Keycloak
3. Enter credentials: `notebook` / `notebook-password`
4. Automatically returned to RAGFlow

### Knowledge Base Management

1. **Create Knowledge Base**
   - Click "Knowledge Bases" → "New"
   - Name: "Research Papers"
   - Type: "Standard"
   - Embedding Model: "BAAI/bge-small-en-v1.5"
   - Click "Create"

2. **Upload Documents**
   - Open knowledge base
   - Click "Upload Files"
   - Select multiple PDFs/DOCX/TXT files
   - Configure chunking:
     - Method: "Semantic"
     - Size: 512 tokens
     - Overlap: 50 tokens
   - Click "Process"

3. **Monitor Processing**
   - View processing status
   - Check chunk statistics
   - Preview extracted text
   - Verify embeddings generated

4. **Configure Retrieval**
   - Go to "Settings" tab
   - Hybrid Search: Enable
   - Dense Weight: 0.7
   - Sparse Weight: 0.3
   - Top-K: 10
   - Reranker: Enable

### Querying

1. **Interactive Query**
   - Go to "Chat" interface
   - Select knowledge base
   - Type question
   - View retrieved chunks
   - See relevance scores

2. **Batch Processing**
   - Go to "Batch Query"
   - Upload CSV with questions
   - Configure output format
   - Download results

3. **API Integration**
   ```python
   # RAGFlow API endpoint
   import requests

   response = requests.post(
       "http://localhost:9382/api/v1/query",
       headers={"Authorization": f"Bearer {token}"},
       json={
           "kb_id": "kb_123",
           "query": "What are the findings?",
           "top_k": 5
       }
   )
   ```

### Advanced Features

1. **Dataset Organization**
   - Create folders for topics
   - Tag documents
   - Version control
   - Access control per dataset

2. **Analytics Dashboard**
   - Query performance metrics
   - Usage statistics
   - Popular queries
   - Chunk utilization

3. **Session Synchronization**
   - Automatic sync with Streamlit sessions
   - Shared file access via `/shared_uploads`
   - Unified `mcp_session_id` tracking

**Reference**: `docs/phase2-fixes/RAGFLOW_UI_DEPLOYMENT_GUIDE.md`

## Embedding Model Configuration

### Understanding Embedding Models

RAGFlow and ADEPT use **separate embedding models** - they do NOT inherit from each other:

| Component | Environment Variable | Default Model | Provider |
|-----------|---------------------|---------------|----------|
| **ADEPT Core** | `EMBEDDING_DEFAULT_MODEL` | `all-MiniLM-L6-v2` | Local (sentence-transformers) |
| **RAGFlow** | `RAGFLOW_EMBEDDING_MODEL` | `text-embedding-ada-002` | OpenAI API |
| **ChromaDB** | `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Local (sentence-transformers) |

### Configuration Details

#### ADEPT Framework Embeddings
```bash
# In .env file - for ADEPT's ChromaDB backend
EMBEDDING_DEFAULT_MODEL="all-MiniLM-L6-v2"  # Free, local model
# Or use OpenAI:
# EMBEDDING_DEFAULT_MODEL="text-embedding-3-large"
# EMBEDDING_OPENAI_API_KEY="sk-..."
```

- **Default**: Uses free, local sentence-transformers model
- **No API costs**: Runs entirely on your hardware
- **Good performance**: Suitable for most use cases
- **Configuration**: Set in `.env` file

#### RAGFlow Embeddings
```bash
# In .env file - for RAGFlow backend
RAGFLOW_EMBEDDING_MODEL="text-embedding-ada-002"
RAGFLOW_EMBEDDING_DIMENSION="1536"

# Or use newer model:
# RAGFLOW_EMBEDDING_MODEL="text-embedding-3-large"
# RAGFLOW_EMBEDDING_DIMENSION="3072"
```

- **Default**: Uses OpenAI's embedding API
- **Requires API key**: Costs per token processed
- **Enterprise-grade**: Better quality for production
- **Separate from ADEPT**: Completely independent configuration

### Choosing Your Strategy

#### Option 1: Cost-Effective (Local Embeddings)
```bash
# Use local models for both systems
EMBEDDING_DEFAULT_MODEL="all-MiniLM-L6-v2"
RAGFLOW_EMBEDDING_MODEL="all-MiniLM-L6-v2"
KB_BACKEND_STRATEGY="chromadb_only"
```

#### Option 2: Production Quality (OpenAI)
```bash
# Use OpenAI for better quality
EMBEDDING_DEFAULT_MODEL="text-embedding-3-large"
RAGFLOW_EMBEDDING_MODEL="text-embedding-3-large"
RAGFLOW_EMBEDDING_DIMENSION="3072"
KB_BACKEND_STRATEGY="ragflow_only"
```

#### Option 3: Hybrid Approach
```bash
# ADEPT uses free local, RAGFlow uses premium
EMBEDDING_DEFAULT_MODEL="all-MiniLM-L6-v2"
RAGFLOW_EMBEDDING_MODEL="text-embedding-3-large"
KB_BACKEND_STRATEGY="auto"
```

## Validation and Testing

### Available Validation Targets

The framework includes comprehensive validation for RAG workflows:

#### Core RAG Validation
```bash
# Test basic RAG tools (ChromaDB backend)
make validate-rag-tools

# Test file processing with RAG
make validate-file-processing-tools

# Test complete CLI RAG workflow (currently needs fixing)
make validate-cli-rag-e2e
```

#### RAGFlow-Specific Validation
```bash
# Test complete RAGFlow data lifecycle
# CLI SDK → NGINX → Gateway → Orchestration → RAGFlow
make validate-ragflow-data-lifecycle

# Test RAGFlow knowledge base workflow
make validate-ragflow-kb-workflow

# Run all RAGFlow tests
make validate-ragflow-data-lifecycle validate-ragflow-kb-workflow
```

#### Prerequisites for Testing
1. **Main ADEPT stack must be running**:
   ```bash
   make start
   make validate-service-health
   ```

2. **RAGFlow stack must be running** (if testing RAGFlow):
   ```bash
   make start-ragflow-backend
   make start-ragflow-api
   make start-ragflow-ui
   ```

3. **Verify services are accessible**:
   ```bash
   # Check ADEPT services
   curl http://localhost:8180/health  # Keycloak
   curl http://localhost:8081/health  # Agent Gateway

   # Check RAGFlow services
   curl http://localhost:9380/api/health  # RAGFlow API
   curl http://localhost:9382  # RAGFlow UI
   ```

### Test Coverage

| Test | Coverage | Status |
|------|----------|--------|
| `validate-rag-tools` | ChromaDB RAG operations | ✅ Working |
| `validate-file-processing-tools` | File → RAG pipeline | ✅ Working |
| `validate-cli-rag-e2e` | Full CLI workflow | ⚠️ Needs Response API conversion |
| `validate-ragflow-data-lifecycle` | RAGFlow integration | ✅ Implemented |
| `validate-ragflow-kb-workflow` | RAGFlow KB operations | ✅ Implemented |

### Running Tests in Docker

All tests run in Docker containers for consistency:
```bash
# Tests use this base command internally
docker run --rm \
  --network=agentic_framework_network \
  -v "$(pwd)/src":/app/src \
  -v "$(pwd)/tests":/app/tests \
  agentic-framework-deps-base:latest \
  pytest tests/e2e/test_name.py -v
```

## Architecture Reference

### Data Flow
```
User Interface (CLI/SDK/Streamlit/Jupyter/RAGFlow)
       ↓
NGINX Proxy (SSL termination, routing)
       ↓
Agent Gateway (JWT validation, CORS)
       ↓
Orchestration Service (LangGraph, state management)
       ↓
MCP Tool Servers (document processing, RAG operations)
       ↓
Storage Layer (PostgreSQL, ChromaDB/RAGFlow, shared volumes)
```

### File Organization
```
/shared_uploads/
├── {mcp_session_id}/
│   ├── uploaded_files/
│   ├── processed_data/
│   └── rag_indexes/
```

### Key Components
- **ProcessUploadedFile**: Detects file type, extracts text
- **create_rag_index**: Builds vector index from documents
- **query_rag_index**: Semantic search with hybrid retrieval
- **list_rag_indexes**: Shows available indexes per session

**Reference**: `docs/phase2-fixes/IMPLEMENTATION_STATUS_CHECKPOINT.md`

## Troubleshooting

### Common Issues

1. **Authentication Failures**
   ```bash
   # Check Keycloak status
   docker logs keycloak

   # Verify credentials
   make validate-credentials

   # Fix credential drift
   make fix-credentials
   ```

2. **File Upload Errors**
   ```bash
   # Check permissions
   ls -la /shared_uploads/

   # Verify session directory
   docker exec mcp_server ls -la /app/data/uploaded_files/
   ```

3. **RAG Index Not Found**
   ```bash
   # List indexes for session
   docker exec mcp_server python -c "
   from tools.csv_rag_tool import list_rag_indexes
   print(list_rag_indexes(mcp_session_id='your_session_id'))
   "
   ```

4. **Slow Query Performance**
   - Check vector DB status: `docker logs vector_db_server`
   - Monitor chunk size and overlap settings
   - Consider enabling GPU acceleration

5. **Session Isolation Issues**
   - Verify `mcp_session_id` propagation
   - Check file permissions: should be `1000:1000`
   - Review session directory structure

### Performance Optimization

1. **Batch Processing**
   ```python
   # Process multiple files in parallel
   file_ids = [file1.id, file2.id, file3.id]
   await create_rag_index(file_ids=file_ids, index_name="batch_index")
   ```

2. **Caching**
   - Enable Redis caching in `.env`
   - Set appropriate TTLs for indexes
   - Use persistent vector stores

3. **Resource Allocation**
   ```yaml
   # docker-compose.override.yaml
   services:
     mcp_server:
       deploy:
         resources:
           limits:
             memory: 4G
             cpus: '2'
   ```

### Debug Mode
```bash
# Enable debug logging
export DEBUG=true
export LOG_LEVEL=DEBUG

# View detailed logs
docker compose logs -f mcp_server | grep RAG

# Monitor tool calls
make validate-mcp-tools-discovery
```

## Bulk Document Processing with ZIP Files

### Overview
The framework now includes comprehensive support for bulk document processing through ZIP archives. This feature addresses the token limit issues and enables efficient processing of large document collections.

### ZIP Processing Features
- **Automatic extraction** to session-isolated directories
- **File type detection** and filtering
- **Adaptive chunking** based on document size
- **Batch processing** for efficiency
- **Nested ZIP support** (configurable)
- **Token limit validation** before processing

### Using the ZIP Processor Tool

#### Via Python SDK
```python
from agentic_framework_sdk import AgenticFrameworkSDK

sdk = AgenticFrameworkSDK()
assistant = await sdk.create_assistant(
    name="Document Processor",
    tools=["process_zip_archive"]
)

# Upload ZIP file
file = await sdk.upload_file("adept_block_diagrams.zip")

# Process with automatic chunking
result = await assistant.run_tool(
    "process_zip_archive",
    {
        "file_id": file.id,
        "kb_id": "architecture_docs",
        "batch_size": 5,
        "file_type_filter": [".png", ".pdf", ".md"],
        "auto_create_kb": True
    }
)

print(f"Processed {result['statistics']['processed']} files")
print(f"Failed: {result['statistics']['failed']}")
print(f"Skipped: {result['statistics']['skipped']}")
```

#### Via CLI
```bash
# Upload and process ZIP
agentic-framework file upload adept_block_diagrams.zip
agentic-framework rag process-zip \
  --file-id <file_id> \
  --kb-id architecture_docs \
  --batch-size 10 \
  --filter ".png,.pdf"
```

#### Via Streamlit
1. Navigate to "Document Processing" tab
2. Click "Upload ZIP Archive"
3. Select your ZIP file
4. Configure processing options:
   - Knowledge base name
   - File type filters
   - Batch size
5. Click "Process Archive"
6. Monitor progress in real-time

### Handling Large Documents (Token Limit Prevention)

#### Document Size Validation
```python
from agentic_framework_pkg.core.document_size_validator import DocumentSizeValidator

validator = DocumentSizeValidator(max_tokens=200_000)

# Check single document
can_process, error_msg, info = validator.can_process_document("large_doc.pdf")
if not can_process:
    print(f"Document too large: {error_msg}")
    print(f"Recommended strategy: {info['recommendation']}")

# Get processing strategy
strategy = validator.get_processing_strategy("large_doc.pdf")
print(f"Strategy: {strategy['strategy']}")
print(f"Chunk size: {strategy['chunk_size']}")
```

#### Batch Validation
```python
# Validate multiple files before processing
files = ["doc1.pdf", "doc2.txt", "doc3.docx"]
results = validator.validate_batch(files)

print(f"Can process: {len(results['can_process'])} files")
print(f"Cannot process: {len(results['cannot_process'])} files")
print(f"Total tokens: {results['total_estimated_tokens']:,}")

for rec in results['recommendations']:
    print(f"Recommendation: {rec}")
```

### Adaptive Chunking Configuration

The system automatically adjusts chunk sizes based on document size:

| Document Size | Chunk Size | Overlap | Strategy |
|--------------|------------|---------|----------|
| < 1MB | 800 tokens | 150 | Normal processing |
| 1-5MB | 512 tokens | 100 | Moderate chunking |
| 5-10MB | 384 tokens | 75 | Aggressive chunking |
| > 10MB | 256 tokens | 50 | Maximum chunking |

Override with environment variables:
```bash
RAGFLOW_AUTO_CHUNK_ADJUSTMENT=true
RAGFLOW_MAX_CHUNK_SIZE=512
RAGFLOW_CHUNK_OVERLAP=100
RAGFLOW_MAX_CHUNKS_PER_DOCUMENT=500
```

### Example: Processing Research Papers Archive

```python
import asyncio
from agentic_framework_sdk import AgenticFrameworkSDK

async def process_research_archive():
    sdk = AgenticFrameworkSDK()

    # Upload research papers ZIP
    file = await sdk.upload_file("research_papers_2024.zip")

    # Create assistant with RAG tools
    assistant = await sdk.create_assistant(
        name="Research Assistant",
        tools=["process_zip_archive", "query_rag_index"]
    )

    # Process ZIP with specific settings
    process_result = await assistant.run_tool(
        "process_zip_archive",
        {
            "file_id": file.id,
            "kb_id": "research_2024",
            "batch_size": 3,  # Process 3 files at a time
            "file_type_filter": [".pdf", ".txt", ".md"],
            "process_nested_zips": True,  # Handle nested archives
            "auto_create_kb": True
        }
    )

    # Check results
    stats = process_result['statistics']
    print(f"Successfully processed {stats['processed']} documents")
    print(f"Total size: {stats['total_size_bytes'] / 1_000_000:.2f} MB")

    # Query the processed documents
    query_result = await assistant.run_tool(
        "query_rag_index",
        {
            "index_name": "research_2024",
            "query": "What are the latest findings on protein folding?",
            "top_k": 5
        }
    )

    return query_result

# Run the processing
result = asyncio.run(process_research_archive())
```

### Example: Handling Image Archives (PNG/JPG)

```python
async def process_diagram_archive():
    sdk = AgenticFrameworkSDK()

    # Special handling for image archives
    file = await sdk.upload_file("architecture_diagrams.zip")

    result = await sdk.run_tool(
        "process_zip_archive",
        {
            "file_id": file.id,
            "kb_id": "architecture_visuals",
            "file_type_filter": [".png", ".jpg", ".jpeg"],
            "batch_size": 5
        }
    )

    # Images are processed with:
    # - OCR for text extraction
    # - Vision model for descriptions
    # - Single chunk per image (no overlap)

    return result
```

### Troubleshooting ZIP Processing

#### Issue: Token Limit Exceeded
```bash
# Error: "Document too large (1,347,234 tokens). Budget: 200,000"

# Solution 1: Reduce chunk sizes
export RAGFLOW_MAX_CHUNK_SIZE=256
export RAGFLOW_CHUNK_OVERLAP=50

# Solution 2: Process files individually
agentic-framework rag process-zip \
  --file-id <id> \
  --batch-size 1 \
  --max-file-size 5MB
```

#### Issue: ZIP Extraction Fails
```bash
# Check disk space
df -h /tmp

# Check permissions
ls -la /tmp/zip_extract/

# Clean up old extractions
rm -rf /tmp/zip_extract/*
```

#### Issue: Slow Processing
```python
# Optimize batch size based on file types
if all_pdfs:
    batch_size = 3  # PDFs are memory-intensive
elif all_text:
    batch_size = 10  # Text files are lightweight
else:
    batch_size = 5  # Mixed content
```

### Best Practices

1. **Pre-validate archives** before processing:
   ```python
   # Check total size
   total_size = sum(f.file_size for f in zip_ref.filelist)
   if total_size > 100_000_000:  # 100MB
       print("Warning: Large archive, consider splitting")
   ```

2. **Use file type filters** to avoid processing unnecessary files:
   ```python
   # Only process documents, skip images and executables
   file_type_filter = [".pdf", ".docx", ".txt", ".md"]
   ```

3. **Monitor progress** for large archives:
   ```python
   # Check processing status
   status = await sdk.get_job_status(job_id)
   print(f"Progress: {status['processed']}/{status['total']}")
   ```

4. **Clean up** after processing:
   ```python
   # Remove extracted files after ingestion
   import shutil
   shutil.rmtree(f"/tmp/zip_extract/{session_id}")
   ```

## Appendix

### Environment Variables
- `ENABLE_RAGFLOW`: Enable RAGFlow backend (default: true)
- `RAGFLOW_UI_ENABLED`: Enable visual UI (default: true)
- `CHROMADB_FALLBACK`: Use ChromaDB if RAGFlow unavailable
- `RAG_CHUNK_SIZE`: Default chunk size (512)
- `RAG_CHUNK_OVERLAP`: Default overlap (50)

### File Format Support
- **Documents**: PDF, DOCX, TXT, MD, RTF
- **Data**: CSV, JSON, XLSX, Parquet
- **Code**: Python, JavaScript, Java, C++
- **Images**: PNG, JPEG (with OCR via RAGFlow)

### Security Considerations
- All files isolated by `mcp_session_id`
- JWT tokens expire after 30 minutes
- File access controlled by user groups
- Sandbox execution for code processing

### Related Documentation
- [RAGFlow Integration Status](../phase2-fixes/RAGFLOW_INTEGRATION_STATUS.md)
- [File Processing Enhancement](../phase2-fixes/FILE_TYPE_DETECTION_ENHANCEMENT.md)
- [Knowledge Base Design](../phase2-fixes/KNOWLEDGE_BASE_MANAGEMENT_TIER2_DESIGN.md)
- [E2E Test Implementation](../../tests/e2e/test_cli_rag_e2e_workflow.py)

---

Last Updated: November 13, 2025
Version: 1.0.0