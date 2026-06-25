"""Abstract base class for observability backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..models import GenerationRecord


@dataclass
class BackendConfig:
    """Configuration for an observability backend."""

    endpoint: str = ""
    public_key: str = ""
    secret_key: str = ""
    region: str = ""
    project: str = ""
    timeout: int = 30
    extra: dict[str, Any] = field(default_factory=dict)


class ObservabilityBackend(ABC):
    """Abstract base for token utilization data sources.

    Implementations must provide:
    - name: human-readable backend identifier
    - fetch_generations(): retrieve all LLM generation records
    - validate_config(): check that required credentials are present
    """

    def __init__(self, config: BackendConfig):
        self._config = config

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable backend name."""
        ...

    @abstractmethod
    def validate_config(self) -> None:
        """Validate backend configuration. Raises ValueError if invalid."""
        ...

    @abstractmethod
    def fetch_generations(self, page_limit: int = 50) -> list[GenerationRecord]:
        """Fetch all LLM generation records from the backend."""
        ...

    def test_connection(self) -> bool:
        """Test connectivity to the backend."""
        try:
            self.validate_config()
            self.fetch_generations(page_limit=1)
            return True
        except Exception:
            return False
