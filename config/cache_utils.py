from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

from django.core.cache import cache

DEFAULT_TTL = 300  # 5 minutes
PUBLIC_TTL = 600  # 10 minutes
ANALYTICS_TTL = 120  # 2 minutes
# Version keys must outlive content TTLs and survive file-cache cull pressure.
VERSION_TTL = 60 * 60 * 24 * 30  # 30 days

# Only these GET params may participate in public list cache keys.
# Prevents unbounded ?x=1,?x=2 spam from filling the 400-slot file cache.
_ALLOWED_QUERY_PARAMS = frozenset(
    {
        "category",
        "featured",
        "status",
        "gradeLevel",
        "from",
        "to",
        "section",
        "page",
        "classId",
        "classIds",
        "subject",
        "termId",
        "yearId",
        "tab",
    }
)


def make_cache_key(*parts: str) -> str:
    raw = ":".join(str(p) for p in parts if p is not None)
    return f"ghazatna:{raw}"


def cache_get(key: str) -> Any | None:
    return cache.get(key)


def cache_set(key: str, value: Any, ttl: int = DEFAULT_TTL) -> None:
    cache.set(key, value, ttl)


def cache_delete(key: str) -> None:
    cache.delete(key)


def cache_delete_many(keys: list[str]) -> None:
    if keys:
        cache.delete_many(keys)


def invalidate_prefix(prefix: str) -> None:
    version_key = make_cache_key("version", prefix)
    current = cache.get(version_key, 0)
    cache.set(version_key, int(current) + 1, VERSION_TTL)


def versioned_key(prefix: str, *parts: str) -> str:
    version = cache.get(make_cache_key("version", prefix), 0)
    return make_cache_key(prefix, str(version), *parts)


_EMPTY_SENTINEL = "__ghazatna_cache_none__"


def get_or_set(key: str, producer: Callable[[], Any], ttl: int = DEFAULT_TTL) -> Any:
    """Cache producer results including empty lists; treat only missing keys as miss.

    A producer that returns ``None`` is stored under a sentinel so subsequent
    requests do not re-run the producer every time.
    """
    if cache.has_key(key):  # noqa: W601 — intentional Django cache API
        value = cache.get(key)
        if value == _EMPTY_SENTINEL:
            return None
        return value
    value = producer()
    cache.set(key, _EMPTY_SENTINEL if value is None else value, ttl)
    return value


def stable_query_key(request) -> str:
    if not request.GET:
        return "all"
    filtered = [
        (key, value)
        for key, value in request.GET.items()
        if key in _ALLOWED_QUERY_PARAMS
    ]
    if not filtered:
        return "all"
    payload = json.dumps(sorted(filtered), ensure_ascii=False)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()
