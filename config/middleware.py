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
