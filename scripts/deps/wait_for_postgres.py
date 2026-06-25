# scripts/deps/wait_for_postgres.py
import os
import sys
import time
import logging
import psycopg

# Configure logger for more verbose output
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def list_databases(conn):
    """Lists all databases in the PostgreSQL server."""
    cursor = conn.cursor()
    try:
        logger.info("Executing query to list databases: SELECT datname FROM pg_database;")
        cursor.execute("SELECT datname FROM pg_database;")
        databases = [row[0] for row in cursor.fetchall()]
        logger.info(f"Available databases: {databases}")
        return databases
    except Exception as e:
        logger.error(f"Failed to list databases: {e}", exc_info=True)
        return []
    finally:
        cursor.close()

def create_database_if_not_exists(conn, db_name):
    """Creates a database if it doesn't exist."""
    cursor = conn.cursor()
    try:
        logger.info(f"Checking if database '{db_name}' exists...")
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
        exists = cursor.fetchone()
        if exists:
            logger.info(f"Database '{db_name}' already exists.")
        else:
            logger.info(f"Database '{db_name}' does not exist. Executing CREATE DATABASE {db_name}...")
            # NOTE: We use string formatting for the CREATE DATABASE command because
            # psycopg2 does not support parameterization for database identifiers.
            # This is safe here as db_name is a hardcoded, trusted value.
            cursor.execute(f"CREATE DATABASE {db_name}")
            logger.info(f"Database '{db_name}' created successfully.")
    except Exception as e:
        logger.error(f"An error occurred while creating database '{db_name}': {e}", exc_info=True)
        raise
    finally:
        cursor.close()

def initialize_orchestration_schema(conn, db_user, db_password, db_host):
    """Initialize the orchestration service database schema with hybrid orchestration support."""
    try:
        logger.info("Connecting to agentic_orchestrator database to initialize schema...")
        orch_conn = psycopg.connect(
            f"dbname=agentic_orchestrator user={db_user} password={db_password} host={db_host} connect_timeout=3"
        )
        orch_conn.autocommit = True
        
        cursor = orch_conn.cursor()
        
        # Core checkpoint table with proper LangGraph versioning support
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS checkpoints (
                thread_id TEXT PRIMARY KEY,
                checkpoint BYTEA,
                metadata BYTEA,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Assistants table
        cursor.execute("""
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
        """)
        
        # Threads table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS threads (
                id TEXT PRIMARY KEY,
                object TEXT NOT NULL DEFAULT 'thread',
                created_at BIGINT NOT NULL,
                metadata JSON DEFAULT '{}'::JSON,
                owner_id TEXT
            );
        """)
        
        # Runs table
        cursor.execute("""
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
                owner_id TEXT
            );
        """)
        
        # Run steps table
        cursor.execute("""
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
                owner_id TEXT
            );
        """)
        
        # Multi-agent sessions table for hybrid orchestration
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS multi_agent_sessions (
                session_id TEXT PRIMARY KEY,
                session_data BYTEA,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Session hierarchy table for hybrid orchestration
        cursor.execute("""
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
        """)

        # Tasks table for async tool execution tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tool_name TEXT NOT NULL,
                args JSONB NOT NULL,
                context JSONB NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                progress INTEGER DEFAULT 0,
                result JSONB,
                error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                thread_id TEXT NOT NULL,
                mcp_session_id TEXT,
                multi_agent_session_id TEXT,
                user_id TEXT NOT NULL,
                request_id TEXT NOT NULL
            );
        """)

        # Create indexes for better performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_runs_thread_id ON runs(thread_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_runs_assistant_id ON runs(assistant_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_run_steps_run_id ON run_steps(run_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_run_steps_status ON run_steps(status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_checkpoints_thread_id ON checkpoints(thread_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_session_hierarchies_mcp_session_id ON session_hierarchies(mcp_session_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_session_hierarchies_multi_agent_session_id ON session_hierarchies(multi_agent_session_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_thread_id ON tasks(thread_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at DESC);")
        
        # Update trigger for updated_at timestamps
        cursor.execute("""
            CREATE OR REPLACE FUNCTION update_updated_at_column()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = CURRENT_TIMESTAMP;
                RETURN NEW;
            END;
            $$ language 'plpgsql';
        """)
        
        cursor.execute("""
            DROP TRIGGER IF EXISTS update_checkpoints_updated_at ON checkpoints;
        """)

        cursor.execute("""
            DROP TRIGGER IF EXISTS update_multi_agent_sessions_updated_at ON multi_agent_sessions;
            CREATE TRIGGER update_multi_agent_sessions_updated_at BEFORE UPDATE ON multi_agent_sessions
                FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
        """)
        
        cursor.close()
        orch_conn.close()
        logger.info("Orchestration service schema initialized successfully.")
        
    except Exception as e:
        logger.error(f"Failed to initialize orchestration schema: {e}", exc_info=True)
        raise

def initialize_registry_schema(conn, db_user, db_password, db_host):
    """Initialize the registry service database schema."""
    try:
        logger.info("Connecting to agentic_registry database to initialize schema...")
        reg_conn = psycopg.connect(
            f"dbname=agentic_registry user={db_user} password={db_password} host={db_host} connect_timeout=3"
        )
        reg_conn.autocommit = True
        
        cursor = reg_conn.cursor()

        # Gateway registry table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS gateways (
                alias TEXT PRIMARY KEY,
                public_url TEXT NOT NULL,
                internal_url TEXT,
                capabilities JSON,
                health_status TEXT DEFAULT 'Unknown',
                last_health_check TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Add missing columns if table already exists (schema migration)
        cursor.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='gateways' AND column_name='health_status'
                ) THEN
                    ALTER TABLE gateways ADD COLUMN health_status TEXT DEFAULT 'Unknown';
                END IF;
            END $$;
        """)

        # Note: alias is the PRIMARY KEY, so it already has an index
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_gateways_health_status ON gateways(health_status);")
        
        cursor.close()
        reg_conn.close()
        logger.info("Registry service schema initialized successfully.")
        
    except Exception as e:
        logger.error(f"Failed to initialize registry schema: {e}", exc_info=True)
        raise

def main():
    """
    Waits for the PostgreSQL server to be ready and then ensures
    the required databases are created.
    """
    max_retries = 15
    retry_delay = 5  # seconds
    
    db_user = os.getenv("POSTGRES_USER", "admin")
    db_password = os.getenv("POSTGRES_PASSWORD", "password")
    db_host = "postgres"
    
    logger.info(f"Starting PostgreSQL setup script. Target host: '{db_host}', User: '{db_user}'.")

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Attempt {attempt}/{max_retries}: Trying to connect to PostgreSQL...")
            conn = psycopg.connect(
                f"dbname=postgres user={db_user} password={db_password} host={db_host} connect_timeout=3"
            )
            conn.autocommit = True
            logger.info("Successfully connected to PostgreSQL.")
            
            list_databases(conn)

            create_database_if_not_exists(conn, "agentic_orchestrator")
            create_database_if_not_exists(conn, "agentic_registry")
            create_database_if_not_exists(conn, "keycloak")
            
            # Initialize schemas after database creation
            logger.info("Initializing database schemas with hybrid orchestration support...")
            initialize_orchestration_schema(conn, db_user, db_password, db_host)
            initialize_registry_schema(conn, db_user, db_password, db_host)
            
            list_databases(conn)

            conn.close()
            logger.info("PostgreSQL setup complete. All required databases are present.")
            return
            #sys.exit(0) # Explicitly exit with success code

        except psycopg.OperationalError as e:
            logger.warning(f"PostgreSQL is not ready yet. Retrying in {retry_delay}s... Details: {e}")
            time.sleep(retry_delay)
        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}", exc_info=True)
            sys.exit(1)

    logger.error(f"Failed to connect to PostgreSQL and set up databases after {max_retries} attempts.")
    sys.exit(1)

if __name__ == "__main__":
    main()
