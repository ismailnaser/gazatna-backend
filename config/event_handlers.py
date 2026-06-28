from __future__ import annotations

from config.cache_utils import invalidate_prefix
from config.events import on
from config.jobs import run_async


def _invalidate_and_warm(prefix: str) -> None:
    invalidate_prefix(prefix)
    run_async(_warm_public_cache)


def _warm_public_cache() -> None:
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


@on("content.changed")
def _on_content_changed(**_payload) -> None:
    for prefix in ("public:news", "public:programs", "public:stats", "public:values", "public:site"):
        invalidate_prefix(prefix)
    run_async(_warm_public_cache)


@on("staff.changed")
def _on_staff_changed(**_payload) -> None:
    invalidate_prefix("public:teachers")
    run_async(_warm_public_cache)


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
    run_async(_warm_public_cache)
