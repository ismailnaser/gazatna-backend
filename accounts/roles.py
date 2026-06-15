SUPER_ADMIN_ROLE = "admin"

ADMIN_ROLES = (
    SUPER_ADMIN_ROLE,
    "admin_students",
    "admin_academics",
    "admin_finance",
    "admin_content",
    "admin_staff",
)

SCOPE_ROLES = {
    "students": {SUPER_ADMIN_ROLE, "admin_students"},
    "academics": {SUPER_ADMIN_ROLE, "admin_academics"},
    "finance": {SUPER_ADMIN_ROLE, "admin_finance"},
    "content": {SUPER_ADMIN_ROLE, "admin_content"},
    "staff": {SUPER_ADMIN_ROLE, "admin_staff"},
}


def is_admin_role(role: str) -> bool:
    return role in ADMIN_ROLES


def role_has_scope(role: str, scope: str) -> bool:
    if role == SUPER_ADMIN_ROLE:
        return True
    return role in SCOPE_ROLES.get(scope, set())
