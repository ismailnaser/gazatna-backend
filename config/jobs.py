from __future__ import annotations

import logging
import uuid
from typing import Any, Callable

from django.core.cache import cache
from django.db import close_old_connections

logger = logging.getLogger(__name__)

_JOB_TTL = 3600


def _job_key(job_id: str) -> str:
    return f"ghazatna:job:{job_id}"


def enqueue_job(name: str, func: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
    """Run a named job inline.

    Shared hosting (CloudLinux NPROC) cannot safely use threads/processes.
    Threads count toward the process limit and crash Passenger with
    ``cagefs_enter: Unable to fork``.
    """
    job_id = uuid.uuid4().hex
    cache.set(
        _job_key(job_id),
        {"id": job_id, "name": name, "status": "running", "result": None, "error": None},
        _JOB_TTL,
    )
    close_old_connections()
    try:
        result = func(*args, **kwargs)
        cache.set(
            _job_key(job_id),
            {"id": job_id, "name": name, "status": "done", "result": result, "error": None},
            _JOB_TTL,
        )
        return job_id
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
        return job_id
    finally:
        close_old_connections()


def get_job_status(job_id: str) -> dict[str, Any] | None:
    return cache.get(_job_key(job_id))


def run_async(func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    """Compatibility wrapper — executes synchronously, never forks or threads."""
    close_old_connections()
    try:
        func(*args, **kwargs)
    except Exception:
        logger.exception("Task failed: %s", getattr(func, "__name__", "task"))
    finally:
        close_old_connections()
