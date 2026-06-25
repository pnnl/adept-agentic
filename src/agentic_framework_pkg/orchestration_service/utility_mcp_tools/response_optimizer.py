"""
Response optimization utilities for session introspection tools.

Provides auto-export functionality when responses exceed context window limits,
with graceful warnings for medium-sized responses.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .token_validator import validate_response_size
from ...logger_config import get_logger

logger = get_logger(__name__)

# Default export directory
DEFAULT_EXPORT_DIR = "/app/data/exports"


def get_export_directory(category: str = "session_queries") -> Path:
    """
    Get export directory for a specific category.

    Creates directory if it doesn't exist.

    Args:
        category: Export category (session_queries, session_history, telemetry)

    Returns:
        Path to export directory
    """
    export_base = Path(os.getenv("EXPORT_BASE_DIR", DEFAULT_EXPORT_DIR))
    export_dir = export_base / category
    export_dir.mkdir(parents=True, exist_ok=True)
    return export_dir


def generate_export_filename(
    user_id: str, prefix: str = "export", extension: str = "json"
) -> str:
    """
    Generate timestamped export filename.

    Args:
        user_id: User ID for filename
        prefix: Filename prefix (default: export)
        extension: File extension (default: json)

    Returns:
        Filename string (e.g., "user123_20260124_093015.json")
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Sanitize user_id (remove special chars)
    safe_user_id = "".join(c if c.isalnum() else "_" for c in user_id)
    return f"{prefix}_{safe_user_id}_{timestamp}.{extension}"


def export_to_file(data: Any, filepath: Path, pretty: bool = True) -> Dict[str, Any]:
    """
    Export data to JSON file.

    Args:
        data: Data to export
        filepath: Path to export file
        pretty: Use pretty formatting (default: True)

    Returns:
        Dict with export status:
        {
            "success": bool,
            "filepath": str,
            "size_bytes": int,
            "error": Optional[str]
        }
    """
    try:
        with open(filepath, "w") as f:
            if pretty:
                json.dump(data, f, indent=2, default=str)
            else:
                json.dump(data, f, default=str)

        file_size = filepath.stat().st_size

        logger.info(f"Exported data to {filepath} ({file_size:,} bytes)")

        return {
            "success": True,
            "filepath": str(filepath),
            "size_bytes": file_size,
        }

    except Exception as e:
        logger.error(f"Failed to export data to {filepath}: {e}")
        return {
            "success": False,
            "filepath": str(filepath),
            "error": str(e),
        }


def create_summary_for_exported_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create summary statistics for exported data.

    Handles different data structures (sessions, history, telemetry).

    Args:
        data: Full data dictionary to summarize

    Returns:
        Summary dict with key statistics
    """
    summary = {}

    # Handle sessions data
    if "sessions" in data:
        sessions = data["sessions"]
        summary["total_sessions"] = len(sessions)

        # Token and cost aggregation
        total_tokens = sum(s.get("total_tokens", 0) for s in sessions)
        total_cost = sum(s.get("estimated_cost_usd", 0) for s in sessions)

        summary["total_tokens"] = total_tokens
        summary["total_cost_usd"] = round(total_cost, 4)

        # Date range
        dates = [
            s.get("created_at") or s.get("updated_at")
            for s in sessions
            if s.get("created_at") or s.get("updated_at")
        ]
        if dates:
            summary["date_range"] = {
                "earliest": min(dates),
                "latest": max(dates),
            }

    # Handle messages/history data
    elif "messages" in data:
        messages = data["messages"]
        summary["total_messages"] = len(messages)

        # Token aggregation
        total_tokens = sum(
            m.get("additional_kwargs", {}).get("usage", {}).get("total_tokens", 0)
            for m in messages
        )
        summary["total_tokens"] = total_tokens

        # Message type breakdown
        message_types = {}
        for msg in messages:
            msg_type = msg.get("type", "unknown")
            message_types[msg_type] = message_types.get(msg_type, 0) + 1
        summary["message_types"] = message_types

    # Handle telemetry data
    elif "traces" in data or "observations" in data:
        if "traces" in data:
            traces = data["traces"]
            summary["total_traces"] = len(traces)
        if "observations" in data:
            observations = data["observations"]
            summary["total_observations"] = len(observations)

        # Cost aggregation (if available)
        if "traces" in data:
            total_cost = sum(t.get("calculatedTotalCost", 0) for t in data["traces"])
            summary["total_cost_usd"] = round(total_cost, 4)

    return summary


async def optimize_response(
    data: Any,
    user_id: str,
    max_tokens: int = 100000,
    model: str = "gpt-4",
    category: str = "session_queries",
    export_prefix: str = "export",
) -> Dict[str, Any]:
    """
    Optimize response based on token size.

    Strategy:
    - Small (<50% max_tokens): Return data as-is
    - Medium (50-100% max_tokens): Return data with warning
    - Large (>100% max_tokens): Auto-export to file, return summary + path

    Args:
        data: Response data to optimize
        user_id: User ID for export filename
        max_tokens: Maximum token threshold (default: 100,000)
        model: Model identifier for token counting (default: gpt-4)
        category: Export category for directory organization
        export_prefix: Prefix for export filename

    Returns:
        Optimized response dict (either full data, or summary + export path)
    """
    # Validate response size
    validation = validate_response_size(data, max_tokens=max_tokens, model=model)

    token_count = validation["token_count"]
    size_category = validation["size_category"]
    should_export = validation["should_export"]
    should_warn = validation["should_warn"]
    warning_message = validation["warning_message"]

    # Small response - return as-is
    if size_category == "small":
        return {
            "success": True,
            "token_count": token_count,
            "max_tokens": max_tokens,
            **data,
        }

    # Medium response - return with warning
    elif size_category == "medium":
        return {
            "success": True,
            "warning": warning_message,
            "token_count": token_count,
            "max_tokens": max_tokens,
            "recommendation": validation["recommendation"],
            **data,
        }

    # Large response - auto-export
    elif should_export:
        # Generate export path
        export_dir = get_export_directory(category)
        filename = generate_export_filename(user_id, prefix=export_prefix)
        filepath = export_dir / filename

        # Export full data to file
        export_result = export_to_file(data, filepath)

        if not export_result["success"]:
            # Export failed - return data with error warning
            logger.error(f"Auto-export failed: {export_result.get('error')}")
            return {
                "success": False,
                "error": "Auto-export failed",
                "export_error": export_result.get("error"),
                "warning": warning_message,
                "token_count": token_count,
                "max_tokens": max_tokens,
                **data,  # Still return data despite export failure
            }

        # Create summary
        summary = create_summary_for_exported_data(data)

        # Return summary with export path
        return {
            "success": True,
            "auto_exported": True,
            "warning": warning_message,
            "token_count": token_count,
            "max_tokens": max_tokens,
            "export_path": str(filepath),
            "export_size_bytes": export_result["size_bytes"],
            "summary": summary,
            "message": (
                f"Response size ({token_count:,} tokens) exceeds context window "
                f"({max_tokens:,} tokens). Full results exported to file. "
                f"Use ExportSessionData tool or inspect file directly."
            ),
        }

    # Fallback (shouldn't reach here)
    return {
        "success": True,
        "token_count": token_count,
        "max_tokens": max_tokens,
        **data,
    }
