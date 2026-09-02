from django.test import RequestFactory, SimpleTestCase

from accounts.auth_cookies import ACCESS_COOKIE, REFRESH_COOKIE
from config.middleware import CookieAuthOriginMiddleware


class CookieAuthOriginMiddlewareTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = CookieAuthOriginMiddleware(lambda request: None)

    def _patch(self, **extra):
        request = self.factory.patch("/api/admin/site-settings/", **extra)
        request.COOKIES[ACCESS_COOKIE] = "fake-access"
        request.COOKIES[REFRESH_COOKIE] = "fake-refresh"
        return request

    def test_allows_same_origin_sec_fetch_site_without_origin(self):
        request = self._patch(HTTP_SEC_FETCH_SITE="same-origin", HTTP_HOST="127.0.0.1:8001")
        self.assertIsNone(self.middleware(request))

    def test_allows_forwarded_frontend_host(self):
        request = self._patch(
            HTTP_HOST="127.0.0.1:8001",
            HTTP_X_FORWARDED_HOST="localhost:3001",
            HTTP_X_FORWARDED_PROTO="http",
            HTTP_ORIGIN="http://localhost:3001",
        )
        self.assertIsNone(self.middleware(request))

    def test_blocks_cross_site_without_trust_signals(self):
        request = self._patch(HTTP_HOST="127.0.0.1:8001", HTTP_ORIGIN="https://evil.example")
        response = self.middleware(request)
        self.assertEqual(response.status_code, 403)
