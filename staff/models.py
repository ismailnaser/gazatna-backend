from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models


class StaffType(models.Model):
    name = models.CharField(max_length=100, unique=True)
    is_teacher = models.BooleanField(
        default=False,
        help_text="إذا كان معلماً يُنشأ حساب دخول وتظهر حقول الإسناد التعليمي.",
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "نوع الكادر"
        verbose_name_plural = "أنواع الكادر"
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class TeacherProfile(models.Model):
    class Gender(models.TextChoices):
        MALE = "male", "ذكر"
        FEMALE = "female", "أنثى"

    class MaritalStatus(models.TextChoices):
        SINGLE = "single", "أعزب/عزباء"
        MARRIED = "married", "متزوج/ة"
        DIVORCED = "divorced", "مطلق/ة"
        WIDOWED = "widowed", "أرمل/ة"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="teacher_profile",
    )
    staff_type = models.ForeignKey(
        StaffType,
        on_delete=models.PROTECT,
        related_name="members",
    )
    name = models.CharField(max_length=200, verbose_name="الاسم بالعربي")
    name_en = models.CharField(max_length=200, blank=True, default="", verbose_name="الاسم بالإنجليزي")
    national_id = models.CharField(
        max_length=9,
        unique=True,
        validators=[RegexValidator(r"^\d{9}$", message="رقم الهوية يجب أن يكون 9 أرقام.")],
        verbose_name="رقم الهوية",
    )
    date_of_birth = models.DateField(null=True, blank=True, verbose_name="تاريخ الميلاد")
    gender = models.CharField(max_length=10, choices=Gender.choices, blank=True, default="")
    marital_status = models.CharField(
        max_length=10,
        choices=MaritalStatus.choices,
        blank=True,
        default="",
    )
    mobile = models.CharField(max_length=20, blank=True, default="")
    alt_mobile = models.CharField(max_length=20, blank=True, default="")
    address = models.TextField(blank=True, default="", verbose_name="مكان السكن")
    join_date = models.DateField(null=True, blank=True, verbose_name="تاريخ الالتحاق")
    notes = models.TextField(blank=True, default="", verbose_name="ملاحظات")
    teaching_subjects = models.ManyToManyField(
        "academics.Subject",
        related_name="teachers",
        blank=True,
    )
    experience = models.TextField(blank=True)
    bio = models.TextField(blank=True)
    image = models.ImageField(upload_to="teachers/", blank=True, null=True)
    image_gradient = models.CharField(max_length=200, blank=True)
    is_public = models.BooleanField(default=True)

    class Meta:
        verbose_name = "عضو كادر"
        verbose_name_plural = "الكادر"
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def age(self):
        if not self.date_of_birth:
            return None
        today = date.today()
        years = today.year - self.date_of_birth.year
        if (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day):
            years -= 1
        return years

    def clean(self):
        super().clean()
        if self.staff_type_id and self.staff_type and not self.staff_type.is_teacher:
            return
        if self.staff_type_id and self.staff_type and self.staff_type.is_teacher:
            if self.pk and not self.teaching_subjects.exists():
                pass

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.image:
            return
        try:
            from PIL import Image
        except Exception:
            return
        try:
            img_path = self.image.path
            with Image.open(img_path) as im:
                im = im.convert("RGB")
                w, h = im.size
                side = min(w, h)
                left = (w - side) // 2
                top = (h - side) // 2
                im = im.crop((left, top, left + side, top + side))
                im = im.resize((512, 512), Image.Resampling.LANCZOS)
                im.save(img_path, quality=88, optimize=True)
        except Exception:
            return


class TeacherClassAssignment(models.Model):
    teacher = models.ForeignKey(TeacherProfile, on_delete=models.CASCADE, related_name="class_assignments")
    school_class = models.ForeignKey("academics.SchoolClass", on_delete=models.CASCADE, related_name="teacher_assignments")

    class Meta:
        unique_together = [("teacher", "school_class")]
        verbose_name = "تعيين معلم لصف"
        verbose_name_plural = "تعيينات المعلمين"


class TeacherReadAlert(models.Model):
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="read_teacher_alerts",
    )
    alert_key = models.CharField(max_length=80)
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("teacher", "alert_key")]
        verbose_name = "إشعار معلم مفتوح"
        verbose_name_plural = "إشعارات المعلم المفتوحة"
        ordering = ["-read_at"]

    def __str__(self):
        return f"{self.teacher_id}: {self.alert_key}"
