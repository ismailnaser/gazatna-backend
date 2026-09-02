from django.test import override_settings
from rest_framework.test import APITestCase

from accounts.models import User

CACHE = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "login-tests",
    },
    "throttle": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "login-tests-throttle",
    },
}


@override_settings(CACHES=CACHE)
class LoginApiTests(APITestCase):
    def setUp(self):
        self.password = "StrongPass123"
        self.user = User.objects.create_user(
            username="parent_one",
            password=self.password,
            role="parent",
            first_name="ولي",
            status="active",
        )
        self.inactive = User.objects.create_user(
            username="inactive_user",
            password=self.password,
            role="parent",
            status="inactive",
        )

    def test_login_success_returns_tokens(self):
        res = self.client.post(
            "/api/auth/login/",
            {"username": "parent_one", "password": self.password},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("access", res.data)
        self.assertIn("refresh", res.data)
        self.assertEqual(res.data["user"]["role"], "parent")

    def test_wrong_password_uses_generic_message(self):
        res = self.client.post(
            "/api/auth/login/",
            {"username": "parent_one", "password": "wrong"},
            format="json",
        )
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.data["detail"], "بيانات الدخول غير صحيحة")

    def test_unknown_user_uses_same_generic_message(self):
        res = self.client.post(
            "/api/auth/login/",
            {"username": "does-not-exist", "password": "wrong"},
            format="json",
        )
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.data["detail"], "بيانات الدخول غير صحيحة")

    def test_inactive_user_cannot_login(self):
        res = self.client.post(
            "/api/auth/login/",
            {"username": "inactive_user", "password": self.password},
            format="json",
        )
        self.assertEqual(res.status_code, 401)

    def test_me_requires_auth(self):
        res = self.client.get("/api/auth/me/")
        self.assertEqual(res.status_code, 401)

    def test_me_returns_current_user(self):
        login = self.client.post(
            "/api/auth/login/",
            {"username": "parent_one", "password": self.password},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        res = self.client.get("/api/auth/me/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["username"], "parent_one")

    def test_login_sets_httponly_cookies(self):
        res = self.client.post(
            "/api/auth/login/",
            {"username": "parent_one", "password": self.password},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.cookies["ghazatna_access"]["httponly"])
        self.assertTrue(res.cookies["ghazatna_refresh"]["httponly"])
        self.assertFalse(res.cookies["ghazatna_present"]["httponly"])

    def test_me_accepts_access_cookie_without_bearer(self):
        self.client.post(
            "/api/auth/login/",
            {"username": "parent_one", "password": self.password},
            format="json",
        )
        self.client.credentials()
        res = self.client.get("/api/auth/me/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["username"], "parent_one")

    def test_logout_clears_auth_cookies(self):
        self.client.post(
            "/api/auth/login/",
            {"username": "parent_one", "password": self.password},
            format="json",
        )
        self.client.credentials()
        res = self.client.post(
            "/api/auth/logout/",
            {},
            format="json",
            HTTP_ORIGIN="http://localhost:3001",
        )
        self.assertEqual(res.status_code, 200)
        self.client.cookies.clear()
        res = self.client.get("/api/auth/me/")
        self.assertEqual(res.status_code, 401)
