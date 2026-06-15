from rest_framework.permissions import BasePermission

from accounts.roles import ADMIN_ROLES, SUPER_ADMIN_ROLE, is_admin_role, role_has_scope


class IsAdmin(BasePermission):
    """أي حساب إداري (كلي أو متخصص)."""

    def has_permission(self, request, view):
        return request.user.is_authenticated and is_admin_role(request.user.role)


class IsSuperAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == SUPER_ADMIN_ROLE


class IsTeacher(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == "teacher"


class IsParent(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == "parent"


class IsAdminOrTeacher(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in ("teacher", *ADMIN_ROLES)


def AdminScopePermission(*scopes: str):
    class _Permission(BasePermission):
        def has_permission(self, request, view):
            if not request.user.is_authenticated:
                return False
            return any(role_has_scope(request.user.role, scope) for scope in scopes)

    return _Permission
