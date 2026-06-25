"""Shared ProcessPoolExecutor for sandbox code execution.

Provides true process-level parallelism for the Python-side orchestration of
llm-sandbox sessions (Docker connection setup, result marshaling, file copying).
Each execution gets its own process with independent memory and no GIL contention.

Lazy initialization ensures the pool is only created when first needed,
which is safe for forked uvicorn workers -- each worker gets its own pool.

Configuration:
    SANDBOX_PROCESS_POOL_WORKERS: Number of worker processes (default: 4)
"""

import os
from concurrent.futures import ProcessPoolExecutor

_executor: ProcessPoolExecutor | None = None

SANDBOX_PROCESS_POOL_WORKERS = int(os.getenv("SANDBOX_PROCESS_POOL_WORKERS", "4"))


def get_process_pool() -> ProcessPoolExecutor:
    """Get or create the module-level ProcessPoolExecutor singleton."""
    global _executor
    if _executor is None:
        _executor = ProcessPoolExecutor(max_workers=SANDBOX_PROCESS_POOL_WORKERS)
    return _executor


def shutdown_process_pool():
    """Shutdown the ProcessPoolExecutor if it was created."""
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False)
        _executor = None
