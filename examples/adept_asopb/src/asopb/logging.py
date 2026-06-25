"""
ASOPB Centralized Logging Configuration

All ASOPB modules should use:
    from asopb.logging import get_logger, timed
    logger = get_logger(__name__)

This ensures consistent formatting, level control, and future extensibility
(structured logging, JSON output, etc.) without changing individual modules.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import os
import sys
import time
from typing import Any, Callable

_CONFIGURED = False
_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _configure_root() -> None:
    """Configure the asopb root logger once."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    level_name = os.environ.get("ASOPB_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger("asopb")
    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
        root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Get a logger under the asopb namespace.

    Usage:
        from asopb.logging import get_logger
        logger = get_logger(__name__)
        logger.info("Processing %d files", count)

    The log level is controlled by ASOPB_LOG_LEVEL env var (default: INFO).
    """
    _configure_root()
    return logging.getLogger(name)


def timed(func: Callable = None, *, track_rss: bool = True) -> Callable:
    """Decorator that logs method entry, exit, elapsed time, and peak RSS.

    Works with both sync and async methods. Logs at INFO level with
    the method's module logger.

    Args:
        track_rss: Include RSS memory in log lines (default True on Linux).

    Usage:
        @timed
        async def _run_scanner(self, scanner_name, repo_path):
            ...

        @timed(track_rss=False)
        def lightweight_op():
            ...
    """
    def _decorator(fn: Callable) -> Callable:
        _logger = logging.getLogger(fn.__module__)

        def _rss_suffix() -> str:
            if not track_rss:
                return ""
            return f" [RSS={mem_mb()}MB]"

        if asyncio.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                sig_args = _format_args(args, kwargs)
                _logger.info(f"[START] {fn.__qualname__}({sig_args}){_rss_suffix()}")
                t0 = time.perf_counter()
                try:
                    result = await fn(*args, **kwargs)
                    elapsed = time.perf_counter() - t0
                    _logger.info(
                        f"[DONE]  {fn.__qualname__} — {elapsed:.3f}s{_rss_suffix()}"
                    )
                    return result
                except Exception as e:
                    elapsed = time.perf_counter() - t0
                    _logger.error(
                        f"[FAIL]  {fn.__qualname__} — {elapsed:.3f}s — "
                        f"{type(e).__name__}: {e}{_rss_suffix()}"
                    )
                    raise
            return async_wrapper
        else:
            @functools.wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                sig_args = _format_args(args, kwargs)
                _logger.info(f"[START] {fn.__qualname__}({sig_args}){_rss_suffix()}")
                t0 = time.perf_counter()
                try:
                    result = fn(*args, **kwargs)
                    elapsed = time.perf_counter() - t0
                    _logger.info(
                        f"[DONE]  {fn.__qualname__} — {elapsed:.3f}s{_rss_suffix()}"
                    )
                    return result
                except Exception as e:
                    elapsed = time.perf_counter() - t0
                    _logger.error(
                        f"[FAIL]  {fn.__qualname__} — {elapsed:.3f}s — "
                        f"{type(e).__name__}: {e}{_rss_suffix()}"
                    )
                    raise
            return sync_wrapper

    if func is not None:
        return _decorator(func)
    return _decorator


def mem_mb() -> int:
    """Current process peak RSS in MB (Linux)."""
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024


class MemoryMonitor:
    """Background thread that logs memory usage at regular intervals.

    Captures VmRSS from /proc/self/status (Linux). Logs at INFO level when
    RSS changes by more than threshold_mb, and always logs peak at shutdown.

    Usage:
        from asopb.logging import MemoryMonitor
        with MemoryMonitor(interval_s=5, threshold_mb=100):
            run_ml_inference(...)
    """

    def __init__(self, interval_s: float = 5.0, threshold_mb: int = 100):
        import resource as _resource
        import threading
        self._interval = interval_s
        self._threshold = threshold_mb
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._peak_mb = 0
        self._last_logged_mb = 0
        self._logger = logging.getLogger("asopb.memory")

    def _read_vm_rss(self) -> int:
        try:
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1]) // 1024
        except (OSError, ValueError):
            pass
        import resource as _resource
        return _resource.getrusage(_resource.RUSAGE_SELF).ru_maxrss // 1024

    def _monitor(self):
        while not self._stop.is_set():
            rss = self._read_vm_rss()
            if rss > self._peak_mb:
                self._peak_mb = rss
            if abs(rss - self._last_logged_mb) >= self._threshold:
                self._logger.info("RSS=%dMB (peak=%dMB)", rss, self._peak_mb)
                self._last_logged_mb = rss
            self._stop.wait(self._interval)

    def __enter__(self):
        import threading
        self._thread = threading.Thread(target=self._monitor, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._logger.info("Peak RSS: %dMB", self._peak_mb)

    @property
    def peak_mb(self) -> int:
        return self._peak_mb


def _format_args(args: tuple, kwargs: dict) -> str:
    """Format arguments for log output, skipping self and truncating long values."""
    parts = []
    for i, a in enumerate(args):
        if i == 0 and hasattr(a, '__class__'):
            continue
        s = repr(a)
        if len(s) > 80:
            s = s[:77] + "..."
        parts.append(s)
    for k, v in kwargs.items():
        s = repr(v)
        if len(s) > 80:
            s = s[:77] + "..."
        parts.append(f"{k}={s}")
    return ", ".join(parts)
