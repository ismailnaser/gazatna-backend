from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger(__name__)

_handlers: dict[str, list[Callable[..., None]]] = defaultdict(list)


def on(event_name: str):
    def decorator(handler: Callable[..., None]) -> Callable[..., None]:
        _handlers[event_name].append(handler)
        return handler

    return decorator


def emit(event_name: str, **payload: Any) -> None:
    for handler in list(_handlers.get(event_name, [])):
        try:
            handler(**payload)
        except Exception:
            logger.exception("Event handler failed for %s", event_name)


def clear_handlers() -> None:
    _handlers.clear()
