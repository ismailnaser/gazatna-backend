from django.urls import path
from rest_framework.routers import DefaultRouter

from accounts.views import (
    AdminUserViewSet,
    LoginView,
    LogoutView,
    MeView,
    StatusAwareTokenRefreshView,
)

router = DefaultRouter()
router.register("users", AdminUserViewSet, basename="admin-users")

urlpatterns = [
    path("login/", LoginView.as_view(), name="auth-login"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("me/", MeView.as_view(), name="auth-me"),
    path("token/refresh/", StatusAwareTokenRefreshView.as_view(), name="token-refresh"),
] + router.urls
