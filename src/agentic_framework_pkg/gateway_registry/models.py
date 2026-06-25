"""
This module defines the SQLAlchemy database models for the Gateway Registry.
"""
from sqlalchemy import Column, String, JSON, DateTime
from sqlalchemy.sql import func
from .database import Base

class Gateway(Base):
    """
    SQLAlchemy model representing a registered Agent Gateway.

    Attributes:
        alias (str): The unique, human-readable alias for the gateway (Primary Key).
        public_url (str): The publicly accessible URL for A2A communication.
        internal_url (str): The internal network URL for local health checks.
        capabilities (JSON): A list of capabilities the gateway provides.
        health_status (str): The last known health status (e.g., "Healthy").
        last_health_check (DateTime): Timestamp of the last health check.
        created_at (DateTime): Timestamp of the initial registration.
        updated_at (DateTime): Timestamp of the last update.
    """
    __tablename__ = "gateways"

    alias = Column(String, primary_key=True, index=True)
    public_url = Column(String, nullable=False)
    internal_url = Column(String, nullable=True)
    capabilities = Column(JSON, nullable=True)
    health_status = Column(String, default="Unknown")
    last_health_check = Column(DateTime(timezone=True), onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
