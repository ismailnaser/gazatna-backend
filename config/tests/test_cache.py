import tempfile
from unittest.mock import patch

from django.core.cache.backends.filebased import FileBasedCache
from django.test import SimpleTestCase

from config.cache import ResilientFileBasedCache


class ResilientCacheTests(SimpleTestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cache = ResilientFileBasedCache(self.tmpdir, {"TIMEOUT": 60})

    def test_roundtrip(self):
        self.cache.set("k", {"ok": True})
        self.assertEqual(self.cache.get("k"), {"ok": True})

    def test_get_permission_error_is_miss(self):
        with patch.object(FileBasedCache, "get", side_effect=PermissionError("denied")):
            self.assertIsNone(self.cache.get("throttle-key"))

    def test_set_permission_error_is_swallowed(self):
        with patch.object(FileBasedCache, "set", side_effect=PermissionError("denied")):
            self.cache.set("k", "v")

    def test_add_permission_error_returns_false(self):
        with patch.object(FileBasedCache, "add", side_effect=OSError("locked")):
            self.assertFalse(self.cache.add("k", "v"))
