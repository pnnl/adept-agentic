#!/usr/bin/env python3
"""
CLI tool for managing stuck runs in the orchestration service.

This tool helps developers identify and clean up stuck runs that may occur
due to checkpoint versioning issues, agent execution failures, or other
system problems.

Usage:
    python -m agentic_framework_pkg.orchestration_service.cli.manage_runs --help
    python -m agentic_framework_pkg.orchestration_service.cli.manage_runs list-stuck
    python -m agentic_framework_pkg.orchestration_service.cli.manage_runs clean-stuck --confirm
    python -m agentic_framework_pkg.orchestration_service.cli.manage_runs show-run <run_id>
"""
import asyncio
import os
import sys
import argparse
from typing import List, Dict, Any
import psycopg2
from datetime import datetime, timezone

from ...logger_config import get_logger

logger = get_logger(__name__)

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://admin:password@localhost:5432/agentic_orchestrator")


def get_db_connection():
    """Get a database connection."""
    # Parse DATABASE_URL to get connection parameters
    if DATABASE_URL.startswith("postgresql+asyncpg://"):
        db_url = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    else:
        db_url = DATABASE_URL
        
    return psycopg2.connect(db_url)


def list_runs(status_filter: str = None) -> List[Dict[str, Any]]:
    """List runs, optionally filtered by status."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if status_filter:
            cursor.execute(
                "SELECT id, thread_id, assistant_id, status, created_at, model FROM runs WHERE status = %s ORDER BY created_at DESC LIMIT 20",
                (status_filter,)
            )
        else:
            cursor.execute(
                "SELECT id, thread_id, assistant_id, status, created_at, model FROM runs ORDER BY created_at DESC LIMIT 20"
            )
        
        runs = []
        for row in cursor.fetchall():
            runs.append({
                "id": row[0],
                "thread_id": row[1], 
                "assistant_id": row[2],
                "status": row[3],
                "created_at": datetime.fromtimestamp(row[4], timezone.utc) if row[4] else None,
                "model": row[5]
            })
        
        return runs
    finally:
        cursor.close()
        conn.close()


def list_stuck_runs(max_age_hours: int = 1) -> List[Dict[str, Any]]:
    """List runs that appear to be stuck (in queued/in_progress for too long)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Get runs that have been queued or in_progress for more than max_age_hours
        current_timestamp = int(datetime.now(timezone.utc).timestamp())
        cutoff_timestamp = current_timestamp - (max_age_hours * 3600)
        
        cursor.execute("""
            SELECT id, thread_id, assistant_id, status, created_at, model 
            FROM runs 
            WHERE status IN ('queued', 'in_progress') 
            AND created_at < %s 
            ORDER BY created_at ASC
        """, (cutoff_timestamp,))
        
        stuck_runs = []
        for row in cursor.fetchall():
            stuck_runs.append({
                "id": row[0],
                "thread_id": row[1],
                "assistant_id": row[2], 
                "status": row[3],
                "created_at": datetime.fromtimestamp(row[4], timezone.utc) if row[4] else None,
                "model": row[5],
                "age_hours": (current_timestamp - row[4]) / 3600 if row[4] else None
            })
        
        return stuck_runs
    finally:
        cursor.close()
        conn.close()


def get_run_details(run_id: str) -> Dict[str, Any]:
    """Get detailed information about a specific run."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Get run details
        cursor.execute(
            "SELECT * FROM runs WHERE id = %s",
            (run_id,)
        )
        run_row = cursor.fetchone()
        
        if not run_row:
            return {"error": f"Run {run_id} not found"}
        
        # Get column names
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'runs' ORDER BY ordinal_position")
        columns = [row[0] for row in cursor.fetchall()]
        
        run_data = dict(zip(columns, run_row))
        
        # Get run steps
        cursor.execute(
            "SELECT id, status, step_details, created_at, completed_at, failed_at FROM run_steps WHERE run_id = %s ORDER BY created_at",
            (run_id,)
        )
        steps = []
        for step_row in cursor.fetchall():
            steps.append({
                "id": step_row[0],
                "status": step_row[1],
                "step_details": step_row[2],
                "created_at": datetime.fromtimestamp(step_row[3], timezone.utc) if step_row[3] else None,
                "completed_at": datetime.fromtimestamp(step_row[4], timezone.utc) if step_row[4] else None,
                "failed_at": datetime.fromtimestamp(step_row[5], timezone.utc) if step_row[5] else None,
            })
        
        # Get checkpoint info
        cursor.execute(
            "SELECT thread_id, checkpoint_id, parent_checkpoint_id FROM checkpoints WHERE thread_id = %s ORDER BY checkpoint_id DESC LIMIT 1",
            (run_data["thread_id"],)
        )
        checkpoint_row = cursor.fetchone()
        checkpoint_info = None
        if checkpoint_row:
            checkpoint_info = {
                "thread_id": checkpoint_row[0],
                "checkpoint_id": checkpoint_row[1],
                "parent_checkpoint_id": checkpoint_row[2],
            }
        
        return {
            "run": run_data,
            "steps": steps,
            "checkpoint": checkpoint_info
        }
    finally:
        cursor.close()
        conn.close()


def delete_run(run_id: str) -> bool:
    """Delete a run and its associated steps."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Delete run steps first (foreign key constraint)
        cursor.execute("DELETE FROM run_steps WHERE run_id = %s", (run_id,))
        steps_deleted = cursor.rowcount
        
        # Delete the run
        cursor.execute("DELETE FROM runs WHERE id = %s", (run_id,))
        run_deleted = cursor.rowcount
        
        conn.commit()
        
        logger.info(f"Deleted run {run_id}: {run_deleted} run, {steps_deleted} steps")
        return run_deleted > 0
    except Exception as e:
        conn.rollback()
        logger.error(f"Error deleting run {run_id}: {e}")
        return False
    finally:
        cursor.close()
        conn.close()


def clean_stuck_runs(max_age_hours: int = 1, confirm: bool = False) -> int:
    """Clean up stuck runs that are older than max_age_hours."""
    stuck_runs = list_stuck_runs(max_age_hours)
    
    if not stuck_runs:
        logger.info(f"No stuck runs found (older than {max_age_hours} hours)")
        return 0

    logger.info(f"Found {len(stuck_runs)} stuck runs:")
    for run in stuck_runs:
        logger.info(f"  {run['id']} - {run['status']} - {run['age_hours']:.1f}h old")

    if not confirm:
        logger.info("Use --confirm to actually delete these runs")
        return 0

    deleted_count = 0
    for run in stuck_runs:
        if delete_run(run['id']):
            deleted_count += 1

    logger.info(f"Deleted {deleted_count} stuck runs")
    return deleted_count


def main():
    parser = argparse.ArgumentParser(description="Manage orchestration service runs")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # List runs command
    list_parser = subparsers.add_parser("list", help="List recent runs")
    list_parser.add_argument("--status", help="Filter by status (queued, in_progress, completed, failed)")
    
    # List stuck runs command  
    stuck_parser = subparsers.add_parser("list-stuck", help="List stuck runs")
    stuck_parser.add_argument("--max-age", type=int, default=1, help="Max age in hours to consider stuck (default: 1)")
    
    # Show run details command
    show_parser = subparsers.add_parser("show-run", help="Show detailed run information")
    show_parser.add_argument("run_id", help="Run ID to show")
    
    # Clean stuck runs command
    clean_parser = subparsers.add_parser("clean-stuck", help="Clean up stuck runs")
    clean_parser.add_argument("--max-age", type=int, default=1, help="Max age in hours to consider stuck (default: 1)")
    clean_parser.add_argument("--confirm", action="store_true", help="Actually delete the runs (required)")
    
    # Delete specific run command
    delete_parser = subparsers.add_parser("delete-run", help="Delete a specific run")
    delete_parser.add_argument("run_id", help="Run ID to delete")
    delete_parser.add_argument("--confirm", action="store_true", help="Confirm deletion (required)")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    try:
        if args.command == "list":
            runs = list_runs(args.status)
            if runs:
                logger.info(f"{'ID':<40} {'Status':<12} {'Age':<20} {'Model':<20}")
                logger.info("-" * 100)
                for run in runs:
                    age = "Unknown"
                    if run['created_at']:
                        age_delta = datetime.now(timezone.utc) - run['created_at']
                        if age_delta.total_seconds() < 3600:
                            age = f"{age_delta.total_seconds()/60:.1f}m"
                        else:
                            age = f"{age_delta.total_seconds()/3600:.1f}h"
                    logger.info(f"{run['id']:<40} {run['status']:<12} {age:<20} {run['model'] or 'N/A':<20}")
            else:
                logger.info("No runs found")
                
        elif args.command == "list-stuck":
            stuck_runs = list_stuck_runs(args.max_age)
            if stuck_runs:
                logger.info(f"{'ID':<40} {'Status':<12} {'Age (hours)':<12} {'Model':<20}")
                logger.info("-" * 90)
                for run in stuck_runs:
                    age_str = f"{run['age_hours']:.1f}h" if run['age_hours'] else "Unknown"
                    logger.info(f"{run['id']:<40} {run['status']:<12} {age_str:<12} {run['model'] or 'N/A':<20}")
                logger.info(f"Found {len(stuck_runs)} stuck runs (older than {args.max_age}h)")
            else:
                logger.info(f"No stuck runs found (older than {args.max_age} hours)")
                
        elif args.command == "show-run":
            details = get_run_details(args.run_id)
            if "error" in details:
                logger.error(f"Run not found: {details['error']}")
                return 1

            run = details["run"]
            logger.info(f"Run Details for {args.run_id}:")
            logger.info(f"  Thread ID: {run['thread_id']}")
            logger.info(f"  Assistant ID: {run['assistant_id']}")
            logger.info(f"  Status: {run['status']}")
            logger.info(f"  Model: {run['model']}")
            logger.info(f"  Created: {datetime.fromtimestamp(run['created_at'], timezone.utc) if run['created_at'] else 'Unknown'}")

            if details["steps"]:
                logger.info(f"Run Steps ({len(details['steps'])}):")
                for step in details["steps"]:
                    logger.info(f"  {step['id']}: {step['status']} - {step['created_at']}")
            else:
                logger.info("No run steps found")
                
            if details["checkpoint"]:
                cp = details["checkpoint"]
                logger.info("Checkpoint Info:")
                logger.info(f"  Thread ID: {cp['thread_id']}")
                logger.info(f"  Checkpoint ID: {cp['checkpoint_id']}")
                logger.info(f"  Parent: {cp['parent_checkpoint_id']}")
            else:
                logger.info("No checkpoint found")
                
        elif args.command == "clean-stuck":
            clean_stuck_runs(args.max_age, args.confirm)
            
        elif args.command == "delete-run":
            if not args.confirm:
                logger.info("Use --confirm to actually delete the run")
                return 1
            if delete_run(args.run_id):
                logger.info(f"Deleted run {args.run_id}")
            else:
                logger.error(f"Failed to delete run {args.run_id}")
                return 1

        return 0

    except Exception as e:
        logger.error(f"Error executing command: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())