from urllib.parse import urlparse

from django.conf import settings
from django.http import HttpResponse, JsonResponse

from accounts.auth_cookies import ACCESS_COOKIE, REFRESH_COOKIE
from config.throttle_cache import bump_counter

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
_LOCAL_ORIGINS = (
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
)


def _allowed_origins() -> set[str]:
    origins = {o.rstrip("/") for o in _LOCAL_ORIGINS}
    origins.update({"https://gzs.edu.ps", "https://www.gzs.edu.ps"})
    for attr in ("CSRF_TRUSTED_ORIGINS", "CORS_ALLOWED_ORIGINS"):
        for raw in getattr(settings, attr, None) or []:
            value = str(raw).strip().rstrip("/")
            if value:
                origins.add(value)
    return origins


def _request_origin(request) -> str:
    proto = (
        (request.META.get("HTTP_X_FORWARDED_PROTO") or "")
        .split(",")[0]
        .strip()
        or ("https" if request.is_secure() else "http")
    )
    host = (request.get_host() or "").split(",")[0].strip()
    if not host:
        return ""
    return f"{proto}://{host}".rstrip("/")


def _origin_of(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


class CookieAuthOriginMiddleware:
    """Block cross-site mutating API calls that rely on auth cookies (not Bearer)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method in _SAFE_METHODS:
            return self.get_response(request)

        path = request.path_info or ""
        if not path.startswith("/api"):
            return self.get_response(request)

        auth = request.META.get("HTTP_AUTHORIZATION") or ""
        if auth.lower().startswith("bearer "):
            return self.get_response(request)

        if ACCESS_COOKIE not in request.COOKIES and REFRESH_COOKIE not in request.COOKIES:
            return self.get_response(request)

        origin = (request.META.get("HTTP_ORIGIN") or "").rstrip("/")
        referer = _origin_of(request.META.get("HTTP_REFERER") or "")
        allowed = _allowed_origins()
        req_origin = _request_origin(request)
        if origin and origin == req_origin:
            return self.get_response(request)
        if referer and referer == req_origin:
            return self.get_response(request)
        if origin in allowed or referer in allowed:
            return self.get_response(request)

        return JsonResponse(
            {"detail": "تعذر التحقق من مصدر الطلب."},
            status=403,
        )


class ApiTrailingSlashMiddleware:
    """Next.js rewrites drop the trailing slash; Django cannot 301 POST.

    Restore `/` on /api paths before CommonMiddleware so APPEND_SLASH
    does not raise RuntimeError in DEBUG.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info or ""
        if path.startswith("/api") and not path.endswith("/"):
            request.path_info = f"{path}/"
        return self.get_response(request)


class AdminLoginRateLimitMiddleware:
    """Rate-limit Django admin login POSTs (DRF throttles do not cover /admin/).

    Uses the durable throttle cache (DatabaseCache / Redis) shared across workers.
    Short window: 10 / minute. Long window: 40 / hour (slow brute-force brake).
    """

    SHORT_LIMIT = 10
    SHORT_WINDOW = 60
    LONG_LIMIT = 40
    LONG_WINDOW = 3600

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = (request.path_info or "").rstrip("/")
        if request.method == "POST" and path.endswith("/admin/login"):
            ip = (
                (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
                or request.META.get("REMOTE_ADDR")
                or "unknown"
            )
            short_key = f"admin-login:m:{ip}"
            long_key = f"admin-login:h:{ip}"
            short_hits = bump_counter(short_key, self.SHORT_WINDOW)
            long_hits = bump_counter(long_key, self.LONG_WINDOW)
            if short_hits > self.SHORT_LIMIT or long_hits > self.LONG_LIMIT:
                return HttpResponse(
                    "تم تجاوز عدد محاولات الدخول. حاول لاحقاً.",
                    status=429,
                    content_type="text/plain; charset=utf-8",
                )
        return self.get_response(request)
