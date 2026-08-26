"""Helpers for the dedicated throttle cache (Redis or DatabaseCache)."""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.cache import caches

logger = logging.getLogger(__name__)


def throttle_cache():
    return caches["throttle"]


def ensure_throttle_cache_table() -> None:
    """Create DatabaseCache table if throttle backend needs it (no-op for Redis)."""
    backend = settings.CACHES.get("throttle", {}).get("BACKEND", "")
    if "DatabaseCache" not in backend:
        return
    table = getattr(settings, "THROTTLE_CACHE_TABLE", "ghazatna_throttle_cache")
    try:
        from django.core.management import call_command

        call_command("createcachetable", table, verbosity=0)
    except Exception:
        # Table may already exist, or DB not ready during early import/migrate.
        logger.debug("createcachetable %s skipped/failed", table, exc_info=False)


def bump_counter(key: str, window_seconds: int) -> int:
    """Atomically-ish increment a counter; returns the new value."""
    cache = throttle_cache()
    try:
        added = cache.add(key, 1, window_seconds)
        if added:
            return 1
        try:
            return int(cache.incr(key))
        except ValueError:
            cache.set(key, 1, window_seconds)
            return 1
    except Exception:
        logger.warning("throttle bump failed for %s", key, exc_info=False)
        return 0
