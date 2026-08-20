"""Hot-path caching helpers via django-cacheops file_cache (no Redis required)."""

from __future__ import annotations


_file_cache_patched = False


def patch_file_cache_unpickle_errors() -> None:
    """Treat corrupt pickle files as cache misses instead of 500s.

    cacheops FileCache only catches IOError/OSError/EOFError on read; a bad
    pickle (e.g. truncated write) otherwise blows up the request.
    """
    global _file_cache_patched
    if _file_cache_patched:
        return
    try:
        from cacheops.simple import CacheMiss, FileCache
    except Exception:
        return

    original_get = FileCache._get

    def _safe_get(self, key):  # type: ignore[no-untyped-def]
        try:
            return original_get(self, key)
        except CacheMiss:
            raise
        except Exception:
            try:
                self._delete(self._key_to_filename(key))
            except Exception:
                pass
            raise CacheMiss

    FileCache._get = _safe_get  # type: ignore[method-assign]
    _file_cache_patched = True


def invalidate_hot_file_caches() -> None:
    """Drop file_cache entries that back admin/public heavy reads."""
    try:
        from academics.analytics_services import (
            invalidate_cached_average_grade,
            invalidate_cached_enrollment_analytics,
            invalidate_cached_grade_chart,
        )
        from academics.academic_services import invalidate_cached_academic_context

        invalidate_cached_average_grade()
        invalidate_cached_grade_chart()
        invalidate_cached_enrollment_analytics()
        invalidate_cached_academic_context()
    except Exception:
        # Cache miss / import during migrate — never break request path.
        pass
