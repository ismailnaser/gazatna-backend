from __future__ import annotations

import logging
from collections import defaultdict
from contextlib import contextmanager
from typing import Any, Callable

logger = logging.getLogger(__name__)

_handlers: dict[str, list[Callable[..., None]]] = defaultdict(list)
_suppress_depth = 0


def on(event_name: str):
    def decorator(handler: Callable[..., None]) -> Callable[..., None]:
        registered = _handlers[event_name]
        if handler not in registered:
            registered.append(handler)
        return handler

    return decorator


@contextmanager
def suppress_events():
    """Temporarily skip emit() — use around bulk saves to avoid N× cache storms."""
    global _suppress_depth
    _suppress_depth += 1
    try:
        yield
    finally:
        _suppress_depth -= 1


def emit(event_name: str, **payload: Any) -> None:
    if _suppress_depth > 0:
        return
    for handler in list(_handlers.get(event_name, [])):
        try:
            handler(**payload)
        except Exception:
            logger.exception("Event handler failed for %s", event_name)


def clear_handlers() -> None:
    _handlers.clear()
