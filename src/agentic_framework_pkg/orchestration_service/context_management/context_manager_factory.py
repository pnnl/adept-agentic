"""Factory for creating context manager instances based on configuration mode.

Singleton pattern ensures consistent mode selection across service lifetime.

Supported Modes:
- "simple": Fast buffer layer (context_manager.py wrapper)
- "advanced": Intelligent tracker (context_window_manager.py wrapper)
- "hybrid": Future dual-layer implementation (Phase 3+)

Environment Configuration:
    CONTEXT_MANAGEMENT_MODE=simple|advanced|hybrid  (default: simple)

Usage:
    # Get factory instance (singleton)
    factory = ContextManagerFactory()

    # Create context manager with default mode
    manager = factory.create()

    # Create with explicit mode
    manager = factory.create(mode="advanced")

    # Inspect current mode
    print(factory.get_current_mode())  # "simple"

Author: Session 34 Implementation Team
Date: 2026-01-19
"""

import os
from typing import Optional, Dict, Any

from .base_context_manager import BaseContextManager
from .config import ContextManagementMode

# Import adapters (will be created next)
# Lazy imports to avoid circular dependencies
from .adapters.simple_adapter import SimpleContextManagerAdapter
from .adapters.advanced_adapter import AdvancedContextManagerAdapter
from .adapters.hybrid_adapter import HybridContextManagerAdapter
from ...logger_config import get_logger


logger = get_logger(__name__)


class ContextManagerFactory:
    """
    Singleton factory for creating context manager instances.

    Design:
    - Singleton ensures consistent mode selection across service lifetime
    - Mode determined by CONTEXT_MANAGEMENT_MODE env var at initialization
    - Validates mode at startup with clear error messages
    - Logs mode selection for observability
    - Thread-safe singleton implementation

    Singleton Behavior:
    - First call to __new__ creates the singleton instance
    - Subsequent calls return the same instance
    - Initialization (_initialize) only runs once
    - Mode is determined once at first instantiation

    Example:
        >>> # First instantiation
        >>> factory1 = ContextManagerFactory()
        >>> factory1.get_current_mode()
        'simple'
        >>>
        >>> # Second instantiation (returns same instance)
        >>> factory2 = ContextManagerFactory()
        >>> factory1 is factory2
        True
        >>>
        >>> # Create managers
        >>> simple_mgr = factory1.create(mode="simple")
        >>> advanced_mgr = factory1.create(mode="advanced")
    """

    _instance: Optional["ContextManagerFactory"] = None
    _default_mode: Optional[ContextManagementMode] = None
    _initialized: bool = False

    def __new__(cls):
        """
        Singleton implementation (thread-safe).

        Returns:
            The singleton ContextManagerFactory instance
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """
        Initialize factory (only runs once due to singleton pattern).

        Reads CONTEXT_MANAGEMENT_MODE env var and validates it.
        Logs initialization for observability.
        """
        # Only initialize once (singleton pattern)
        if not self._initialized:
            self._initialize()
            self.__class__._initialized = True

    def _initialize(self) -> None:
        """
        Initialize factory with default mode from environment.

        Called once during first instantiation.
        Reads CONTEXT_MANAGEMENT_MODE env var (defaults to "simple").
        Validates mode and logs initialization.
        """
        mode_str = os.getenv("CONTEXT_MANAGEMENT_MODE", "simple").lower()

        try:
            self._default_mode = ContextManagementMode(mode_str)
            logger.info(
                f"[CONTEXT_FACTORY] Initialized with mode: {self._default_mode.value}"
            )
        except ValueError:
            valid_modes = ", ".join([m.value for m in ContextManagementMode])
            logger.error(
                f"[CONTEXT_FACTORY] Invalid mode '{mode_str}'. "
                f"Valid modes: {valid_modes}. Defaulting to 'simple'."
            )
            self._default_mode = ContextManagementMode.SIMPLE

    def create(
        self, mode: Optional[str] = None, checkpointer=None, **kwargs
    ) -> BaseContextManager:
        """
        Create a context manager instance.

        Args:
            mode: Override mode (uses default if None).
                  Valid values: "simple", "advanced", "hybrid"
            checkpointer: LangGraph checkpointer instance (optional).
                          If provided, will be passed to adapter constructor.
            **kwargs: Additional arguments passed to adapter constructor.
                      Reserved for future use (e.g., custom configurations).

        Returns:
            BaseContextManager instance (adapter subclass):
            - SimpleContextManagerAdapter for mode="simple"
            - AdvancedContextManagerAdapter for mode="advanced"
            - HybridContextManagerAdapter for mode="hybrid" (Phase 3+)

        Raises:
            ValueError: If mode is invalid (not in ContextManagementMode enum)
            NotImplementedError: If mode is not yet implemented (e.g., "hybrid" in Phase 1)

        Example:
            >>> factory = ContextManagerFactory()
            >>>
            >>> # Use default mode (from env var)
            >>> manager = factory.create()
            >>> manager.get_mode()
            'simple'
            >>>
            >>> # Override mode
            >>> manager = factory.create(mode="advanced")
            >>> manager.get_mode()
            'advanced'
            >>>
            >>> # With checkpointer
            >>> from agentic_framework_pkg.orchestration_service.persistence import AsyncPostgresSaver
            >>> checkpointer = AsyncPostgresSaver()
            >>> manager = factory.create(mode="simple", checkpointer=checkpointer)
        """
        # Determine effective mode
        if mode is None:
            effective_mode = self._default_mode
        else:
            try:
                effective_mode = ContextManagementMode(mode.lower())
            except ValueError:
                valid_modes = ", ".join([m.value for m in ContextManagementMode])
                raise ValueError(
                    f"Invalid mode: '{mode}'. Valid modes: {valid_modes}"
                )

        # Log creation
        logger.debug(
            f"[CONTEXT_FACTORY] Creating manager with mode: {effective_mode.value}"
        )

        # Create adapter based on mode
        if effective_mode == ContextManagementMode.SIMPLE:
            return SimpleContextManagerAdapter(checkpointer=checkpointer, **kwargs)
        elif effective_mode == ContextManagementMode.ADVANCED:
            return AdvancedContextManagerAdapter(checkpointer=checkpointer, **kwargs)
        elif effective_mode == ContextManagementMode.HYBRID:
            # Phase 1: Not implemented yet
            raise NotImplementedError(
                "Hybrid mode is not available in Phase 1. "
                "Use 'simple' or 'advanced' mode. "
                "Hybrid mode will be available in Phase 3+. "
                "See docs/implementation-plans/SESSION_34_PHASE1_CONTEXT_MANAGEMENT_FACTORY_PATTERN.md "
                "for roadmap details."
            )
        else:
            # Should never reach here due to enum validation
            raise ValueError(f"Unknown mode: {effective_mode}")

    def get_current_mode(self) -> str:
        """
        Get the current default mode.

        Returns:
            Mode string: "simple", "advanced", or "hybrid"

        Example:
            >>> factory = ContextManagerFactory()
            >>> factory.get_current_mode()
            'simple'
        """
        return self._default_mode.value

    def get_available_modes(self) -> list:
        """
        Get list of all available modes.

        Returns:
            List of mode strings

        Example:
            >>> factory = ContextManagerFactory()
            >>> factory.get_available_modes()
            ['simple', 'advanced', 'hybrid']
        """
        return [m.value for m in ContextManagementMode]

    def get_implemented_modes(self) -> list:
        """
        Get list of currently implemented modes (Phase 1).

        Returns:
            List of implemented mode strings

        Example:
            >>> factory = ContextManagerFactory()
            >>> factory.get_implemented_modes()
            ['simple', 'advanced']
        """
        # Phase 1: Only simple and advanced are implemented
        return ["simple", "advanced"]

    def is_mode_available(self, mode: str) -> bool:
        """
        Check if a mode is currently available (implemented).

        Args:
            mode: Mode string to check

        Returns:
            True if mode is implemented, False otherwise

        Example:
            >>> factory = ContextManagerFactory()
            >>> factory.is_mode_available("simple")
            True
            >>> factory.is_mode_available("hybrid")
            False  # Phase 1 only
        """
        return mode.lower() in self.get_implemented_modes()

    def get_implementation_info(self) -> Dict[str, Any]:
        """
        Get factory metadata.

        Returns:
            Dict with keys:
            - default_mode: Current default mode
            - available_modes: List of all defined modes
            - implemented_modes: List of currently implemented modes
            - env_var: Environment variable name for configuration
            - phase: Current implementation phase (1)
            - version: Factory version string

        Example:
            >>> factory = ContextManagerFactory()
            >>> info = factory.get_implementation_info()
            >>> info['default_mode']
            'simple'
            >>> info['implemented_modes']
            ['simple', 'advanced']
            >>> info['phase']
            1
        """
        return {
            "default_mode": self._default_mode.value,
            "available_modes": self.get_available_modes(),
            "implemented_modes": self.get_implemented_modes(),
            "env_var": "CONTEXT_MANAGEMENT_MODE",
            "phase": 1,
            "version": "1.0.0",
        }

    def __repr__(self) -> str:
        """
        String representation for debugging.

        Returns:
            String with factory info

        Example:
            >>> repr(factory)
            '<ContextManagerFactory default_mode=simple phase=1>'
        """
        return f"<ContextManagerFactory default_mode={self._default_mode.value} phase=1>"

    def __str__(self) -> str:
        """
        Human-readable string representation.

        Returns:
            String with factory info

        Example:
            >>> str(factory)
            'ContextManagerFactory(mode=simple, implemented=[simple, advanced])'
        """
        implemented = ", ".join(self.get_implemented_modes())
        return (
            f"ContextManagerFactory(mode={self._default_mode.value}, "
            f"implemented=[{implemented}])"
        )
