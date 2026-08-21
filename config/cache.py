"""File cache that degrades on lock/permission races instead of 500.

Django FileBasedCache raises PermissionError/OSError on Windows and some
shared-hosting filesystems when throttle/analytics hit the same key concurrently.
REST framework then turns that into Internal Server Error.
"""
from __future__ import annotations

import logging
import pickle
import zlib

from django.core.cache.backends.base import DEFAULT_TIMEOUT
from django.core.cache.backends.filebased import FileBasedCache

logger = logging.getLogger(__name__)

_CACHE_IO_ERRORS = (
    OSError,
    EOFError,
    pickle.PickleError,
    zlib.error,
)


class ResilientFileBasedCache(FileBasedCache):
    def get(self, key, default=None, version=None):
        try:
            return super().get(key, default, version)
        except _CACHE_IO_ERRORS:
            logger.warning("cache get failed for %s; treating as miss", key, exc_info=False)
            return default

    def set(self, key, value, timeout=DEFAULT_TIMEOUT, version=None):
        try:
            super().set(key, value, timeout, version)
        except _CACHE_IO_ERRORS:
            logger.warning("cache set failed for %s; skipping", key, exc_info=False)

    def add(self, key, value, timeout=DEFAULT_TIMEOUT, version=None):
        try:
            return super().add(key, value, timeout, version)
        except _CACHE_IO_ERRORS:
            logger.warning("cache add failed for %s; skipping", key, exc_info=False)
            return False

    def delete(self, key, version=None):
        try:
            return super().delete(key, version)
        except _CACHE_IO_ERRORS:
            return False

    def touch(self, key, timeout=DEFAULT_TIMEOUT, version=None):
        try:
            return super().touch(key, timeout, version)
        except _CACHE_IO_ERRORS:
            return False

    def has_key(self, key, version=None):
        try:
            return super().has_key(key, version)
        except _CACHE_IO_ERRORS:
            return False

    def clear(self):
        try:
            super().clear()
        except _CACHE_IO_ERRORS:
            logger.warning("cache clear failed; skipping", exc_info=False)
