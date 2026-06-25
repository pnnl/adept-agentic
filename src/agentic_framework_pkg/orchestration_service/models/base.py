"""
SQLAlchemy declarative base for orchestration service models.

This module provides the shared Base class for all ORM models in the
orchestration service. Separated into its own module to prevent circular
import dependencies.
"""

from sqlalchemy.orm import declarative_base

# Shared declarative base for all orchestration service models
Base = declarative_base()
