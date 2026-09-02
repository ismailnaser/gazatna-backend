"""HttpOnly auth cookies. Path=/ so the Next.js proxy on the public host can set them."""

from __future__ import annotations

from datetime import timedelta

from rest_framework_simplejwt.settings import api_settings as jwt_settings

ACCESS_COOKIE = "ghazatna_access"
REFRESH_COOKIE = "ghazatna_refresh"
PRESENT_COOKIE = "ghazatna_present"


def _cookie_secure(request) -> bool:
    proto = (request.META.get("HTTP_X_FORWARDED_PROTO") or "").split(",")[0].strip()
    return bool(request.is_secure() or proto == "https")


def _cookie_domain(request) -> str | None:
    host = (request.get_host() or "").split(":")[0].lower()
    if host in ("gzs.edu.ps", "www.gzs.edu.ps", "django.gzs.edu.ps", "www.django.gzs.edu.ps"):
        return "gzs.edu.ps"
    return None


def _max_age(duration: timedelta | None) -> int | None:
    if duration is None:
        return None
    return int(duration.total_seconds())


def set_auth_cookies(response, request, access: str, refresh: str, remember: bool = True) -> None:
    secure = _cookie_secure(request)
    domain = _cookie_domain(request)
    access_age = _max_age(jwt_settings.ACCESS_TOKEN_LIFETIME)
    refresh_age = _max_age(jwt_settings.REFRESH_TOKEN_LIFETIME) if remember else None
    present_age = refresh_age if remember else None

    common = {
        "path": "/",
        "secure": secure,
        "samesite": "Lax",
        "domain": domain,
    }
    response.set_cookie(
        ACCESS_COOKIE,
        access,
        max_age=access_age,
        httponly=True,
        **common,
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh,
        max_age=refresh_age,
        httponly=True,
        **common,
    )
    # Readable flag only — not a secret. Lets the SPA know a session exists.
    response.set_cookie(
        PRESENT_COOKIE,
        "1",
        max_age=present_age,
        httponly=False,
        **common,
    )


def clear_auth_cookies(response, request) -> None:
    secure = _cookie_secure(request)
    domain = _cookie_domain(request)
    for name in (ACCESS_COOKIE, REFRESH_COOKIE, PRESENT_COOKIE):
        response.delete_cookie(name, path="/", samesite="Lax")
        if domain:
            response.delete_cookie(name, path="/", domain=domain, samesite="Lax")


def remember_from_request(request) -> bool:
    raw = request.data.get("remember", True)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in ("0", "false", "no", "off")
