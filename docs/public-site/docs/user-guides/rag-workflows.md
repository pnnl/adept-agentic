# RAG Workflows

Retrieval-Augmented Generation (RAG) in ADEPT enables agents to answer questions grounded in your uploaded documents. The platform uses a ChromaDB/pgvector hybrid vector store with visibility-scoped collections to control access.

## Overview

The RAG pipeline follows three stages:

1. **Upload** -- Files are ingested into session-scoped storage.
2. **Process** -- Documents are chunked, embedded, and indexed into a vector collection.
3. **Query** -- The agent retrieves relevant chunks and uses an LLM to synthesize an answer.

## Uploading Files

Upload files via the REST API or through the agent's natural language interface:

```bash
# REST API upload
curl -X POST https://your-adept-server.example.com/v1/files \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@dataset.csv" \
  -F "purpose=assistants"
```

Supported file types include CSV, PDF, and plain text files. Each upload is stored in a session-scoped directory to ensure isolation between users.

## Processing Types

Once uploaded, files must be processed before they can be queried. The `processing_type` parameter controls how files are handled:

| Processing Type | Description | Use Case |
|-----------------|-------------|----------|
| `auto` | Automatic detection based on file extension | General-purpose ingestion |
| `rag` | Full RAG pipeline (chunk, embed, index) | Document Q&A |
| `sql` | Convert to SQL-queryable tables | Structured data analysis |
| `dataframe` | Load as pandas DataFrame | Statistical operations |
| `text` | Raw text extraction | Simple text retrieval |

## Creating RAG Indexes

Use `create_rag_index_from_folder` to index multiple files at once:

```text
Agent, create a RAG index from my uploaded folder with user-level visibility.
```

The tool accepts a `timeout_seconds` parameter for large batch operations and a `visibility` parameter to control who can access the resulting collection.

## Querying Documents

The query tool retrieves relevant document chunks via vector similarity search, then passes them to an LLM for answer generation:

```text
Agent, what are the key findings in my uploaded research paper?
```

The LLM synthesizes answers grounded in retrieved context, citing relevant passages when possible.

## Visibility Scoping

Collections are scoped using a naming convention that controls access:

| Scope | Collection Naming | Access |
|-------|-------------------|--------|
| **Session** (default) | `s_{session_id[:12]}_{name}` | Current MCP session only |
| **User** | `u_{owner_id[:12]}_{name}` | Persists across sessions for the owning user |
| **World** | `w_{name}` | Accessible to any authenticated user |

!!! tip "Choosing Visibility"
    Use `session` for ephemeral exploration, `user` for personal knowledge bases that persist across conversations, and `world` for shared organizational resources.

## Batch Operations

Two batch tools enable large-scale document processing:

### `process_files_batch`

Processes multiple files in parallel with configurable concurrency:

- Accepts a list of file IDs and a `processing_type`
- Dispatches to the appropriate processing pipeline based on type
- Uses per-session locking to prevent concurrent metadata corruption

### `create_rag_index_from_folder`

Creates a unified RAG index from all files in a session folder:

- Processes all files in the specified directory
- Embeds and indexes into a single named collection
- Supports `visibility` and `timeout_seconds` parameters

!!! note "Concurrency Safety"
    Both batch operations use per-session `asyncio.Lock` to prevent race conditions when multiple files update session metadata simultaneously.

## Vector Store Backend

ADEPT uses ChromaDB as the primary vector store:

- **Production**: `HttpClient` connecting to a dedicated ChromaDB service
- **Fallback**: `PersistentClient` for local development without a ChromaDB server
- **Embeddings**: Configurable via `EMBEDDING_DEFAULT_MODEL` environment variable

The `BackendFactory` selects the appropriate backend based on the `backend_type` configuration parameter.
