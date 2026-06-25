#!/usr/bin/env python3
"""
Database schema migration script to add missing columns.

This script addresses the schema mismatch between the SQLAlchemy models
and the actual database tables by ensuring all required columns exist.
"""
import os
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

from ..logger_config import get_logger

logger = get_logger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://admin:password@postgres:5432/agentic_orchestrator")

async def migrate_schema():
    """
    Migrate the database schema to add missing columns.
    """
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    
    try:
        async with engine.begin() as conn:
            logger.info("Starting database schema migration...")
            
            # Check if assistants table exists, create if not
            result = await conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'assistants'
                );
            """))
            table_exists = result.scalar()
            
            if not table_exists:
                logger.info("Creating assistants table...")
                await conn.execute(text("""
                    CREATE TABLE assistants (
                        id TEXT PRIMARY KEY,
                        created_at BIGINT,
                        name TEXT,
                        description TEXT,
                        model TEXT NOT NULL,
                        instructions TEXT,
                        tools JSON,
                        owner_id TEXT,
                        file_ids JSON,
                        metadata JSON
                    );
                """))
                logger.info("Assistants table created.")
            else:
                logger.info("Assistants table exists, checking columns...")
                
                # Check and add missing columns to assistants table
                missing_columns = []
                
                # Check for description column
                result = await conn.execute(text("""
                    SELECT column_name FROM information_schema.columns 
                    WHERE table_name = 'assistants' AND column_name = 'description';
                """))
                if not result.fetchone():
                    missing_columns.append("description")
                
                # Check for instructions column  
                result = await conn.execute(text("""
                    SELECT column_name FROM information_schema.columns 
                    WHERE table_name = 'assistants' AND column_name = 'instructions';
                """))
                if not result.fetchone():
                    missing_columns.append("instructions")
                
                # Check for name column
                result = await conn.execute(text("""
                    SELECT column_name FROM information_schema.columns 
                    WHERE table_name = 'assistants' AND column_name = 'name';
                """))
                if not result.fetchone():
                    missing_columns.append("name")
                    
                # Check for file_ids column
                result = await conn.execute(text("""
                    SELECT column_name FROM information_schema.columns 
                    WHERE table_name = 'assistants' AND column_name = 'file_ids';
                """))
                if not result.fetchone():
                    missing_columns.append("file_ids")
                
                # Add missing columns
                for column in missing_columns:
                    logger.info(f"Adding missing column '{column}' to assistants table...")
                    if column == "model":
                        await conn.execute(text("ALTER TABLE assistants ADD COLUMN model TEXT NOT NULL DEFAULT 'default-model';"))
                    elif column in ["description", "instructions", "name", "owner_id"]:
                        await conn.execute(text(f"ALTER TABLE assistants ADD COLUMN {column} TEXT;"))
                    elif column in ["file_ids", "metadata"]:
                        await conn.execute(text(f"ALTER TABLE assistants ADD COLUMN {column} JSON;"))
                    elif column == "created_at":
                        await conn.execute(text("ALTER TABLE assistants ADD COLUMN created_at BIGINT;"))
                    
                if missing_columns:
                    logger.info(f"Added missing columns: {missing_columns}")
                else:
                    logger.info("All required columns already exist in assistants table.")
            
            # Check runs table for missing instructions column
            logger.info("Checking runs table for missing columns...")
            result = await conn.execute(text("""
                SELECT column_name FROM information_schema.columns 
                WHERE table_name = 'runs' AND column_name = 'instructions';
            """))
            if not result.fetchone():
                logger.info("Adding missing 'instructions' column to runs table...")
                await conn.execute(text("ALTER TABLE runs ADD COLUMN instructions TEXT;"))
                logger.info("Added instructions column to runs table.")
            else:
                logger.info("Instructions column already exists in runs table.")
                
            # Verify final schema
            logger.info("Verifying final schema...")
            for table in ['assistants', 'runs']:
                result = await conn.execute(text(f"""
                    SELECT column_name, data_type, is_nullable 
                    FROM information_schema.columns 
                    WHERE table_name = '{table}' 
                    ORDER BY ordinal_position;
                """))
                columns = result.fetchall()
                logger.info(f"{table} table schema:")
                for col in columns:
                    logger.info(f"  - {col[0]} ({col[1]}, nullable: {col[2]})")
            
            logger.info("Schema migration completed successfully.")
            
    except Exception as e:
        logger.error(f"Schema migration failed: {e}")
        raise
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(migrate_schema())