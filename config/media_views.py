from django.http import FileResponse, Http404
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from config.media_access import (
    is_public_media_path,
    normalize_media_path,
    resolve_media_file,
    user_can_access_media,
    verify_media_signature,
)


def _serve_file(media_file, *, as_attachment: bool) -> FileResponse:
    response = FileResponse(media_file.open("rb"), as_attachment=as_attachment)
    # Defense in depth: never let SVG execute even if an old file remains on disk.
    name = media_file.name.lower()
    if name.endswith(".svg"):
        response["Content-Disposition"] = f'attachment; filename="{media_file.name}"'
        response["Content-Type"] = "application/octet-stream"
        response["X-Content-Type-Options"] = "nosniff"
    return response


class ProtectedMediaView(APIView):
    """Serve uploaded files with public allowlist + signed URLs or JWT."""

    permission_classes = [AllowAny]
    authentication_classes = []
    # Media must not consume the shared anonymous API throttle (images would 429 pages).
    throttle_classes = []

    def get(self, request, path):
        cleaned = normalize_media_path(path)
        media_file = resolve_media_file(cleaned)
        if not media_file:
            raise Http404

        # Public assets (site/news/teachers) may display inline.
        # Protected paths always download — blocks SVG XSS on the app origin.
        if is_public_media_path(cleaned):
            return _serve_file(media_file, as_attachment=False)

        signature = request.query_params.get("sig") or request.GET.get("sig")
        expires = request.query_params.get("exp") or request.GET.get("exp")
        if verify_media_signature(cleaned, signature, expires):
            return _serve_file(media_file, as_attachment=True)

        jwt_auth = JWTAuthentication()
        auth_result = jwt_auth.authenticate(request)
        if auth_result:
            user, _token = auth_result
            if user_can_access_media(user, cleaned):
                return _serve_file(media_file, as_attachment=True)

        return Response({"detail": "غير مصرح"}, status=403)
