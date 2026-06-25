from typing import Optional
from sqlalchemy import Column, String, JSON, BigInteger
from sqlalchemy.orm import Mapped, mapped_column
from .models.base import Base

class Assistant(Base):
    __tablename__ = "assistants"

    id = Column(String, primary_key=True, index=True)
    created_at = Column(BigInteger)
    name = Column(String, nullable=True)
    description = Column(String, nullable=True)  # Note: use Mapped for SQLAlchemy 2.0 instead of Column(String, nullable=True)
    model = Column(String, nullable=False)
    instructions = Column(String, nullable=True)  # Note: use Mapped for SQLAlchemy 2.0 instead of Column(String, nullable=True)
    tools = Column(JSON, nullable=True)
    owner_id = Column(String, nullable=True)
    # OpenAI API compatibility fields
    file_ids = Column(JSON, nullable=True)  # Store as JSON array
    metadata_ = Column("metadata", JSON, nullable=True)  # Use column alias for reserved keyword

class Run(Base):
    __tablename__ = "runs"

    id = Column(String, primary_key=True, index=True)
    thread_id = Column(String, nullable=False)
    assistant_id = Column(String, nullable=False)
    status = Column(String, nullable=False)
    created_at = Column(BigInteger)
    model = Column(String, nullable=True)
    instructions = Column(String, nullable=True) #Mapped[Optional[str]]  # Note: use Mapped for SQLAlchemy 2.0 instead of Column(String, nullable=True)
    tools = Column(JSON, nullable=True)
    metadata_ = Column("metadata", JSON, nullable=True)
    owner_id = Column(String, nullable=True)

class RunStep(Base):
    __tablename__ = "run_steps"

    id = Column(String, primary_key=True, index=True)
    run_id = Column(String, nullable=False)
    thread_id = Column(String, nullable=False)
    assistant_id = Column(String, nullable=False)
    status = Column(String, nullable=False)
    step_details = Column(JSON, nullable=False)
    last_error = Column(JSON, nullable=True)
    created_at = Column(BigInteger)
    completed_at = Column(BigInteger, nullable=True)
    failed_at = Column(BigInteger, nullable=True)
    cancelled_at = Column(BigInteger, nullable=True)
    expires_at = Column(BigInteger, nullable=True)
    metadata_ = Column("metadata", JSON, nullable=True)
    owner_id = Column(String, nullable=True)
