from django.core.cache import caches
from rest_framework.throttling import AnonRateThrottle


class _ThrottleCacheMixin:
    """Resolve the durable throttle cache at request time (not import time)."""

    cache_name = "throttle"

    def __init__(self):
        super().__init__()
        try:
            self.cache = caches[self.cache_name]
        except Exception:
            # Tests / emergency overrides that only define "default".
            self.cache = caches["default"]


class LoginRateThrottle(_ThrottleCacheMixin, AnonRateThrottle):
    """Login attempts use a dedicated durable cache (DB or Redis)."""

    scope = "login"


class LoginHourlyRateThrottle(_ThrottleCacheMixin, AnonRateThrottle):
    """Secondary brake against slow distributed brute-force."""

    scope = "login_hourly"


class PublicPostRateThrottle(_ThrottleCacheMixin, AnonRateThrottle):
    scope = "public_post"
