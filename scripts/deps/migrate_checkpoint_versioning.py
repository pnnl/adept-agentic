#!/usr/bin/env python3
"""
Database migration script to fix checkpoint versioning issues in existing deployments.

This script addresses the KeyError: 'v' issues by:
1. Adding version field to existing checkpoints
2. Ensuring checkpoint data structure compatibility with LangGraph requirements
3. Creating proper database schema for hybrid orchestration

Run this script on existing deployments before restarting services.
"""
import os
import sys
import time
import pickle
import logging
import psycopg

# Configure logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def fix_checkpoint_versioning(db_host, db_user, db_password):
    """Fix existing checkpoints by adding version field."""
    try:
        logger.info("Connecting to agentic_orchestrator database to fix checkpoint versioning...")
        conn = psycopg.connect(
            f"dbname=agentic_orchestrator user={db_user} password={db_password} host={db_host} connect_timeout=10"
        )
        conn.autocommit = True
        
        cursor = conn.cursor()
        
        # Get all existing checkpoints
        cursor.execute("SELECT thread_id, checkpoint FROM checkpoints;")
        checkpoints = cursor.fetchall()
        
        fixed_count = 0
        for thread_id, checkpoint_data in checkpoints:
            try:
                # Deserialize checkpoint
                checkpoint = pickle.loads(checkpoint_data)
                
                # Check if version field is missing
                if isinstance(checkpoint, dict) and "v" not in checkpoint:
                    # Add version field
                    checkpoint["v"] = 4  # Current LangGraph checkpoint version
                    
                    # Serialize and update
                    updated_checkpoint_data = pickle.dumps(checkpoint)
                    cursor.execute(
                        "UPDATE checkpoints SET checkpoint = %s WHERE thread_id = %s",
                        (updated_checkpoint_data, thread_id)
                    )
                    
                    fixed_count += 1
                    logger.debug(f"Fixed checkpoint versioning for thread {thread_id}")
                    
            except Exception as e:
                logger.warning(f"Could not fix checkpoint for thread {thread_id}: {e}")
                continue
        
        cursor.close()
        conn.close()
        
        logger.info(f"Fixed {fixed_count} checkpoints with missing version fields.")
        return fixed_count
        
    except Exception as e:
        logger.error(f"Failed to fix checkpoint versioning: {e}")
        raise

def add_hybrid_orchestration_tables(db_host, db_user, db_password):
    """Add tables required for hybrid orchestration if they don't exist."""
    try:
        logger.info("Adding hybrid orchestration tables...")
        conn = psycopg.connect(
            f"dbname=agentic_orchestrator user={db_user} password={db_password} host={db_host} connect_timeout=10"
        )
        conn.autocommit = True
        
        cursor = conn.cursor()
        
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
        
        # Create indexes for session hierarchies
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_session_hierarchies_mcp_session_id ON session_hierarchies(mcp_session_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_session_hierarchies_multi_agent_session_id ON session_hierarchies(multi_agent_session_id);")
        
        # Add missing columns to existing tables if needed
        try:
            cursor.execute("ALTER TABLE checkpoints ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;")
            cursor.execute("ALTER TABLE checkpoints ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;")
        except Exception as e:
            logger.debug(f"Columns may already exist: {e}")
        
        try:
            cursor.execute("ALTER TABLE multi_agent_sessions ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;")
            cursor.execute("ALTER TABLE multi_agent_sessions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;")
        except Exception as e:
            logger.debug(f"Columns may already exist: {e}")
        
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
        conn.close()
        
        logger.info("Hybrid orchestration tables added successfully.")
        
    except Exception as e:
        logger.error(f"Failed to add hybrid orchestration tables: {e}")
        raise

def main():
    """Main migration function."""
    db_host = os.getenv("POSTGRES_HOST", "postgres")
    db_user = os.getenv("POSTGRES_USER", "admin")
    db_password = os.getenv("POSTGRES_PASSWORD", "password")
    
    logger.info(f"Starting checkpoint versioning migration for host: {db_host}")
    
    max_retries = 5
    retry_delay = 5
    
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Attempt {attempt}/{max_retries}: Connecting to PostgreSQL...")

            # Test connection
            test_conn = psycopg.connect(
                f"dbname=agentic_orchestrator user={db_user} password={db_password} host={db_host} connect_timeout=3"
            )
            test_conn.close()
            logger.info("Successfully connected to PostgreSQL.")
            
            # Fix checkpoint versioning
            fixed_count = fix_checkpoint_versioning(db_host, db_user, db_password)
            
            # Add hybrid orchestration tables
            add_hybrid_orchestration_tables(db_host, db_user, db_password)
            
            logger.info(f"Migration completed successfully. Fixed {fixed_count} checkpoints.")
            return

        except psycopg.OperationalError as e:
            logger.warning(f"PostgreSQL is not ready yet. Retrying in {retry_delay}s... Details: {e}")
            time.sleep(retry_delay)
        except Exception as e:
            logger.error(f"Migration failed: {e}")
            sys.exit(1)
    
    logger.error(f"Failed to complete migration after {max_retries} attempts.")
    sys.exit(1)

if __name__ == "__main__":
    main()