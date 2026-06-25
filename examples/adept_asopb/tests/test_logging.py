"""Tests for asopb.logging module.

Covers: get_logger, timed (sync/async, RSS tracking), mem_mb, MemoryMonitor.
"""

from __future__ import annotations

import asyncio
import logging
import logging.handlers
import time
import threading
from unittest.mock import patch, MagicMock

import pytest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from asopb.logging import get_logger, timed, mem_mb, MemoryMonitor


class TestGetLogger:
    def test_returns_logger(self):
        logger = get_logger("test.module")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test.module"

    def test_idempotent_configuration(self):
        get_logger("a")
        get_logger("b")
        root = logging.getLogger("asopb")
        assert len(root.handlers) <= 1


class TestMemMb:
    def test_returns_int(self):
        result = mem_mb()
        assert isinstance(result, int)

    def test_positive_value(self):
        assert mem_mb() > 0

    def test_reasonable_range(self):
        rss = mem_mb()
        assert rss < 50000  # less than 50GB


class TestTimedSync:
    def test_basic_timing(self, caplog):
        @timed
        def add(a, b):
            return a + b

        with caplog.at_level(logging.INFO):
            result = add(1, 2)

        assert result == 3
        assert "[START]" in caplog.text
        assert "[DONE]" in caplog.text
        assert "add" in caplog.text

    def test_rss_tracking_default(self, caplog):
        @timed
        def noop():
            pass

        with caplog.at_level(logging.INFO):
            noop()

        assert "RSS=" in caplog.text

    def test_rss_tracking_disabled(self, caplog):
        @timed(track_rss=False)
        def noop():
            pass

        with caplog.at_level(logging.INFO):
            noop()

        assert "RSS=" not in caplog.text

    def test_exception_logging(self, caplog):
        @timed
        def fail():
            raise ValueError("test error")

        with caplog.at_level(logging.INFO):
            with pytest.raises(ValueError, match="test error"):
                fail()

        assert "[FAIL]" in caplog.text
        assert "ValueError" in caplog.text

    def test_elapsed_time(self, caplog):
        @timed
        def slow():
            time.sleep(0.05)

        with caplog.at_level(logging.INFO):
            slow()

        assert "0.0" in caplog.text  # at least 0.05s shows as 0.0xx


class TestTimedAsync:
    @pytest.mark.asyncio
    async def test_async_basic(self, caplog):
        @timed
        async def async_add(a, b):
            return a + b

        with caplog.at_level(logging.INFO):
            result = await async_add(1, 2)

        assert result == 3
        assert "[START]" in caplog.text
        assert "[DONE]" in caplog.text

    @pytest.mark.asyncio
    async def test_async_exception(self, caplog):
        @timed
        async def async_fail():
            raise RuntimeError("async error")

        with caplog.at_level(logging.INFO):
            with pytest.raises(RuntimeError, match="async error"):
                await async_fail()

        assert "[FAIL]" in caplog.text
        assert "RuntimeError" in caplog.text

    @pytest.mark.asyncio
    async def test_async_rss_disabled(self, caplog):
        @timed(track_rss=False)
        async def async_noop():
            pass

        with caplog.at_level(logging.INFO):
            await async_noop()

        assert "RSS=" not in caplog.text


class TestMemoryMonitor:
    def test_context_manager_basic(self):
        with MemoryMonitor(interval_s=0.1, threshold_mb=0) as mon:
            time.sleep(0.15)
        assert mon.peak_mb > 0

    def test_peak_mb_property(self):
        with MemoryMonitor(interval_s=0.05, threshold_mb=0) as mon:
            time.sleep(0.1)
        assert isinstance(mon.peak_mb, int)
        assert mon.peak_mb > 0

    def test_thread_stops_on_exit(self):
        with MemoryMonitor(interval_s=0.05) as mon:
            assert mon._thread is not None
            assert mon._thread.is_alive()
        time.sleep(0.1)
        assert not mon._thread.is_alive()

    def test_threshold_logging(self):
        handler = logging.handlers.MemoryHandler(capacity=100)
        logger = logging.getLogger("asopb.memory")
        logger.addHandler(handler)
        try:
            with MemoryMonitor(interval_s=0.05, threshold_mb=0) as mon:
                time.sleep(0.15)
            messages = [h.getMessage() for h in handler.buffer]
            assert any("RSS=" in m for m in messages)
        finally:
            logger.removeHandler(handler)

    def test_peak_logged_on_exit(self):
        handler = logging.handlers.MemoryHandler(capacity=100)
        logger = logging.getLogger("asopb.memory")
        logger.addHandler(handler)
        try:
            with MemoryMonitor(interval_s=0.05, threshold_mb=9999) as mon:
                time.sleep(0.1)
            messages = [h.getMessage() for h in handler.buffer]
            assert any("Peak RSS:" in m for m in messages)
        finally:
            logger.removeHandler(handler)
