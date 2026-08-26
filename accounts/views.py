from django.contrib.auth import authenticate
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from accounts.models import User
from accounts.roles import ADMIN_ROLES
from accounts.serializers import UserCreateSerializer, UserSerializer
from accounts.utils import generate_secure_password
from config.permissions import IsSuperAdmin
from config.throttling import LoginHourlyRateThrottle, LoginRateThrottle


def user_authentication_rule(user) -> bool:
    """SimpleJWT rule: reject inactive custom status as well as is_active=False."""
    if user is None:
        return False
    if not getattr(user, "is_active", True):
        return False
    return getattr(user, "status", "active") == "active"


class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [LoginRateThrottle, LoginHourlyRateThrottle]

    def post(self, request):
        username = str(request.data.get("username", "")).strip()
        password = request.data.get("password", "")

        if not username:
            return Response({"detail": "بيانات الدخول غير صحيحة"}, status=status.HTTP_401_UNAUTHORIZED)

        # Always run authenticate (includes dummy password hash) to avoid
        # username enumeration via timing when the user does not exist.
        auth_user = authenticate(request, username=username, password=password)
        if not auth_user or not user_authentication_rule(auth_user):
            return Response({"detail": "بيانات الدخول غير صحيحة"}, status=status.HTTP_401_UNAUTHORIZED)

        refresh = RefreshToken.for_user(auth_user)
        return Response(
            {
                "user": UserSerializer(auth_user).data,
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            }
        )


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not user_authentication_rule(request.user):
            return Response({"detail": "الحساب غير نشط"}, status=status.HTTP_401_UNAUTHORIZED)
        return Response(UserSerializer(request.user).data)


class LogoutView(APIView):
    """Blacklist the refresh token so deactivated/logged-out sessions stop renewing."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        raw = request.data.get("refresh") or ""
        if not raw:
            return Response({"detail": "رمز التحديث مطلوب"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            token = RefreshToken(raw)
            token.blacklist()
        except TokenError:
            return Response({"detail": "رمز التحديث غير صالح"}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"detail": "تم تسجيل الخروج"}, status=status.HTTP_200_OK)


class StatusAwareTokenRefreshView(TokenRefreshView):
    """Reject refresh for users with status != active before minting new tokens."""

    def post(self, request, *args, **kwargs):
        raw = request.data.get("refresh")
        if not raw:
            return Response({"detail": "رمز التحديث مطلوب"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            token = RefreshToken(raw)
            user = User.objects.filter(id=token.get("user_id")).first()
            if not user_authentication_rule(user):
                try:
                    token.blacklist()
                except TokenError:
                    pass
                return Response({"detail": "الحساب غير نشط"}, status=status.HTTP_401_UNAUTHORIZED)
        except TokenError:
            return Response({"detail": "رمز التحديث غير صالح"}, status=status.HTTP_401_UNAUTHORIZED)
        return super().post(request, *args, **kwargs)


class AdminUserViewSet(viewsets.ModelViewSet):
    permission_classes = [IsSuperAdmin]
    queryset = User.objects.filter(role__in=ADMIN_ROLES).order_by("id")

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return UserCreateSerializer
        return UserSerializer

    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        user = self.get_object()
        new_password = generate_secure_password()
        user.set_password(new_password)
        user.save(update_fields=["password"])
        return Response(
            {
                "userId": str(user.id),
                "name": user.display_name,
                "username": user.username,
                "password": new_password,
            }
        )
