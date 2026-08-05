from __future__ import annotations

from config.cache_utils import invalidate_prefix
from config.events import on

# Cache is rebuilt lazily on the next public GET. Never spawn workers to warm it —
# that pattern exhausted NPROC on CloudLinux/Passenger.


@on("content.changed")
def _on_content_changed(**_payload) -> None:
    for prefix in ("public:news", "public:programs", "public:stats", "public:values", "public:site"):
        invalidate_prefix(prefix)


@on("staff.changed")
def _on_staff_changed(**_payload) -> None:
    invalidate_prefix("public:teachers")


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
