import tempfile
from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from academics.models import Student, StudentDocument
from accounts.models import User
from config.media_access import user_can_access_media
from finance.models import PaymentNotice


def _user(username, role, password="StrongPass123"):
    return User.objects.create_user(
        username=username,
        password=password,
        role=role,
        first_name=username,
        status="active",
    )


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class MediaOwnershipTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.parent_a = _user("media_parent_a", "parent")
        cls.parent_b = _user("media_parent_b", "parent")
        cls.teacher = _user("media_teacher", "teacher")
        cls.finance = _user("media_finance", "admin_finance")
        cls.student_a = Student.objects.create(
            name="طالب أ",
            student_number="MED001",
            grade_level="الرابع",
            section="أ",
            parent=cls.parent_a,
        )
        cls.student_b = Student.objects.create(
            name="طالب ب",
            student_number="MED002",
            grade_level="الرابع",
            section="ب",
            parent=cls.parent_b,
        )
        cls.doc_a = StudentDocument.objects.create(
            student=cls.student_a,
            name="هوية",
            file=SimpleUploadedFile("id-a.pdf", b"%PDF-1.4 dummy", content_type="application/pdf"),
        )
        cls.doc_b = StudentDocument.objects.create(
            student=cls.student_b,
            name="هوية",
            file=SimpleUploadedFile("id-b.pdf", b"%PDF-1.4 dummy", content_type="application/pdf"),
        )
        cls.pay_a = PaymentNotice.objects.create(
            student=cls.student_a,
            amount=100,
            date=date.today(),
            receipt=SimpleUploadedFile("r-a.jpg", b"\xff\xd8\xff", content_type="image/jpeg"),
        )

    def test_parent_can_read_own_student_document_only(self):
        self.assertTrue(user_can_access_media(self.parent_a, self.doc_a.file.name))
        self.assertFalse(user_can_access_media(self.parent_a, self.doc_b.file.name))
        self.assertFalse(user_can_access_media(self.parent_b, self.doc_a.file.name))

    def test_teacher_cannot_read_student_documents(self):
        self.assertFalse(user_can_access_media(self.teacher, self.doc_a.file.name))

    def test_parent_can_read_own_receipt_only(self):
        self.assertTrue(user_can_access_media(self.parent_a, self.pay_a.receipt.name))
        self.assertFalse(user_can_access_media(self.parent_b, self.pay_a.receipt.name))

    def test_unknown_private_file_is_denied_to_parent(self):
        self.assertFalse(user_can_access_media(self.parent_a, "students/documents/missing.pdf"))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ProtectedMediaViewTests(APITestCase):
    password = "StrongPass123"

    @classmethod
    def setUpTestData(cls):
        cls.parent_a = _user("view_parent_a", "parent")
        cls.parent_b = _user("view_parent_b", "parent")
        cls.student_a = Student.objects.create(
            name="طالب أ",
            student_number="MEDV001",
            grade_level="الرابع",
            section="أ",
            parent=cls.parent_a,
        )
        cls.student_b = Student.objects.create(
            name="طالب ب",
            student_number="MEDV002",
            grade_level="الرابع",
            section="ب",
            parent=cls.parent_b,
        )
        cls.doc_a = StudentDocument.objects.create(
            student=cls.student_a,
            name="هوية",
            file=SimpleUploadedFile("view-id-a.pdf", b"%PDF-1.4 dummy", content_type="application/pdf"),
        )

    def _login(self, username):
        res = self.client.post(
            "/api/auth/login/",
            {"username": username, "password": self.password},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.data)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")

    def test_owner_parent_can_fetch_document(self):
        self._login("view_parent_a")
        res = self.client.get(f"/media/{self.doc_a.file.name}")
        self.assertEqual(res.status_code, 200)

    def test_other_parent_cannot_fetch_document(self):
        self._login("view_parent_b")
        res = self.client.get(f"/media/{self.doc_a.file.name}")
        self.assertEqual(res.status_code, 403)

    def test_anonymous_cannot_fetch_private_document(self):
        res = self.client.get(f"/media/{self.doc_a.file.name}")
        self.assertEqual(res.status_code, 403)
