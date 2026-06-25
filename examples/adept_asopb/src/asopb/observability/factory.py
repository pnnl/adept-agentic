"""Backend factory with plugin registry."""

from __future__ import annotations

from typing import Type

from .backends.base import BackendConfig, ObservabilityBackend


class BackendFactory:
    """Factory for creating observability backend instances.

    Supports registration of new backends at runtime:
        BackendFactory.register("custom", CustomBackend)
        backend = BackendFactory.create("custom", config={...})
    """

    _registry: dict[str, Type[ObservabilityBackend]] = {}

    @classmethod
    def register(cls, name: str, backend_class: Type[ObservabilityBackend]) -> None:
        """Register a backend class under a name."""
        cls._registry[name.lower()] = backend_class

    @classmethod
    def create(cls, name: str, config: dict | BackendConfig | None = None) -> ObservabilityBackend:
        """Create a backend instance by name.

        Args:
            name: Backend name (langfuse, aws, azure, gcp)
            config: Configuration dict or BackendConfig instance

        Returns:
            Configured ObservabilityBackend instance

        Raises:
            ValueError: If backend name is not registered
        """
        cls._ensure_defaults_registered()

        key = name.lower()
        if key not in cls._registry:
            available = ", ".join(sorted(cls._registry.keys()))
            raise ValueError(f"Unknown backend '{name}'. Available: {available}")

        if config is None:
            backend_config = BackendConfig()
        elif isinstance(config, dict):
            backend_config = BackendConfig(
                endpoint=config.get("endpoint", ""),
                public_key=config.get("public_key", ""),
                secret_key=config.get("secret_key", ""),
                region=config.get("region", ""),
                project=config.get("project", ""),
                timeout=config.get("timeout", 30),
                extra=config.get("extra", {}),
            )
        else:
            backend_config = config

        return cls._registry[key](backend_config)

    @classmethod
    def list_backends(cls) -> list[str]:
        """List all registered backend names."""
        cls._ensure_defaults_registered()
        return sorted(cls._registry.keys())

    @classmethod
    def _ensure_defaults_registered(cls) -> None:
        """Lazily register built-in backends on first use."""
        from .backends.aws_cloudwatch_backend import AWSCloudWatchBackend
        from .backends.azure_monitor_backend import AzureMonitorBackend
        from .backends.gcp_cloud_trace_backend import GCPCloudTraceBackend
        from .backends.langfuse_backend import LangfuseBackend

        cls._registry.setdefault("langfuse", LangfuseBackend)
        cls._registry.setdefault("aws", AWSCloudWatchBackend)
        cls._registry.setdefault("azure", AzureMonitorBackend)
        cls._registry.setdefault("gcp", GCPCloudTraceBackend)
