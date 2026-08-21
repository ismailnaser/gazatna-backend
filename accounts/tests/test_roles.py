from django.test import SimpleTestCase

from accounts.roles import (
    ADMIN_ROLES,
    SUPER_ADMIN_ROLE,
    is_admin_role,
    role_has_scope,
)


class RoleScopeTests(SimpleTestCase):
    def test_super_admin_has_every_scope(self):
        for scope in ("students", "academics", "finance", "content", "staff"):
            self.assertTrue(role_has_scope(SUPER_ADMIN_ROLE, scope))

    def test_specialized_admin_is_limited_to_own_scope(self):
        self.assertTrue(role_has_scope("admin_finance", "finance"))
        self.assertFalse(role_has_scope("admin_finance", "students"))
        self.assertFalse(role_has_scope("admin_content", "staff"))
        self.assertTrue(role_has_scope("admin_students", "students"))

    def test_teacher_and_parent_are_not_admins(self):
        self.assertFalse(is_admin_role("teacher"))
        self.assertFalse(is_admin_role("parent"))
        self.assertFalse(role_has_scope("teacher", "academics"))
        self.assertFalse(role_has_scope("parent", "finance"))

    def test_unknown_scope_is_denied_for_specialized_roles(self):
        self.assertFalse(role_has_scope("admin_finance", "not-a-real-scope"))

    def test_all_admin_roles_are_recognized(self):
        for role in ADMIN_ROLES:
            self.assertTrue(is_admin_role(role))
