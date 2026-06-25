# Knowledge Base Operations

## Overview

The ADEPT Agentic Framework provides comprehensive RAG (Retrieval-Augmented Generation) capabilities through Knowledge Base APIs. Knowledge bases enable semantic search over documents, PDFs, and structured data.

**Supported Backends**:
- **RAGFlow** (v0.8.0) - Advanced document processing with MySQL backend
- **ChromaDB** - Lightweight vector database for embeddings
- **Auto** - Automatic backend selection based on content type

## Quick Start

### 1. Create a Knowledge Base

```bash
curl -X POST http://localhost:8080/v1/knowledge_bases/create \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Research Papers",
    "description": "Collection of scientific research papers",
    "backend_type": "ragflow",
    "chunk_size": 1000,
    "chunk_overlap": 200
  }'
```

**Response**:
```json
{
  "kb_id": "kb_abc123",
  "name": "Research Papers",
  "description": "Collection of scientific research papers",
  "backend_type": "ragflow",
  "created_at": "2026-01-07T10:30:00Z",
  "document_count": 0,
  "chunk_size": 1000,
  "chunk_overlap": 200
}
```

### 2. Ingest Documents

```bash
# Upload PDF document
curl -X POST http://localhost:8080/v1/knowledge_bases/ingest \
  -H "Authorization: Bearer ${TOKEN}" \
  -F "kb_id=kb_abc123" \
  -F "file=@research_paper.pdf"
```

**Response**:
```json
{
  "kb_id": "kb_abc123",
  "document_id": "doc_xyz789",
  "filename": "research_paper.pdf",
  "status": "processing",
  "chunks_created": 0,
  "message": "Document queued for ingestion"
}
```

### 3. Query the Knowledge Base

```bash
curl -X POST http://localhost:8080/v1/knowledge_bases/query/kb_abc123 \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What are the key findings about protein folding?",
    "top_k": 5,
    "score_threshold": 0.7
  }'
```

**Response**:
```json
{
  "results": [
    {
      "document_id": "doc_xyz789",
      "chunk_id": "chunk_001",
      "content": "Recent studies show that protein folding is influenced by...",
      "score": 0.92,
      "metadata": {
        "page": 3,
        "filename": "research_paper.pdf"
      }
    },
    {
      "document_id": "doc_xyz789",
      "chunk_id": "chunk_005",
      "content": "The folding process is critical for protein function...",
      "score": 0.85,
      "metadata": {
        "page": 7,
        "filename": "research_paper.pdf"
      }
    }
  ],
  "query": "What are the key findings about protein folding?",
  "total_results": 2
}
```

## Python Examples

### Complete Workflow

```python
import os
from openai import OpenAI
import time

# Initialize client
client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key=os.getenv("KEYCLOAK_TOKEN")
)

# Step 1: Create knowledge base
kb_response = client.post(
    "/knowledge_bases/create",
    json={
        "name": "Genomics Research",
        "description": "Papers on genomics and bioinformatics",
        "backend_type": "ragflow",
        "chunk_size": 1000,
        "chunk_overlap": 200
    }
)
kb_id = kb_response.json()["kb_id"]
print(f"Created KB: {kb_id}")

# Step 2: Upload documents
documents = [
    "paper1_genomics.pdf",
    "paper2_bioinformatics.pdf",
    "paper3_sequencing.pdf"
]

for doc_path in documents:
    with open(doc_path, "rb") as f:
        ingest_response = client.post(
            "/knowledge_bases/ingest",
            files={"file": f},
            data={"kb_id": kb_id}
        )
        doc_id = ingest_response.json()["document_id"]
        print(f"Ingested: {doc_path} -> {doc_id}")

# Step 3: Wait for processing
print("Waiting for document processing...")
time.sleep(30)  # RAGFlow processing time

# Step 4: Query the knowledge base
query_response = client.post(
    f"/knowledge_bases/query/{kb_id}",
    json={
        "query": "What are the latest sequencing technologies?",
        "top_k": 5
    }
)

results = query_response.json()["results"]
print(f"\nFound {len(results)} relevant passages:")

for i, result in enumerate(results, 1):
    print(f"\n{i}. Score: {result['score']:.2f}")
    print(f"   Source: {result['metadata']['filename']} (page {result['metadata']['page']})")
    print(f"   Content: {result['content'][:200]}...")
```

### Query with Filters

```python
# Query with metadata filters
response = client.post(
    f"/knowledge_bases/query/{kb_id}",
    json={
        "query": "CRISPR applications",
        "top_k": 10,
        "filters": {
            "year": {"$gte": 2020},
            "journal": "Nature Genetics"
        }
    }
)
```

### Batch Document Ingestion

```python
import glob

# Find all PDFs in directory
pdf_files = glob.glob("./research_papers/*.pdf")

# Batch ingest
for pdf_path in pdf_files:
    with open(pdf_path, "rb") as f:
        response = client.post(
            "/knowledge_bases/ingest",
            files={"file": f},
            data={
                "kb_id": kb_id,
                "metadata": {
                    "source": "literature_review_2024",
                    "category": "genomics"
                }
            }
        )
    print(f"Queued: {pdf_path}")
```

## RAG-Enhanced Chat

Use knowledge bases with the Response API for RAG-enhanced conversations:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key=os.getenv("KEYCLOAK_TOKEN")
)

# Step 1: Query knowledge base for relevant context
kb_response = client.post(
    f"/knowledge_bases/query/{kb_id}",
    json={
        "query": "What are the ethical concerns with CRISPR?",
        "top_k": 3
    }
)

# Step 2: Build context from results
context_passages = [
    result["content"] for result in kb_response.json()["results"]
]
context = "\n\n".join(context_passages)

# Step 3: Use context in chat completion
response = client.responses.chat.completions.create(
    model="gpt-4",
    messages=[
        {
            "role": "system",
            "content": f"You are a scientific assistant. Use the following context to answer questions:\n\n{context}"
        },
        {
            "role": "user",
            "content": "What are the ethical concerns with CRISPR technology?"
        }
    ]
)

print(response.choices[0].message.content)
```

## Advanced Features

### 1. Document Status Tracking

```python
# Check document processing status
status_response = client.get(
    f"/knowledge_bases/document/{kb_id}/{doc_id}/status"
)

status_data = status_response.json()
print(f"Status: {status_data['status']}")
print(f"Chunks created: {status_data['chunks_created']}")
print(f"Processing time: {status_data['processing_time_seconds']}s")

# Poll until complete
while status_data["status"] == "processing":
    time.sleep(5)
    status_response = client.get(
        f"/knowledge_bases/document/{kb_id}/{doc_id}/status"
    )
    status_data = status_response.json()

print("Processing complete!")
```

### 2. List and Manage Knowledge Bases

```python
# List all knowledge bases
list_response = client.get("/knowledge_bases/list")
knowledge_bases = list_response.json()["knowledge_bases"]

for kb in knowledge_bases:
    print(f"KB: {kb['name']} ({kb['kb_id']})")
    print(f"  Documents: {kb['document_count']}")
    print(f"  Backend: {kb['backend_type']}")
    print(f"  Created: {kb['created_at']}")

# Get specific knowledge base
kb_details = client.get(f"/knowledge_bases/{kb_id}")
print(kb_details.json())
```

### 3. Delete Knowledge Base

```python
# Delete specific document
delete_doc_response = client.delete(
    f"/knowledge_bases/document/{kb_id}/{doc_id}"
)
print("Document deleted")

# Delete entire knowledge base
delete_kb_response = client.delete(f"/knowledge_bases/{kb_id}")
print("Knowledge base deleted")
```

### 4. Hybrid Search (Semantic + Keyword)

```python
# Combine semantic and keyword search
response = client.post(
    f"/knowledge_bases/query/{kb_id}",
    json={
        "query": "CRISPR gene editing",
        "top_k": 10,
        "search_mode": "hybrid",  # semantic + keyword
        "semantic_weight": 0.7,
        "keyword_weight": 0.3
    }
)
```

## ChromaDB Backend

For lightweight embeddings and local development:

```python
# Create ChromaDB knowledge base
kb_response = client.post(
    "/knowledge_bases/create",
    json={
        "name": "Quick Notes",
        "description": "Personal research notes",
        "backend_type": "chromadb",  # Use ChromaDB
        "chunk_size": 500,
        "chunk_overlap": 50
    }
)

# ChromaDB advantages:
# - Faster ingestion for small documents
# - No external dependencies
# - Ideal for CSV and text files
```

## CSV RAG Tool Integration

For structured data analysis:

```python
# Upload CSV file
with open("experimental_data.csv", "rb") as f:
    file_response = client.files.create(file=f, purpose="assistants")
    file_id = file_response.id

# Analyze with Response API (automatically uses CSV RAG tool)
response = client.responses.chat.completions.create(
    model="gpt-4",
    messages=[
        {
            "role": "user",
            "content": f"Analyze the data in file {file_id}. What correlations exist between columns?"
        }
    ],
    mcp_session_id="csv-analysis-session"
)

print(response.choices[0].message.content)
```

## Best Practices

### 1. Chunking Strategy

```python
# For dense technical documents
kb = client.post("/knowledge_bases/create", json={
    "name": "Technical Manuals",
    "chunk_size": 1500,      # Larger chunks for technical content
    "chunk_overlap": 300     # More overlap to preserve context
})

# For conversational content
kb = client.post("/knowledge_bases/create", json={
    "name": "Chat Logs",
    "chunk_size": 500,       # Smaller chunks for short messages
    "chunk_overlap": 50      # Less overlap needed
})
```

### 2. Score Thresholds

```python
# Adjust relevance threshold based on use case
response = client.post(
    f"/knowledge_bases/query/{kb_id}",
    json={
        "query": "specific technical term",
        "top_k": 10,
        "score_threshold": 0.8  # High threshold for precise matches
    }
)

# Or use lower threshold for exploratory searches
response = client.post(
    f"/knowledge_bases/query/{kb_id}",
    json={
        "query": "general topic exploration",
        "top_k": 20,
        "score_threshold": 0.5  # Lower threshold for broader results
    }
)
```

### 3. Metadata Enrichment

```python
# Add rich metadata during ingestion
with open("paper.pdf", "rb") as f:
    response = client.post(
        "/knowledge_bases/ingest",
        files={"file": f},
        data={
            "kb_id": kb_id,
            "metadata": {
                "title": "CRISPR Applications in Medicine",
                "authors": ["Smith J", "Doe A"],
                "year": 2024,
                "journal": "Nature Medicine",
                "doi": "10.1038/nm.2024.001",
                "keywords": ["CRISPR", "gene editing", "therapeutics"]
            }
        }
    )
```

### 4. Monitoring and Cleanup

```python
# Regular maintenance
kb_list = client.get("/knowledge_bases/list").json()["knowledge_bases"]

for kb in kb_list:
    print(f"KB: {kb['name']}")
    print(f"  Size: {kb['document_count']} documents")
    print(f"  Age: {kb['created_at']}")

    # Delete old unused KBs
    if kb['document_count'] == 0 and age_days > 30:
        client.delete(f"/knowledge_bases/{kb['kb_id']}")
        print(f"  Deleted (empty and old)")
```

## Troubleshooting

### Issue: Slow Query Performance

**Solution**: Adjust chunk size and use score thresholds

```python
# Optimize for speed
response = client.post(
    f"/knowledge_bases/query/{kb_id}",
    json={
        "query": "protein structure",
        "top_k": 5,              # Limit results
        "score_threshold": 0.75,  # Filter low-quality matches early
        "fast_mode": True         # Use approximate nearest neighbor
    }
)
```

### Issue: Low-Quality Retrieval Results

**Solution**: Improve chunking strategy

```python
# Re-create KB with better chunking
new_kb = client.post("/knowledge_bases/create", json={
    "name": "Research Papers v2",
    "chunk_size": 1200,      # Increase chunk size
    "chunk_overlap": 250,    # Increase overlap
    "chunking_strategy": "sentence_aware"  # Respect sentence boundaries
})
```

### Issue: Document Processing Failures

**Solution**: Check document format and size

```bash
# Check supported formats
curl http://localhost:8080/v1/knowledge_bases/supported_formats \
  -H "Authorization: Bearer ${TOKEN}"

# Response: ["pdf", "txt", "docx", "html", "md", "csv"]

# Large files may need splitting
python scripts/split_large_pdf.py input.pdf --max-size 10MB
```

## Performance Benchmarks

| Backend | Ingestion Speed | Query Latency | Best For |
|---------|----------------|---------------|----------|
| RAGFlow | 1-2 min/doc | 200-500ms | PDFs, complex documents |
| ChromaDB | 10-30 sec/doc | 50-150ms | Text files, CSV, fast queries |

## Next Steps

- [Response API Integration](./response-api.md)
- [Admin Tool Management](../README.md#admin-endpoints)
- [Embeddings API](../openapi.json#embeddings)
