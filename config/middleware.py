from django.http import HttpResponse

from config.throttle_cache import bump_counter


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
