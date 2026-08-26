from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def move_app(app: str) -> None:
    src = ROOT / app / "api_views.py"
    dst = ROOT / app / "views.py"
    text = src.read_text(encoding="utf-8")
    dst.write_text(text, encoding="utf-8")
    src.write_text(
        f'"""Compatibility shim — import from {app}.views instead."""\n'
        f"from {app}.views import *  # noqa: F401,F403\n",
        encoding="utf-8",
    )
    print(f"OK {app}")


def main() -> None:
    for app in ("academics", "assignments", "content", "finance", "staff"):
        move_app(app)

    # accounts: append clean AdminUserViewSet to existing auth views
    views_path = ROOT / "accounts" / "views.py"
    views_text = views_path.read_text(encoding="utf-8")
    if "class AdminUserViewSet" not in views_text:
        append = '''

from rest_framework import viewsets
from rest_framework.decorators import action

from accounts.roles import ADMIN_ROLES
from accounts.serializers import UserCreateSerializer
from accounts.utils import generate_secure_password
from config.permissions import IsSuperAdmin


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
'''
        views_path.write_text(views_text.rstrip() + append, encoding="utf-8")
        print("OK accounts merge")
    else:
        print("accounts already merged")

    (ROOT / "accounts" / "api_views.py").write_text(
        '"""Compatibility shim — import from accounts.views instead."""\n'
        "from accounts.views import *  # noqa: F401,F403\n",
        encoding="utf-8",
    )

    (ROOT / "config" / "api_views.py").write_text(
        '"""Backward-compatible re-exports. Prefer importing from domain apps."""\n'
        "from accounts.views import *  # noqa: F401,F403\n"
        "from academics.views import *  # noqa: F401,F403\n"
        "from assignments.views import *  # noqa: F401,F403\n"
        "from content.views import *  # noqa: F401,F403\n"
        "from finance.views import *  # noqa: F401,F403\n"
        "from staff.views import *  # noqa: F401,F403\n"
        "from config.api_helpers import *  # noqa: F401,F403\n",
        encoding="utf-8",
    )
    print("done")


if __name__ == "__main__":
    main()
