from django.test import override_settings
from rest_framework.test import APITestCase

from academics.models import Student
from accounts.models import User

CACHE = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "rbac-tests",
    }
}


def _user(username, role, password="StrongPass123"):
    return User.objects.create_user(
        username=username,
        password=password,
        role=role,
        first_name=username,
        status="active",
    )


@override_settings(CACHES=CACHE)
class ApiRbacTests(APITestCase):
    password = "StrongPass123"

    @classmethod
    def setUpTestData(cls):
        cls.admin = _user("rbac_admin", "admin")
        cls.finance = _user("rbac_finance", "admin_finance")
        cls.teacher = _user("rbac_teacher", "teacher")
        cls.parent_a = _user("rbac_parent_a", "parent")
        cls.parent_b = _user("rbac_parent_b", "parent")
        Student.objects.create(
            name="طالب أ",
            student_number="RBAC001",
            grade_level="الرابع",
            section="أ",
            parent=cls.parent_a,
        )
        Student.objects.create(
            name="طالب ب",
            student_number="RBAC002",
            grade_level="الرابع",
            section="ب",
            parent=cls.parent_b,
        )

    def _login(self, username):
        res = self.client.post(
            "/api/auth/login/",
            {"username": username, "password": self.password},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.data)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")
        return res.data["access"]

    def test_unauthenticated_admin_is_401(self):
        res = self.client.get("/api/admin/students/")
        self.assertEqual(res.status_code, 401)

    def test_public_site_settings_allowed(self):
        res = self.client.get("/api/site-settings/")
        self.assertEqual(res.status_code, 200)

    def test_parent_cannot_list_admin_students(self):
        self._login("rbac_parent_a")
        res = self.client.get("/api/admin/students/")
        self.assertEqual(res.status_code, 403)

    def test_teacher_cannot_read_parent_fees(self):
        self._login("rbac_teacher")
        res = self.client.get("/api/parent/fees/")
        self.assertEqual(res.status_code, 403)

    def test_finance_admin_cannot_list_students(self):
        self._login("rbac_finance")
        res = self.client.get("/api/admin/students/")
        self.assertEqual(res.status_code, 403)

    def test_parent_student_is_scoped_to_linked_child(self):
        self._login("rbac_parent_a")
        res = self.client.get("/api/parent/student/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data.get("name"), "طالب أ")
        self.assertNotEqual(res.data.get("studentNumber"), "RBAC002")

    def test_teacher_schedules_do_not_500_without_profile(self):
        self._login("rbac_teacher")
        res = self.client.get("/api/teacher/schedules/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data, [])

    def test_parent_cannot_create_admin_subject(self):
        self._login("rbac_parent_a")
        res = self.client.post("/api/admin/subjects/", {"name": "اختراق"}, format="json")
        self.assertIn(res.status_code, (401, 403))
