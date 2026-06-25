#!/usr/bin/env python3
"""
Database Schema Validation Script

This script validates the PostgreSQL database schema against expected definitions
for Session Management Phase 1 tables and LangGraph checkpoint tables. It checks:
- Column definitions (name, type, nullable, default values)
- Constraints (UNIQUE, CHECK, FK)
- Indexes
- Triggers

Tables validated:
- user_sessions (Session 32 Phase 1)
- session_messages (Session 32 Phase 1)
- tool_outputs (Session 32 Phase 1)
- context_archives (Session 32 Phase 1)
- checkpoints (LangGraph 1.0.5 checkpoint state)

Usage:
    python validate_schema.py [--verbose] [--json]

Exit Codes:
    0 - Schema matches expected configuration
    1 - Schema drift detected (mismatches found)
    2 - Connection error or script failure
"""

import argparse
import json
import os
import sys
from typing import Dict, List, Any, Optional
import psycopg


# Expected Schema Definitions
# ============================================================================

EXPECTED_SCHEMA = {
    "user_sessions": {
        "columns": [
            {"name": "session_id", "type": "text", "nullable": False, "primary_key": True},
            {"name": "mcp_session_id", "type": "text", "nullable": True},
            {"name": "multi_agent_session_id", "type": "text", "nullable": True},
            {"name": "gateway_session_id", "type": "text", "nullable": True},
            {"name": "user_id", "type": "text", "nullable": False},
            {"name": "username", "type": "text", "nullable": True},
            {"name": "session_type", "type": "text", "nullable": False},
            {"name": "status", "type": "text", "nullable": False},
            {"name": "created_at", "type": "timestamp without time zone", "nullable": False},
            {"name": "last_active_at", "type": "timestamp without time zone", "nullable": False},
            {"name": "archived_at", "type": "timestamp without time zone", "nullable": True},
            {"name": "deleted_at", "type": "timestamp without time zone", "nullable": True},
            {"name": "total_tokens", "type": "integer", "nullable": True},
            {"name": "estimated_cost_usd", "type": "numeric", "nullable": True},
            {"name": "title", "type": "text", "nullable": True},
            {"name": "tags", "type": "text[]", "nullable": True},
            {"name": "session_metadata", "type": "jsonb", "nullable": False},
            {"name": "retention_policy", "type": "text", "nullable": False},
        ],
        "constraints": [
            {"name": "user_sessions_pkey", "type": "PRIMARY KEY", "columns": ["session_id"]},
            {"name": "chk_user_sessions_status", "type": "CHECK", "definition": "status IN ('active', 'archived', 'pending_deletion', 'deleted')"},
        ],
        "indexes": [
            {"name": "idx_user_sessions_user_status_created", "columns": ["user_id", "status", "created_at"]},
            {"name": "idx_user_sessions_last_active", "columns": ["last_active_at"]},
            {"name": "idx_user_sessions_status", "columns": ["status"]},
            {"name": "idx_user_sessions_tags", "type": "gin", "columns": ["tags"]},
            {"name": "idx_user_sessions_multi_tier", "columns": ["mcp_session_id", "multi_agent_session_id"]},
        ],
    },
    "session_messages": {
        "columns": [
            {"name": "id", "type": "uuid", "nullable": False, "default": "gen_random_uuid()"},
            {"name": "created_at", "type": "timestamp without time zone", "nullable": False, "default": "CURRENT_TIMESTAMP"},
            {"name": "session_id", "type": "text", "nullable": False},
            {"name": "message_index", "type": "integer", "nullable": False},
            {"name": "message_role", "type": "text", "nullable": False},
            {"name": "message_content", "type": "text", "nullable": True},
            {"name": "message_metadata", "type": "jsonb", "nullable": True, "default": "'{}'::jsonb"},
            {"name": "context_layer", "type": "text", "nullable": True, "default": "'historical'::text"},
            {"name": "classification_tier", "type": "text", "nullable": True},
            {"name": "importance_score", "type": "double precision", "nullable": True},
            {"name": "fidelity_level", "type": "text", "nullable": True},
            {"name": "tool_call_ids", "type": "text[]", "nullable": True},
            {"name": "has_tool_outputs", "type": "boolean", "nullable": True, "default": "false"},
            {"name": "content_tsvector", "type": "tsvector", "nullable": True},  # GENERATED column
        ],
        "constraints": [
            {"name": "session_messages_pkey", "type": "PRIMARY KEY", "columns": ["id", "created_at"]},
            {"name": "uq_session_message_idx", "type": "UNIQUE", "columns": ["session_id", "message_index", "created_at"]},
            {"name": "session_messages_session_id_fkey", "type": "FOREIGN KEY", "columns": ["session_id"], "references": "user_sessions(session_id)"},
        ],
        "indexes": [
            {"name": "idx_session_messages_session", "columns": ["session_id", "message_index"]},
            {"name": "idx_session_messages_created", "columns": ["created_at"]},
            {"name": "idx_session_messages_role", "columns": ["message_role"]},
            {"name": "idx_session_messages_context_layer", "columns": ["context_layer"]},
            {"name": "idx_session_messages_tool_calls", "type": "gin", "columns": ["tool_call_ids"]},
            {"name": "idx_session_messages_content_fts", "type": "gin", "columns": ["content_tsvector"]},
        ],
        "partitioned": True,
    },
    "tool_outputs": {
        "columns": [
            {"name": "id", "type": "uuid", "nullable": False},
            {"name": "tool_call_id", "type": "text", "nullable": False},
            {"name": "tool_name", "type": "text", "nullable": True},
            {"name": "full_output", "type": "jsonb", "nullable": True},
            {"name": "output_size", "type": "integer", "nullable": True},
            {"name": "session_id", "type": "text", "nullable": True},
            {"name": "mcp_session_id", "type": "text", "nullable": True},
            {"name": "thread_id", "type": "text", "nullable": True},
            {"name": "checkpoint_id", "type": "text", "nullable": True},
            {"name": "message_id", "type": "uuid", "nullable": True},  # Added in migration 002
            {"name": "output_sequence", "type": "integer", "nullable": True},
            {"name": "retention_status", "type": "text", "nullable": False},  # Added in migration 002
            {"name": "created_at", "type": "timestamp without time zone", "nullable": False},
            {"name": "updated_at", "type": "timestamp without time zone", "nullable": True},
        ],
        "indexes": [
            {"name": "idx_tool_outputs_message", "columns": ["message_id"]},
            {"name": "idx_tool_outputs_retention", "columns": ["retention_status"]},
        ],
        "triggers": [
            {"name": "on_tool_output_orphaned", "function": "mark_orphaned_tool_outputs()"},
        ],
    },
    "context_archives": {
        "columns": [
            {"name": "id", "type": "uuid", "nullable": False, "primary_key": True},
            {"name": "session_id", "type": "text", "nullable": False},
            {"name": "thread_id", "type": "text", "nullable": False},
            {"name": "mcp_session_id", "type": "text", "nullable": True},
            {"name": "multi_agent_session_id", "type": "text", "nullable": True},
            {"name": "archive_sequence", "type": "integer", "nullable": False},
            {"name": "message_range_start", "type": "integer", "nullable": False},
            {"name": "message_range_end", "type": "integer", "nullable": False},
            {"name": "summary_content", "type": "text", "nullable": False},
            {"name": "original_token_count", "type": "integer", "nullable": False},
            {"name": "summary_token_count", "type": "integer", "nullable": False},
            {"name": "compression_ratio", "type": "double precision", "nullable": True},
            {"name": "classification_tier", "type": "text", "nullable": False},
            {"name": "average_importance_score", "type": "double precision", "nullable": True},
            {"name": "summarization_model", "type": "text", "nullable": True},
            {"name": "summarization_strategy", "type": "text", "nullable": True},
            {"name": "summarized_at", "type": "timestamp without time zone", "nullable": False},
            {"name": "user_id", "type": "text", "nullable": True},
        ],
        "constraints": [
            {"name": "context_archives_pkey", "type": "PRIMARY KEY", "columns": ["id"]},
            {"name": "uq_context_archives_seq", "type": "UNIQUE", "columns": ["session_id", "archive_sequence"]},
        ],
        "indexes": [
            {"name": "idx_context_archives_session", "columns": ["session_id", "archive_sequence"]},
            {"name": "idx_context_archives_thread", "columns": ["thread_id"]},
            {"name": "idx_context_archives_summarized", "columns": ["summarized_at"]},
        ],
    },
    "checkpoints": {
        "columns": [
            {"name": "thread_id", "type": "text", "nullable": False},
            {"name": "checkpoint_ns", "type": "text", "nullable": False, "default": "''::text"},
            {"name": "checkpoint_id", "type": "text", "nullable": False},
            {"name": "parent_checkpoint_id", "type": "text", "nullable": True},
            {"name": "type", "type": "text", "nullable": True},
            {"name": "checkpoint", "type": "jsonb", "nullable": False},
            {"name": "metadata", "type": "jsonb", "nullable": False, "default": "'{}'::jsonb"},
        ],
        "constraints": [
            {"name": "checkpoints_pkey", "type": "PRIMARY KEY", "columns": ["thread_id", "checkpoint_ns", "checkpoint_id"]},
        ],
        "indexes": [
            {"name": "checkpoints_thread_id_idx", "columns": ["thread_id"]},
        ],
    },
}


# Database Query Functions
# ============================================================================

def connect_to_database() -> psycopg.Connection:
    """Connect to PostgreSQL database using environment variables."""
    db_host = os.getenv("POSTGRES_HOST", "postgres")
    db_port = os.getenv("POSTGRES_PORT", "5432")
    db_name = os.getenv("POSTGRES_DB", "agentic_orchestrator")
    db_user = os.getenv("POSTGRES_USER", "admin")
    db_password = os.getenv("POSTGRES_PASSWORD", "password")

    connection_string = (
        f"host={db_host} port={db_port} dbname={db_name} "
        f"user={db_user} password={db_password}"
    )

    try:
        conn = psycopg.connect(connection_string)
        return conn
    except Exception as e:
        print(f"❌ [ERROR] Failed to connect to database: {e}", file=sys.stderr)
        sys.exit(2)


def get_table_columns(conn: psycopg.Connection, table_name: str) -> List[Dict[str, Any]]:
    """
    Query column definitions for a table using pg_catalog for better default detection.

    Uses pg_catalog.pg_attrdef instead of information_schema.columns because
    information_schema.column_default doesn't reliably return defaults for all columns.
    """
    query = """
        SELECT
            a.attname AS column_name,
            pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
            NOT a.attnotnull AS is_nullable,
            pg_get_expr(d.adbin, d.adrelid) AS column_default
        FROM pg_catalog.pg_attribute a
        LEFT JOIN pg_catalog.pg_attrdef d ON (a.attrelid, a.attnum) = (d.adrelid, d.adnum)
        WHERE a.attrelid = (
            SELECT oid FROM pg_catalog.pg_class
            WHERE relname = %s AND relnamespace = (
                SELECT oid FROM pg_catalog.pg_namespace WHERE nspname = 'public'
            )
        )
        AND a.attnum > 0
        AND NOT a.attisdropped
        ORDER BY a.attnum
    """
    with conn.cursor() as cur:
        cur.execute(query, (table_name,))
        rows = cur.fetchall()

    columns = []
    for row in rows:
        columns.append({
            "name": row[0],
            "type": row[1],
            "nullable": row[2],
            "default": row[3],
        })
    return columns


def get_table_constraints(conn: psycopg.Connection, table_name: str) -> List[Dict[str, Any]]:
    """Query constraint definitions for a table."""
    query = """
        SELECT
            tc.constraint_name,
            tc.constraint_type,
            array_agg(kcu.column_name ORDER BY kcu.ordinal_position) AS columns,
            cc.check_clause
        FROM information_schema.table_constraints tc
        LEFT JOIN information_schema.key_column_usage kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        LEFT JOIN information_schema.check_constraints cc
            ON tc.constraint_name = cc.constraint_name
        WHERE tc.table_name = %s
        GROUP BY tc.constraint_name, tc.constraint_type, cc.check_clause
    """
    with conn.cursor() as cur:
        cur.execute(query, (table_name,))
        rows = cur.fetchall()

    constraints = []
    for row in rows:
        constraints.append({
            "name": row[0],
            "type": row[1],
            "columns": row[2] if row[2] else [],
            "definition": row[3],
        })
    return constraints


def get_table_indexes(conn: psycopg.Connection, table_name: str) -> List[Dict[str, Any]]:
    """Query index definitions for a table."""
    query = """
        SELECT
            indexname,
            indexdef
        FROM pg_indexes
        WHERE tablename = %s
    """
    with conn.cursor() as cur:
        cur.execute(query, (table_name,))
        rows = cur.fetchall()

    indexes = []
    for row in rows:
        indexes.append({
            "name": row[0],
            "definition": row[1],
        })
    return indexes


def get_table_triggers(conn: psycopg.Connection, table_name: str) -> List[Dict[str, Any]]:
    """Query trigger definitions for a table."""
    query = """
        SELECT
            trigger_name,
            action_statement
        FROM information_schema.triggers
        WHERE event_object_table = %s
    """
    with conn.cursor() as cur:
        cur.execute(query, (table_name,))
        rows = cur.fetchall()

    triggers = []
    for row in rows:
        triggers.append({
            "name": row[0],
            "function": row[1],
        })
    return triggers


def get_trigger_details(conn: psycopg.Connection, table_name: str, trigger_name: str) -> Optional[Dict[str, Any]]:
    """
    Get comprehensive trigger details including timing, events, and function.

    Args:
        conn: Database connection
        table_name: Name of the table
        trigger_name: Name of the trigger

    Returns:
        Dictionary with trigger details or None if not found:
        {
            'name': str,
            'timing': 'BEFORE' | 'AFTER' | 'INSTEAD OF',
            'events': ['INSERT', 'UPDATE', 'DELETE'],
            'function_name': str,
            'function_body': str,
            'enabled': bool
        }
    """
    query = """
    SELECT
        t.tgname AS trigger_name,
        CASE t.tgtype::integer & 66
            WHEN 2 THEN 'BEFORE'
            WHEN 64 THEN 'AFTER'
            ELSE 'INSTEAD OF'
        END AS timing,
        CASE
            WHEN t.tgtype::integer & 4 > 0 THEN 'INSERT'
            ELSE NULL
        END AS insert_event,
        CASE
            WHEN t.tgtype::integer & 8 > 0 THEN 'DELETE'
            ELSE NULL
        END AS delete_event,
        CASE
            WHEN t.tgtype::integer & 16 > 0 THEN 'UPDATE'
            ELSE NULL
        END AS update_event,
        p.proname AS function_name,
        pg_get_functiondef(p.oid) AS function_body,
        t.tgenabled = 'O' AS enabled
    FROM pg_trigger t
    JOIN pg_class c ON t.tgrelid = c.oid
    JOIN pg_proc p ON t.tgfoid = p.oid
    WHERE c.relname = %s
    AND t.tgname = %s
    AND NOT t.tgisinternal
    """

    with conn.cursor() as cursor:
        cursor.execute(query, (table_name, trigger_name))
        result = cursor.fetchone()

        if not result:
            return None

        return {
            'name': result[0],
            'timing': result[1],
            'events': [e for e in [result[2], result[3], result[4]] if e],
            'function_name': result[5],
            'function_body': result[6],
            'enabled': result[7]
        }


# Validation Functions
# ============================================================================

def validate_columns(
    table_name: str,
    expected: List[Dict[str, Any]],
    actual: List[Dict[str, Any]],
    verbose: bool = False
) -> List[str]:
    """Validate column definitions match expected schema."""
    errors = []

    # Create lookup maps
    expected_map = {col["name"]: col for col in expected}
    actual_map = {col["name"]: col for col in actual}

    # Check for missing columns
    for col_name in expected_map:
        if col_name not in actual_map:
            errors.append(f"  ❌ Missing column: {table_name}.{col_name}")

    # Check for extra columns (warning only)
    for col_name in actual_map:
        if col_name not in expected_map:
            if verbose:
                print(f"  ⚠️  Extra column found: {table_name}.{col_name} (not in expected schema)")

    # Validate column properties
    for col_name, expected_col in expected_map.items():
        if col_name not in actual_map:
            continue  # Already reported as missing

        actual_col = actual_map[col_name]

        # Type validation (normalize types)
        expected_type = normalize_type(expected_col["type"])
        actual_type = normalize_type(actual_col["type"])
        if expected_type != actual_type:
            errors.append(
                f"  ❌ Column {table_name}.{col_name} type mismatch: "
                f"expected {expected_type}, got {actual_type}"
            )

        # Nullable validation
        if expected_col["nullable"] != actual_col["nullable"]:
            errors.append(
                f"  ❌ Column {table_name}.{col_name} nullable mismatch: "
                f"expected {expected_col['nullable']}, got {actual_col['nullable']}"
            )

        # Default value validation (if specified in expected)
        if "default" in expected_col:
            expected_default = normalize_default(expected_col["default"])
            actual_default = normalize_default(actual_col.get("default"))
            if expected_default and actual_default != expected_default:
                errors.append(
                    f"  ❌ Column {table_name}.{col_name} default mismatch: "
                    f"expected {expected_default}, got {actual_default}"
                )

    return errors


def validate_constraints(
    table_name: str,
    expected: List[Dict[str, Any]],
    actual: List[Dict[str, Any]],
    verbose: bool = False
) -> List[str]:
    """Validate constraint definitions match expected schema."""
    errors = []

    # Create lookup maps
    expected_map = {c["name"]: c for c in expected}
    actual_map = {c["name"]: c for c in actual}

    # Check for missing constraints
    for constraint_name in expected_map:
        if constraint_name not in actual_map:
            errors.append(f"  ❌ Missing constraint: {constraint_name}")

    return errors


def validate_indexes(
    table_name: str,
    expected: List[Dict[str, Any]],
    actual: List[Dict[str, Any]],
    verbose: bool = False
) -> List[str]:
    """
    Validate index definitions match expected schema.

    Matches indexes by columns, not exact index name, to handle naming variations.
    """
    errors = []

    # Check for missing indexes by matching columns
    for expected_idx in expected:
        expected_columns = expected_idx.get("columns", [])
        if not expected_columns:
            continue

        # Check if any actual index covers the expected columns
        found = False
        for actual_idx in actual:
            # Check if all expected columns appear in the index definition
            if all(col in actual_idx["definition"] for col in expected_columns):
                found = True
                if verbose:
                    print(f"  ✓ Index on columns {expected_columns} found as: {actual_idx['name']}")
                break

        if not found:
            columns_str = ", ".join(expected_columns)
            errors.append(f"  ❌ Missing index on columns: {columns_str} (expected name: {expected_idx['name']})")

    return errors


def validate_triggers(
    table_name: str,
    expected: List[Dict[str, Any]],
    actual: List[Dict[str, Any]],
    conn: psycopg.Connection,
    verbose: bool = False
) -> List[str]:
    """
    Validate triggers with comprehensive checks.

    Validates:
    - Trigger exists
    - Trigger is enabled
    - Trigger timing (BEFORE/AFTER) if specified
    - Trigger events (INSERT/UPDATE/DELETE) if specified
    - Trigger function name
    - Trigger function body contains expected logic (optional)

    Args:
        table_name: Name of the table
        expected: List of expected trigger definitions
        actual: List of actual trigger definitions from database
        conn: Database connection for detailed queries
        verbose: Print detailed validation info

    Returns:
        List of error messages
    """
    errors = []

    # Create lookup map
    actual_map = {t["name"]: t for t in actual}

    # Check for missing triggers and validate details
    for expected_trigger in expected:
        trigger_name = expected_trigger["name"]

        if trigger_name not in actual_map:
            errors.append(f"  ❌ Missing trigger: {trigger_name}")
            continue

        # Get detailed trigger information for comprehensive validation
        details = get_trigger_details(conn, table_name, trigger_name)

        if not details:
            errors.append(f"  ❌ Trigger {trigger_name} found but couldn't retrieve details")
            continue

        # Validate enabled status
        if not details['enabled']:
            errors.append(f"  ❌ Trigger {trigger_name} exists but is DISABLED")

        # Validate timing (if specified in expected)
        if "timing" in expected_trigger:
            if details['timing'] != expected_trigger['timing']:
                errors.append(
                    f"  ❌ Trigger {trigger_name} timing mismatch: "
                    f"expected {expected_trigger['timing']}, got {details['timing']}"
                )

        # Validate events (if specified in expected)
        if "events" in expected_trigger:
            expected_events = set(expected_trigger['events'])
            actual_events = set(details['events'])
            if expected_events != actual_events:
                errors.append(
                    f"  ❌ Trigger {trigger_name} events mismatch: "
                    f"expected {expected_events}, got {actual_events}"
                )

        # Validate function name
        if "function" in expected_trigger:
            expected_function = expected_trigger["function"].replace("()", "")
            if details['function_name'] != expected_function:
                errors.append(
                    f"  ❌ Trigger {trigger_name} function mismatch: "
                    f"expected {expected_function}, got {details['function_name']}"
                )

        # Optional: Validate function body contains key logic
        if "function_contains" in expected_trigger:
            for pattern in expected_trigger["function_contains"]:
                if pattern not in details['function_body']:
                    errors.append(
                        f"  ❌ Trigger function {details['function_name']} "
                        f"missing expected logic: {pattern}"
                    )

        if verbose and not errors:
            print(f"    ✓ Trigger {trigger_name} validated (timing={details['timing']}, events={details['events']})")

    return errors


# Utility Functions
# ============================================================================

def normalize_type(type_str: Optional[str]) -> str:
    """
    Normalize PostgreSQL data types for comparison.

    Handles type aliases and variations that PostgreSQL considers equivalent.
    """
    if not type_str:
        return ""

    import re

    # Check if it's an array type
    is_array = type_str.endswith('[]')
    base_type_str = type_str[:-2] if is_array else type_str

    # Remove precision/scale info (e.g., "character varying(255)" -> "character varying")
    base_type = re.sub(r'\(\d+(?:,\d+)?\)', '', base_type_str)

    # Map common type variations
    type_map = {
        "character varying": "text",
        "varchar": "text",
        "timestamp without time zone": "timestamp",
        "timestamp with time zone": "timestamptz",
        "double precision": "float8",
        "integer": "int4",
        "bigint": "int8",
        "smallint": "int2",
    }

    type_lower = base_type.lower().strip()
    normalized = type_map.get(type_lower, type_lower)

    # Add array suffix back if it was an array
    return f"{normalized}[]" if is_array else normalized


def normalize_default(default_str: Optional[str]) -> str:
    """Normalize default value expressions for comparison."""
    if not default_str:
        return ""

    # Remove whitespace and quotes
    normalized = default_str.strip().replace("'", "").replace('"', "")

    # Normalize common patterns
    if "CURRENT_TIMESTAMP" in normalized.upper():
        return "CURRENT_TIMESTAMP"
    if "gen_random_uuid" in normalized:
        return "gen_random_uuid()"

    return normalized


def normalize_check_clause(clause: str) -> str:
    """
    Normalize CHECK constraint SQL for comparison.

    Handles whitespace, case, and formatting variations that PostgreSQL
    considers equivalent.

    Args:
        clause: CHECK constraint SQL clause

    Returns:
        Normalized SQL clause
    """
    if not clause:
        return ""

    import re

    # Remove extra whitespace
    normalized = re.sub(r'\s+', ' ', clause.strip())

    # Normalize quotes (single vs double)
    normalized = normalized.replace('"', "'")

    # Normalize case for keywords (IN, AND, OR)
    keywords = ['IN', 'AND', 'OR', 'NOT', 'NULL']
    for keyword in keywords:
        normalized = re.sub(
            rf'\b{keyword.lower()}\b',
            keyword,
            normalized,
            flags=re.IGNORECASE
        )

    # Remove parentheses around the entire expression if present
    if normalized.startswith('(') and normalized.endswith(')'):
        normalized = normalized[1:-1].strip()

    return normalized.upper()


# Main Validation Logic
# ============================================================================

def validate_schema(verbose: bool = False, json_output: bool = False) -> int:
    """
    Main schema validation function.

    Returns:
        0 if schema is valid
        1 if schema drift detected
        2 if error occurred
    """
    print("[INFO] Session 32 Phase 1 - Schema Validation Starting...")
    print(f"[INFO] Target Database: {os.getenv('POSTGRES_DB', 'agentic_orchestrator')}")
    print(f"[INFO] Host: {os.getenv('POSTGRES_HOST', 'postgres')}:{os.getenv('POSTGRES_PORT', '5432')}\n")

    conn = connect_to_database()

    all_errors = []
    results = {}

    try:
        for table_name, expected_schema in EXPECTED_SCHEMA.items():
            print(f"[INFO] Validating table: {table_name}")
            table_errors = []

            # Validate columns
            actual_columns = get_table_columns(conn, table_name)
            if "columns" in expected_schema:
                column_errors = validate_columns(
                    table_name, expected_schema["columns"], actual_columns, verbose
                )
                table_errors.extend(column_errors)

            # Validate constraints
            actual_constraints = get_table_constraints(conn, table_name)
            if "constraints" in expected_schema:
                constraint_errors = validate_constraints(
                    table_name, expected_schema["constraints"], actual_constraints, verbose
                )
                table_errors.extend(constraint_errors)

            # Validate indexes
            actual_indexes = get_table_indexes(conn, table_name)
            if "indexes" in expected_schema:
                index_errors = validate_indexes(
                    table_name, expected_schema["indexes"], actual_indexes, verbose
                )
                table_errors.extend(index_errors)

            # Validate triggers
            if "triggers" in expected_schema:
                actual_triggers = get_table_triggers(conn, table_name)
                trigger_errors = validate_triggers(
                    table_name, expected_schema["triggers"], actual_triggers, conn, verbose
                )
                table_errors.extend(trigger_errors)

            # Report results
            if table_errors:
                print(f"  ❌ {len(table_errors)} issue(s) found:")
                for error in table_errors:
                    print(error)
                all_errors.extend(table_errors)
            else:
                print(f"  ✅ Schema matches expected configuration")

            results[table_name] = {
                "valid": len(table_errors) == 0,
                "errors": table_errors,
            }

            print()

    finally:
        conn.close()

    # Final summary
    print("=" * 80)
    if all_errors:
        print(f"❌ [SCHEMA DRIFT DETECTED] {len(all_errors)} total issue(s) found across {len(results)} tables\n")
        print("Recommendation: Review migrations and apply necessary schema fixes")
        exit_code = 1
    else:
        print(f"✅ [SCHEMA VALID] All {len(results)} tables match expected configuration\n")
        exit_code = 0

    # JSON output if requested
    if json_output:
        output = {
            "valid": exit_code == 0,
            "total_errors": len(all_errors),
            "tables": results,
        }
        print(json.dumps(output, indent=2))

    return exit_code


# CLI Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Validate Session 32 Phase 1 database schema"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed validation output"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON"
    )

    args = parser.parse_args()

    try:
        exit_code = validate_schema(verbose=args.verbose, json_output=args.json)
        sys.exit(exit_code)
    except Exception as e:
        print(f"❌ [ERROR] Validation script failed: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
