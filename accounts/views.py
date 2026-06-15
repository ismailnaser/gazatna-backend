from django.contrib.auth import authenticate
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from accounts.serializers import UserSerializer


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = str(request.data.get("username", "")).strip()
        password = request.data.get("password", "")

        if not username:
            return Response({"detail": "بيانات الدخول غير صحيحة"}, status=status.HTTP_401_UNAUTHORIZED)

        user = User.objects.filter(username=username).first()
        if not user:
            return Response({"detail": "بيانات الدخول غير صحيحة"}, status=status.HTTP_401_UNAUTHORIZED)

        auth_user = authenticate(request, username=user.username, password=password)
        if not auth_user or auth_user.status != "active":
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
        return Response(UserSerializer(request.user).data)
