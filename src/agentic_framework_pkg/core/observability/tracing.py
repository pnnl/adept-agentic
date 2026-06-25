"""
Lightweight trace/span context managers for A2A observability.

TraceContext and SpanContext wrap Langfuse SDK calls, providing:
- No-op behavior when langfuse_client is None (tracing disabled)
- Idempotent end() via _ended flag
- Exception-safe __exit__ that never suppresses exceptions
- Timing via time.time() for duration_ms metrics

All Langfuse SDK calls are wrapped in try/except so that telemetry
never blocks or fails A2A execution. Failures are logged as warnings.
"""

import logging
import time

logger = logging.getLogger(__name__)


class SpanContext:
    """Wrapper around a backend span. No-op when tracing is disabled."""

    def __init__(self, backend_span=None, backend_cm=None, name=""):
        self._span = backend_span  # The actual span object (has .end(), .update())
        self._cm = backend_cm  # The context manager (has __exit__())
        self.name = name
        self._start_time = time.time()
        self._ended = False

    def update(self, *, output=None, metadata=None, level=None, status_message=None):
        if self._span is None or self._ended:
            return
        try:
            kwargs = {}
            if output is not None:
                kwargs["output"] = output
            if metadata is not None:
                kwargs["metadata"] = metadata
            if level is not None:
                kwargs["level"] = level
            if status_message is not None:
                kwargs["status_message"] = status_message
            if kwargs:
                self._span.update(**kwargs)
        except Exception as e:
            logger.warning("SpanContext(%s).update() failed: %s", self.name, e)

    def end(self, *, output=None, metadata=None, level=None, status_message=None) -> float:
        duration_ms = (time.time() - self._start_time) * 1000
        if self._ended:
            return duration_ms
        self._ended = True
        if self._span is not None:
            try:
                # Langfuse v3: update() accepts output/metadata/level/status_message,
                # but end() only accepts end_time.  Call update() first, then end().
                kwargs = {}
                if output is not None:
                    kwargs["output"] = output
                if metadata is not None:
                    kwargs["metadata"] = metadata
                if level is not None:
                    kwargs["level"] = level
                if status_message is not None:
                    kwargs["status_message"] = status_message
                if kwargs:
                    self._span.update(**kwargs)
                self._span.end()
            except Exception as e:
                logger.warning("SpanContext(%s).end() failed: %s", self.name, e)
            # Exit the context manager for proper cleanup
            if self._cm is not None:
                try:
                    self._cm.__exit__(None, None, None)
                except Exception:
                    pass  # Best-effort cleanup
        return duration_ms

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.end(level="ERROR", status_message=str(exc_val) if exc_val else None)
        else:
            self.end()
        return False  # Never suppress exceptions


class TraceContext:
    """Wrapper around a root trace with child span support."""

    def __init__(self, langfuse_client=None, name="", session_id=None, metadata=None):
        self._client = langfuse_client
        self._name = name
        self._session_id = session_id
        self._metadata = metadata or {}
        self._start_time = time.time()
        self._root_observation = None
        self._root_observation_cm = None
        self._propagate_ctx = None
        self._ended = False

    def start(self) -> "TraceContext":
        if self._client is None:
            return self
        try:
            from langfuse import propagate_attributes

            if self._session_id:
                self._propagate_ctx = propagate_attributes(session_id=self._session_id)
                self._propagate_ctx.__enter__()
            self._root_observation_cm = self._client.start_as_current_observation(
                as_type="span",
                name=self._name,
                metadata=self._metadata,
            )
            self._root_observation = self._root_observation_cm.__enter__()
        except Exception as e:
            logger.warning("TraceContext(%s).start() failed: %s", self._name, e)
        return self

    def span(self, name, *, input=None, metadata=None) -> SpanContext:
        if self._client is None:
            return SpanContext(backend_span=None, name=name)
        try:
            backend_span_cm = self._client.start_as_current_observation(
                as_type="span",
                name=name,
                input=input,
                metadata=metadata,
            )
            backend_span = backend_span_cm.__enter__()
            return SpanContext(backend_span=backend_span, backend_cm=backend_span_cm, name=name)
        except Exception as e:
            logger.warning("TraceContext(%s).span(%s) failed: %s", self._name, name, e)
            return SpanContext(backend_span=None, name=name)

    def update_session_id(self, session_id: str):
        """Update the trace session_id after creation (e.g., when mg-* is extracted from message).

        Also activates propagate_attributes so child spans inherit the session_id.
        """
        self._session_id = session_id
        if self._client is None:
            return
        try:
            self._client.update_current_trace(session_id=session_id)
        except Exception as e:
            logger.warning(
                "TraceContext(%s).update_session_id(%s) failed: %s",
                self._name, session_id, e,
            )
        # Activate propagate_attributes for subsequent child spans
        if self._propagate_ctx is None:
            try:
                from langfuse import propagate_attributes

                self._propagate_ctx = propagate_attributes(session_id=session_id)
                self._propagate_ctx.__enter__()
            except Exception as e:
                logger.warning(
                    "TraceContext(%s).update_session_id(%s) propagate_attributes failed: %s",
                    self._name, session_id, e,
                )

    def end(self, *, level=None, output=None, status_message=None) -> float:
        duration_ms = (time.time() - self._start_time) * 1000
        if self._ended:
            return duration_ms
        self._ended = True
        if self._root_observation_cm is not None:
            try:
                self._root_observation_cm.__exit__(None, None, None)
            except Exception as e:
                logger.warning("TraceContext(%s).end() root_observation exit failed: %s", self._name, e)
        if self._propagate_ctx is not None:
            try:
                self._propagate_ctx.__exit__(None, None, None)
            except Exception as e:
                logger.warning("TraceContext(%s).end() propagate_ctx exit failed: %s", self._name, e)
        return duration_ms

    def flush(self):
        if self._client is not None:
            try:
                self._client.flush()
            except Exception as e:
                logger.warning("TraceContext(%s).flush() failed: %s", self._name, e)

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None and self._root_observation_cm is not None:
            try:
                self._root_observation_cm.__exit__(exc_type, exc_val, exc_tb)
                self._root_observation_cm = None  # Prevent double-exit in end()
            except Exception as e:
                logger.warning("TraceContext(%s).__exit__() failed: %s", self._name, e)
        self.end()
        self.flush()
        return False  # Never suppress exceptions
