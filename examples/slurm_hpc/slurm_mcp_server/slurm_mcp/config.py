"""
SLURM Configuration Settings
============================

Environment-based configuration management for SLURM MCP server.
"""

import os
from typing import Dict, ClassVar
from pydantic import Field, ConfigDict
from pydantic_settings import BaseSettings


class SlurmConfig(BaseSettings):
    """
    SLURM MCP server configuration from environment variables.

    Environment variables:
        SLURM_API_URL: SLURM REST API base URL (e.g., http://slurmrestd:6820)
        SLURM_API_VERSION: SLURM API version (default: v0.0.41)
        SLURM_VERIFY_SSL: Whether to verify SSL certificates (default: false)
        SLURM_TIMEOUT: Request timeout in seconds (default: 30)
        SLURM_JWT_KEY: Base64-encoded HMAC key for JWT generation
        SLURM_SERVICE_JWT: Static JWT token (fallback if no HMAC key)
        SLURM_SERVICE_USER: Username for JWT token claims (default: root)
    """

    # Connection settings
    api_url: str = Field(
        default="http://slurmrestd:6820",
        description="SLURM REST API base URL",
    )
    api_version: str = Field(
        default="v0.0.41",
        description="SLURM API version",
    )
    verify_ssl: bool = Field(
        default=False,
        description="Whether to verify SSL certificates",
    )

    # Request settings
    timeout: int = Field(
        default=30,
        description="Request timeout in seconds",
    )

    # JWT settings (read directly from env, not via pydantic-settings prefix)
    jwt_key: str = Field(
        default="",
        description="Base64-encoded HMAC key for generating JWT tokens on-the-fly",
    )
    service_jwt: str = Field(
        default="",
        description="Static JWT token (fallback when HMAC key unavailable)",
    )
    service_user: str = Field(
        default="root",
        description="Username for JWT token claims",
    )

    # SPIFFE/SPIRE settings (opt-in via SPIFFE_ENABLED=true)
    spiffe_enabled: bool = Field(
        default=False,
        description="Enable SPIFFE/SPIRE workload identity (requires SPIRE agent)",
    )
    spiffe_endpoint_socket: str = Field(
        default="unix:///run/spire/sockets/agent.sock",
        description="SPIRE agent Workload API socket path",
    )
    spiffe_audience: str = Field(
        default="slurmrestd",
        description="JWT-SVID audience for slurmrestd authentication",
    )

    # State emojis for visual representation
    JOB_STATE_EMOJIS: ClassVar[Dict[str, str]] = {
        "RUNNING": "🏃",
        "PENDING": "⏳",
        "COMPLETED": "✅",
        "FAILED": "❌",
        "CANCELLED": "🚫",
        "TIMEOUT": "⏰",
        "NODE_FAIL": "💔",
        "PREEMPTED": "🔄",
        "SUSPENDED": "⏸️",
        "COMPLETING": "🏁",
        "CONFIGURING": "⚙️",
        "RESIZING": "📐",
        "REVOKED": "🚷",
        "SPECIAL_EXIT": "⚠️",
        "OUT_OF_MEMORY": "💾",
        "BOOT_FAIL": "🚨",
        "DEADLINE": "📅",
        "REQUEUED": "🔁",
        "RESV_DEL_HOLD": "🛑",
        "SIGNALING": "📡",
        "STAGE_OUT": "📤",
        "STOPPED": "🛑",
    }

    NODE_STATE_EMOJIS: ClassVar[Dict[str, str]] = {
        "IDLE": "🟢",
        "ALLOCATED": "🔵",
        "MIXED": "🟡",
        "DOWN": "🔴",
        "DRAIN": "🟠",
        "DRAINING": "🟠",
        "DRAINED": "🟠",
        "COMPLETING": "🟣",
        "NO_RESPOND": "⚫",
        "POWERED_DOWN": "💤",
        "FAIL": "❌",
        "FAILING": "❌",
        "MAINT": "🔧",
        "REBOOT": "♻️",
        "RESERVED": "🔒",
        "POWERING_UP": "⚡",
        "POWERING_DOWN": "🔌",
        "POWER_DOWN": "💤",
        "POWER_UP": "⚡",
        "FUTURE": "📅",
        "RESUME": "▶️",
        "UNDRAIN": "✅",
    }

    model_config = ConfigDict(
        env_prefix="SLURM_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


# Simple config instance
config = SlurmConfig()
