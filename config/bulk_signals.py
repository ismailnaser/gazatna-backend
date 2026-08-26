"""Mute Django signal→event storms during bulk academic/finance mutations."""

from __future__ import annotations

from contextlib import contextmanager

from config.events import suppress_events


@contextmanager
def mute_model_events():
    """Suppress cache-invalidation events during bulk writes; emit once after."""
    with suppress_events():
        yield
