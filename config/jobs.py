from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable
import uuid

from django.core.cache import cache

logger = logging.getLogger(__name__)

# Cap workers so shared hosting (cPanel) does not exhaust process threads.
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ghazatna-job")
_JOB_TTL = 3600


def _job_key(job_id: str) -> str:
    return f"ghazatna:job:{job_id}"


def enqueue_job(name: str, func: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
    job_id = uuid.uuid4().hex
    cache.set(
        _job_key(job_id),
        {"id": job_id, "name": name, "status": "pending", "result": None, "error": None},
        _JOB_TTL,
    )

    def runner() -> None:
        cache.set(
            _job_key(job_id),
            {"id": job_id, "name": name, "status": "running", "result": None, "error": None},
            _JOB_TTL,
        )
        try:
            result = func(*args, **kwargs)
            cache.set(
                _job_key(job_id),
                {"id": job_id, "name": name, "status": "done", "result": result, "error": None},
                _JOB_TTL,
            )
        except Exception as exc:
            logger.exception("Background job failed: %s", name)
            cache.set(
                _job_key(job_id),
                {
                    "id": job_id,
                    "name": name,
                    "status": "failed",
                    "result": None,
                    "error": str(exc),
                },
                _JOB_TTL,
            )

    _executor.submit(runner)
    return job_id


def get_job_status(job_id: str) -> dict[str, Any] | None:
    return cache.get(_job_key(job_id))


def run_async(func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    """Run work off the request thread via a bounded pool (no unlimited Thread() spawn)."""

    def wrapper() -> None:
        try:
            func(*args, **kwargs)
        except Exception:
            logger.exception("Async task failed: %s", getattr(func, "__name__", "task"))

    try:
        _executor.submit(wrapper)
    except RuntimeError:
        # Pool shut down or host cannot create threads — skip rather than crash the worker.
        logger.warning(
            "Could not schedule async task %s (thread limit); skipping",
            getattr(func, "__name__", "task"),
        )
