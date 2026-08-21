from django.test import SimpleTestCase

from config.media_access import (
    is_public_media_path,
    normalize_media_path,
    user_can_access_media,
)
from config.serializers import ScheduleSerializer
from config.api_views import _schedule_entry_text


class ScheduleHelperTests(SimpleTestCase):
    def test_entry_text_coerces_numbers(self):
        self.assertEqual(_schedule_entry_text(45, "60"), "45")
        self.assertEqual(_schedule_entry_text(None, "60"), "60")
        self.assertEqual(_schedule_entry_text("  رياضيات  "), "رياضيات")
        self.assertEqual(_schedule_entry_text(""), "")

    def test_stringify_entries_converts_int_duration(self):
        rows = ScheduleSerializer._stringify_entries(
            [
                {"day": "السبت", "duration": 45, "subject": "رياضيات", "time": 800},
                "skip-me",
                {"day": None, "notes": "  ملاحظة  "},
            ]
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["duration"], "45")
        self.assertEqual(rows[0]["time"], "800")
        self.assertEqual(rows[1]["notes"], "ملاحظة")


class MediaPathTests(SimpleTestCase):
    def test_normalize_strips_traversal(self):
        self.assertEqual(normalize_media_path("/site/hero.png"), "site/hero.png")
        self.assertEqual(normalize_media_path("..\\payments\\x.pdf"), "payments/x.pdf")
        self.assertEqual(normalize_media_path("../../etc/passwd"), "etc/passwd")
        self.assertFalse(normalize_media_path("../../etc/passwd").startswith("/"))

    def test_public_prefixes(self):
        self.assertTrue(is_public_media_path("site/hero.webp"))
        self.assertTrue(is_public_media_path("news/cover.jpg"))
        self.assertTrue(is_public_media_path("teachers/photo.png"))
        self.assertFalse(is_public_media_path("payments/receipt.pdf"))
        self.assertFalse(is_public_media_path("students/documents/id.pdf"))

    def test_anonymous_cannot_read_private_media(self):
        class Anon:
            is_authenticated = False
            role = ""

        self.assertTrue(user_can_access_media(Anon(), "site/logo.png"))
        self.assertFalse(user_can_access_media(Anon(), "payments/r.pdf"))
        self.assertFalse(user_can_access_media(None, "students/documents/a.pdf"))

    def test_finance_scope_can_read_payment_prefix(self):
        class User:
            is_authenticated = True
            role = "admin_finance"
            id = 1

        self.assertTrue(user_can_access_media(User(), "payments/r.pdf"))

