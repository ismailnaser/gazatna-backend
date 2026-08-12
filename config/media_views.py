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


class ProtectedMediaView(APIView):
    """Serve uploaded files with public allowlist + signed URLs or JWT."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, path):
        cleaned = normalize_media_path(path)
        media_file = resolve_media_file(cleaned)
        if not media_file:
            raise Http404

        if is_public_media_path(cleaned):
            return FileResponse(media_file.open("rb"), as_attachment=False)

        signature = request.query_params.get("sig") or request.GET.get("sig")
        expires = request.query_params.get("exp") or request.GET.get("exp")
        if verify_media_signature(cleaned, signature, expires):
            return FileResponse(media_file.open("rb"), as_attachment=False)

        jwt_auth = JWTAuthentication()
        auth_result = jwt_auth.authenticate(request)
        if auth_result:
            user, _token = auth_result
            if user_can_access_media(user, cleaned):
                return FileResponse(media_file.open("rb"), as_attachment=False)

        return Response({"detail": "غير مصرح"}, status=403)
