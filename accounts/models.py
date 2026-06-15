from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "إدارة كلية"
        ADMIN_STUDENTS = "admin_students", "إدارة الطلاب"
        ADMIN_ACADEMICS = "admin_academics", "إدارة الفصول والمواد"
        ADMIN_FINANCE = "admin_finance", "إدارة المالية"
        ADMIN_CONTENT = "admin_content", "إدارة المحتوى"
        ADMIN_STAFF = "admin_staff", "إدارة الكادر"
        TEACHER = "teacher", "معلم"
        PARENT = "parent", "ولي أمر"

    class Status(models.TextChoices):
        ACTIVE = "active", "نشط"
        INACTIVE = "inactive", "غير نشط"

    role = models.CharField(max_length=30, choices=Role.choices, default=Role.PARENT)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        verbose_name = "مستخدم"
        verbose_name_plural = "المستخدمون"

    @property
    def display_name(self):
        full = self.get_full_name().strip()
        return full or self.username
