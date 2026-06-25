"""Unit tests for backend factory."""

import pytest

from asopb.observability.factory import BackendFactory
from asopb.observability.backends.base import BackendConfig, ObservabilityBackend
from asopb.observability.models import GenerationRecord


class TestBackendFactory:
    def setup_method(self):
        BackendFactory._registry = {}

    def test_list_backends(self):
        backends = BackendFactory.list_backends()
        assert "langfuse" in backends
        assert "aws" in backends
        assert "azure" in backends
        assert "gcp" in backends

    def test_create_langfuse(self):
        backend = BackendFactory.create("langfuse", {
            "endpoint": "http://localhost:3001",
            "public_key": "pk-test",
            "secret_key": "sk-test",
        })
        assert backend.name == "Langfuse"

    def test_create_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown backend"):
            BackendFactory.create("nonexistent")

    def test_create_with_backend_config(self):
        config = BackendConfig(
            endpoint="http://localhost:3001",
            public_key="pk-test",
            secret_key="sk-test",
        )
        backend = BackendFactory.create("langfuse", config)
        assert backend.name == "Langfuse"

    def test_register_custom_backend(self):
        class CustomBackend(ObservabilityBackend):
            @property
            def name(self) -> str:
                return "Custom"

            def validate_config(self) -> None:
                pass

            def fetch_generations(self, page_limit=50) -> list[GenerationRecord]:
                return []

        BackendFactory._registry = {}
        BackendFactory._ensure_defaults_registered()
        BackendFactory.register("custom", CustomBackend)
        backend = BackendFactory.create("custom")
        assert backend.name == "Custom"

    def test_case_insensitive_lookup(self):
        backend = BackendFactory.create("LANGFUSE", {
            "endpoint": "http://localhost:3001",
            "public_key": "pk-test",
            "secret_key": "sk-test",
        })
        assert backend.name == "Langfuse"
