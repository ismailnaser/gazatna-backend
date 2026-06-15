from django.conf import settings
from django.db import models


class SchoolClass(models.Model):
    name = models.CharField(max_length=100)
    grade_level = models.CharField(max_length=50, blank=True)
    section = models.CharField(max_length=10, blank=True)

    class Meta:
        verbose_name = "صف"
        verbose_name_plural = "الصفوف"
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def student_count(self):
        return self.students.filter(is_active=True).count()


class Subject(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name = "مادة دراسية"
        verbose_name_plural = "المواد الدراسية"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Student(models.Model):
    name = models.CharField(max_length=200)
    student_number = models.CharField(max_length=50, unique=True)
    grade_level = models.CharField(max_length=50)
    section = models.CharField(max_length=10)
    school_class = models.ForeignKey(
        SchoolClass,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="students",
    )
    parent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )
    documents = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "طالب"
        verbose_name_plural = "الطلاب"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Enrollment(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="enrollments")
    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE, related_name="enrollments")
    academic_year = models.CharField(max_length=20, default="2025-2026")

    class Meta:
        unique_together = [("student", "school_class", "academic_year")]
        verbose_name = "تسجيل"
        verbose_name_plural = "التسجيلات"


class SubjectGrade(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="subject_grades")
    subject = models.CharField(max_length=100)
    score = models.DecimalField(max_digits=5, decimal_places=2)
    max_score = models.DecimalField(max_digits=5, decimal_places=2, default=100)
    note = models.TextField(blank=True)
    term = models.CharField(max_length=50, blank=True)

    class Meta:
        verbose_name = "درجة مادة"
        verbose_name_plural = "درجات المواد"
        ordering = ["subject"]


class ClassGradebook(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="gradebook_entries")
    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE, related_name="gradebook_entries")
    score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    note = models.TextField(blank=True)
    teacher = models.ForeignKey(
        "staff.TeacherProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="gradebook_entries",
    )

    class Meta:
        unique_together = [("student", "school_class")]
        verbose_name = "سجل درجات الصف"
        verbose_name_plural = "سجلات درجات الصفوف"
