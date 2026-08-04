from __future__ import annotations

import threading
import time

from config.cache_utils import invalidate_prefix
from config.events import on
from config.jobs import run_async

_WARM_LOCK = threading.Lock()
_WARM_PENDING = False
_LAST_WARM_AT = 0.0
_WARM_MIN_INTERVAL_SEC = 15.0


def _warm_public_cache() -> None:
    """Refresh public cache endpoints; debounced to avoid thread storms on cPanel."""
    global _WARM_PENDING, _LAST_WARM_AT

    with _WARM_LOCK:
        now = time.monotonic()
        if _WARM_PENDING:
            return
        if now - _LAST_WARM_AT < _WARM_MIN_INTERVAL_SEC:
            return
        _WARM_PENDING = True

    try:
        from django.test import RequestFactory

        from config.api_views import (
            PublicSchoolValuesView,
            PublicSiteSettingsView,
            PublicStatsView,
        )

        factory = RequestFactory()
        request = factory.get("/")

        PublicStatsView().get(request)
        PublicSchoolValuesView().get(request)
        PublicSiteSettingsView().get(request)
    finally:
        with _WARM_LOCK:
            _WARM_PENDING = False
            _LAST_WARM_AT = time.monotonic()


def _schedule_warm() -> None:
    run_async(_warm_public_cache)


@on("content.changed")
def _on_content_changed(**_payload) -> None:
    for prefix in ("public:news", "public:programs", "public:stats", "public:values", "public:site"):
        invalidate_prefix(prefix)
    _schedule_warm()


@on("staff.changed")
def _on_staff_changed(**_payload) -> None:
    invalidate_prefix("public:teachers")
    _schedule_warm()


@on("academics.changed")
def _on_academics_changed(**_payload) -> None:
    for prefix in ("public:site", "academic:context", "admin:analytics"):
        invalidate_prefix(prefix)


@on("finance.changed")
def _on_finance_changed(**_payload) -> None:
    invalidate_prefix("admin:analytics")


@on("site_settings.changed")
def _on_site_settings_changed(**_payload) -> None:
    invalidate_prefix("public:site")
    _schedule_warm()
