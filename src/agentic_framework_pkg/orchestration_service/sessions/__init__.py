"""
Session management module.

This module provides session lifecycle management including:
- Retention policy parsing
- Session CRUD operations
- Export functionality
"""

from .retention_policy import RetentionPolicy, RetentionPolicyError

__all__ = ["RetentionPolicy", "RetentionPolicyError"]
