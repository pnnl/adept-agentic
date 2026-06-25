#!/bin/bash
# This script is executed when the PostgreSQL container starts for the first time.
# It creates multiple databases required by the Agentic Framework services with proper schema initialization.
set -e

# Function to create a database if it doesn't exist
create_database() {
    local db_name=$1
    echo "  Creating database '$db_name'"
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "postgres" -tc "SELECT 1 FROM pg_database WHERE datname = '$db_name'" | grep -q 1 || psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "postgres" -c "CREATE DATABASE $db_name"
}

# Function to initialize orchestration service schema with proper checkpoint versioning
initialize_orchestration_schema() {
    echo "  Initializing orchestration service schema with checkpoint versioning..."
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "agentic_orchestrator" <<-EOSQL
		-- Core checkpoint table with proper LangGraph versioning support
		CREATE TABLE IF NOT EXISTS checkpoints (
		    thread_id TEXT PRIMARY KEY,
		    checkpoint BYTEA,
		    metadata BYTEA,
		    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
		    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
		);

		-- Assistants table
		CREATE TABLE IF NOT EXISTS assistants (
		    id TEXT PRIMARY KEY,
		    object TEXT NOT NULL DEFAULT 'assistant',
		    created_at BIGINT NOT NULL,
		    name TEXT,
		    description TEXT,
		    model TEXT NOT NULL,
		    instructions TEXT,
		    tools JSON DEFAULT '[]'::JSON,
		    file_ids JSON DEFAULT '[]'::JSON,
		    metadata JSON DEFAULT '{}'::JSON,
		    owner_id TEXT
		);

		-- Threads table
		CREATE TABLE IF NOT EXISTS threads (
		    id TEXT PRIMARY KEY,
		    object TEXT NOT NULL DEFAULT 'thread',
		    created_at BIGINT NOT NULL,
		    metadata JSON DEFAULT '{}'::JSON,
		    owner_id TEXT
		);

		-- Runs table
		-- NOTE: No FK on thread_id — threads are managed by LangGraph checkpoints
		-- (persistence_v2.py), not the SQL threads table. The Assistants API is
		-- deprecated; Responses API is the primary interface. Removing this FK
		-- prevents IntegrityError when create_thread writes only to checkpoints.
		CREATE TABLE IF NOT EXISTS runs (
		    id TEXT PRIMARY KEY,
		    object TEXT NOT NULL DEFAULT 'thread.run',
		    thread_id TEXT NOT NULL,
		    assistant_id TEXT NOT NULL,
		    status TEXT NOT NULL,
		    created_at BIGINT NOT NULL,
		    model TEXT,
		    instructions TEXT,
		    tools JSON DEFAULT '[]'::JSON,
		    metadata JSON DEFAULT '{}'::JSON,
		    owner_id TEXT,
		    FOREIGN KEY (assistant_id) REFERENCES assistants(id)
		);

		-- Run steps table
		-- NOTE: No FK on thread_id — same rationale as runs table above.
		CREATE TABLE IF NOT EXISTS run_steps (
		    id TEXT PRIMARY KEY,
		    object TEXT NOT NULL DEFAULT 'thread.run.step',
		    run_id TEXT NOT NULL,
		    thread_id TEXT NOT NULL,
		    assistant_id TEXT NOT NULL,
		    status TEXT NOT NULL,
		    step_details JSON NOT NULL,
		    last_error JSON,
		    created_at BIGINT NOT NULL,
		    completed_at BIGINT,
		    failed_at BIGINT,
		    cancelled_at BIGINT,
		    expires_at BIGINT,
		    metadata JSON DEFAULT '{}'::JSON,
		    owner_id TEXT,
		    FOREIGN KEY (run_id) REFERENCES runs(id),
		    FOREIGN KEY (assistant_id) REFERENCES assistants(id)
		);

		-- Multi-agent sessions table for hybrid orchestration
		CREATE TABLE IF NOT EXISTS multi_agent_sessions (
		    session_id TEXT PRIMARY KEY,
		    session_data JSONB,
		    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
		    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
		);

		-- Session hierarchy table for hybrid orchestration
		CREATE TABLE IF NOT EXISTS session_hierarchies (
		    session_id TEXT PRIMARY KEY,
		    mcp_session_id TEXT,
		    multi_agent_session_id TEXT,
		    gateway_session_id TEXT,
		    interaction_type TEXT NOT NULL,
		    supports_a2a BOOLEAN DEFAULT FALSE,
		    supports_multi_agent BOOLEAN DEFAULT FALSE,
		    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
		    last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP
		);

		-- Create indexes for better performance
		CREATE INDEX IF NOT EXISTS idx_runs_thread_id ON runs(thread_id);
		CREATE INDEX IF NOT EXISTS idx_runs_assistant_id ON runs(assistant_id);
		CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
		CREATE INDEX IF NOT EXISTS idx_run_steps_run_id ON run_steps(run_id);
		CREATE INDEX IF NOT EXISTS idx_run_steps_status ON run_steps(status);
		CREATE INDEX IF NOT EXISTS idx_checkpoints_thread_id ON checkpoints(thread_id);
		CREATE INDEX IF NOT EXISTS idx_session_hierarchies_mcp_session_id ON session_hierarchies(mcp_session_id);
		CREATE INDEX IF NOT EXISTS idx_session_hierarchies_multi_agent_session_id ON session_hierarchies(multi_agent_session_id);

		-- Update trigger for updated_at timestamps
		CREATE OR REPLACE FUNCTION update_updated_at_column()
		RETURNS TRIGGER AS \$\$
		BEGIN
		    NEW.updated_at = CURRENT_TIMESTAMP;
		    RETURN NEW;
		END;
		\$\$ language 'plpgsql';

		-- NOTE: No trigger on checkpoints — LangGraph manages its own versioning via checkpoint_id.
		-- The checkpoints table has no updated_at column.

		CREATE TRIGGER update_multi_agent_sessions_updated_at BEFORE UPDATE ON multi_agent_sessions
		    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
	EOSQL
}

# Function to initialize registry schema
initialize_registry_schema() {
    echo "  Initializing registry service schema..."
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "agentic_registry" <<-EOSQL
		-- Gateway registry table
		CREATE TABLE IF NOT EXISTS gateways (
		    id TEXT PRIMARY KEY,
		    name TEXT NOT NULL,
		    url TEXT NOT NULL,
		    status TEXT NOT NULL DEFAULT 'healthy',
		    last_health_check TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
		    metadata JSON DEFAULT '{}'::JSON,
		    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
		);

		CREATE INDEX IF NOT EXISTS idx_gateways_status ON gateways(status);
		CREATE INDEX IF NOT EXISTS idx_gateways_last_health_check ON gateways(last_health_check);
	EOSQL
}

# Create all required databases
create_database "agentic_orchestrator"
create_database "agentic_registry"

# Initialize schemas with proper structure
initialize_orchestration_schema
initialize_registry_schema

echo "All databases and schemas created successfully with hybrid orchestration support."