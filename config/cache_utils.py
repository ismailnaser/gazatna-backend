from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

from django.core.cache import cache

DEFAULT_TTL = 300  # 5 minutes
PUBLIC_TTL = 600  # 10 minutes
ANALYTICS_TTL = 120  # 2 minutes


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
    cache.set(version_key, int(current) + 1, None)


def versioned_key(prefix: str, *parts: str) -> str:
    version = cache.get(make_cache_key("version", prefix), 0)
    return make_cache_key(prefix, str(version), *parts)


def get_or_set(key: str, producer: Callable[[], Any], ttl: int = DEFAULT_TTL) -> Any:
    value = cache.get(key)
    if value is not None:
        return value
    value = producer()
    cache.set(key, value, ttl)
    return value


def stable_query_key(request) -> str:
    if not request.GET:
        return "all"
    payload = json.dumps(sorted(request.GET.items()), ensure_ascii=False)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()
