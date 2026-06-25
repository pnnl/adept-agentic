#!/bin/bash
# This script is executed when the RAG PostgreSQL container starts for the first time.
# It creates the RAG database with pgvector extension and schema for knowledge base storage.
set -e

echo "Initializing RAG database with pgvector extension..."

# Create the RAG database
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "postgres" -tc \
    "SELECT 1 FROM pg_database WHERE datname = 'agentic_rag'" | grep -q 1 || \
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "postgres" \
    -c "CREATE DATABASE agentic_rag"

# Initialize RAG schema with pgvector
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "agentic_rag" <<-EOSQL
	-- Enable pgvector extension for vector similarity search
	CREATE EXTENSION IF NOT EXISTS vector;

	-- Knowledge bases table: top-level container for RAG indexes
	CREATE TABLE IF NOT EXISTS rag_knowledge_bases (
	    kb_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
	    name TEXT NOT NULL,
	    description TEXT,
	    owner_id TEXT,
	    session_id TEXT,
	    visibility TEXT NOT NULL DEFAULT 'session'
	        CHECK (visibility IN ('session', 'user', 'world')),
	    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
	    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
	);

	-- Documents table: tracks ingested files and their processing status
	CREATE TABLE IF NOT EXISTS rag_documents (
	    doc_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
	    kb_id UUID NOT NULL REFERENCES rag_knowledge_bases(kb_id) ON DELETE CASCADE,
	    file_path TEXT NOT NULL,
	    file_id TEXT,
	    status TEXT NOT NULL DEFAULT 'pending'
	        CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
	    metadata JSONB DEFAULT '{}',
	    chunk_count INTEGER DEFAULT 0,
	    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
	);

	-- Chunks table: stores text chunks with vector embeddings and full-text search
	CREATE TABLE IF NOT EXISTS rag_chunks (
	    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
	    kb_id UUID NOT NULL REFERENCES rag_knowledge_bases(kb_id) ON DELETE CASCADE,
	    doc_id UUID NOT NULL REFERENCES rag_documents(doc_id) ON DELETE CASCADE,
	    chunk_index INTEGER NOT NULL,
	    content TEXT NOT NULL,
	    embedding vector(384),
	    content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
	    metadata JSONB DEFAULT '{}',
	    page_number INTEGER,
	    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
	);

	-- HNSW index for approximate nearest neighbor vector search
	CREATE INDEX IF NOT EXISTS idx_rag_chunks_embedding_hnsw
	    ON rag_chunks USING hnsw (embedding vector_cosine_ops)
	    WITH (m = 16, ef_construction = 64);

	-- GIN index for full-text search on generated tsvector column
	CREATE INDEX IF NOT EXISTS idx_rag_chunks_content_tsv
	    ON rag_chunks USING gin (content_tsv);

	-- B-tree indexes for filtering and lookups
	CREATE INDEX IF NOT EXISTS idx_rag_kb_visibility ON rag_knowledge_bases (visibility);
	CREATE INDEX IF NOT EXISTS idx_rag_kb_owner ON rag_knowledge_bases (owner_id);
	CREATE INDEX IF NOT EXISTS idx_rag_kb_session ON rag_knowledge_bases (session_id);
	CREATE INDEX IF NOT EXISTS idx_rag_chunks_kb ON rag_chunks (kb_id);
	CREATE INDEX IF NOT EXISTS idx_rag_docs_kb ON rag_documents (kb_id);
	CREATE INDEX IF NOT EXISTS idx_rag_docs_status ON rag_documents (status);

	-- Auto-update updated_at trigger for knowledge bases
	CREATE OR REPLACE FUNCTION update_rag_kb_updated_at()
	RETURNS TRIGGER AS \$\$
	BEGIN
	    NEW.updated_at = NOW();
	    RETURN NEW;
	END;
	\$\$ LANGUAGE plpgsql;

	DROP TRIGGER IF EXISTS trg_rag_kb_updated_at ON rag_knowledge_bases;
	CREATE TRIGGER trg_rag_kb_updated_at
	    BEFORE UPDATE ON rag_knowledge_bases
	    FOR EACH ROW EXECUTE FUNCTION update_rag_kb_updated_at();
EOSQL

echo "RAG database initialized successfully with pgvector extension and schema."
