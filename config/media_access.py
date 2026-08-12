"""Media access control and signed URLs for protected uploads."""

from __future__ import annotations

import hashlib
import hmac
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse

from django.conf import settings

from accounts.roles import ADMIN_ROLES, role_has_scope

# Public assets — no signature required (homepage hero, news, faculty photos).
PUBLIC_MEDIA_PREFIXES = (
    "site/",
    "news/",
    "teachers/",
)

SIGN_TTL_SECONDS = 60 * 60 * 12


def normalize_media_path(path: str) -> str:
    cleaned = (path or "").lstrip("/").replace("\\", "/")
    while ".." in cleaned:
        cleaned = cleaned.replace("..", "")
    return cleaned


def is_public_media_path(path: str) -> bool:
    cleaned = normalize_media_path(path)
    return any(cleaned.startswith(prefix) for prefix in PUBLIC_MEDIA_PREFIXES)


def media_path_from_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    raw = parsed.path or url
    prefix = settings.MEDIA_URL.lstrip("/")
    if raw.startswith("/"):
        raw = raw[1:]
    if prefix and raw.startswith(prefix):
        raw = raw[len(prefix) :]
    if raw.startswith("media/"):
        raw = raw[len("media/") :]
    return normalize_media_path(raw)


def sign_media_path(path: str, exp: int | None = None) -> tuple[str, int]:
    cleaned = normalize_media_path(path)
    expires = exp if exp is not None else int(time.time()) + SIGN_TTL_SECONDS
    payload = f"{cleaned}:{expires}"
    signature = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return signature, expires


def verify_media_signature(path: str, signature: str | None, exp: str | None) -> bool:
    if not signature or not exp:
        return False
    try:
        expires = int(exp)
    except (TypeError, ValueError):
        return False
    if expires < int(time.time()):
        return False
    expected, _ = sign_media_path(normalize_media_path(path), expires)
    return hmac.compare_digest(expected, signature)


def append_media_signature(relative_url: str) -> str:
    path = media_path_from_url(relative_url)
    if not path or is_public_media_path(path):
        return relative_url
    signature, expires = sign_media_path(path)
    query = urlencode({"sig": signature, "exp": expires})
    joiner = "&" if "?" in relative_url else "?"
    return f"{relative_url}{joiner}{query}"


def build_media_url(request, file_field) -> str | None:
    if not file_field:
        return None
    relative = file_field.url
    absolute = request.build_absolute_uri(relative) if request else relative
    path = media_path_from_url(relative)
    if is_public_media_path(path):
        return absolute
    return append_media_signature(absolute)


def resolve_media_file(path: str) -> Path | None:
    cleaned = normalize_media_path(path)
    if not cleaned:
        return None
    root = settings.MEDIA_ROOT.resolve()
    candidate = (settings.MEDIA_ROOT / cleaned).resolve()
    if not str(candidate).startswith(str(root)):
        return None
    if not candidate.is_file():
        return None
    return candidate


def user_can_access_media(user, path: str) -> bool:
    cleaned = normalize_media_path(path)
    if is_public_media_path(cleaned):
        return True
    if not user or not getattr(user, "is_authenticated", False):
        return False

    role = getattr(user, "role", "")
    if role in ADMIN_ROLES:
        return True
    if cleaned.startswith("payments/"):
        return role_has_scope(role, "finance")
    if role in ("teacher", "parent"):
        return True
    return False
