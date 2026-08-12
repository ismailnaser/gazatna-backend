from rest_framework.throttling import AnonRateThrottle


class LoginRateThrottle(AnonRateThrottle):
    scope = "login"


class PublicPostRateThrottle(AnonRateThrottle):
    scope = "public_post"
