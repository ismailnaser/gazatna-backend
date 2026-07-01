from django.conf import settings
from django.db import models


class Grade(models.Model):
    name = models.CharField(max_length=50, unique=True)
    sections_count = models.PositiveIntegerField(default=1)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "فصل دراسي"
        verbose_name_plural = "الفصول الدراسية"
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class SchoolClass(models.Model):
    name = models.CharField(max_length=100)
    grade_level = models.CharField(max_length=50, blank=True)
    section = models.CharField(max_length=10, blank=True)
    homeroom_teacher = models.ForeignKey(
        "staff.TeacherProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="homeroom_classes",
    )

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


class ClassSubjectAssignment(models.Model):
    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name="class_assignments",
    )
    school_class = models.ForeignKey(
        SchoolClass,
        on_delete=models.CASCADE,
        related_name="subject_assignments",
    )
    academic_term = models.ForeignKey(
        "AcademicTerm",
        on_delete=models.CASCADE,
        related_name="class_subject_assignments",
        null=True,
        blank=True,
    )

    class Meta:
        unique_together = [("subject", "school_class", "academic_term")]
        verbose_name = "إسناد مادة لصف"
        verbose_name_plural = "إسنادات المواد للصفوف"
        ordering = ["school_class__name", "subject__name"]

    def __str__(self):
        return f"{self.subject.name} — {self.school_class.name}"


class Student(models.Model):
    name = models.CharField(max_length=200)
    student_number = models.CharField(max_length=50, unique=True)
    national_id = models.CharField(max_length=20, blank=True, default="")
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
        constraints = [
            models.UniqueConstraint(
                fields=["national_id"],
                condition=models.Q(national_id__gt=""),
                name="academics_student_national_id_unique",
            ),
            models.UniqueConstraint(
                fields=["parent"],
                condition=models.Q(parent__isnull=False),
                name="academics_student_unique_login_account",
            ),
        ]

    def __str__(self):
        return self.name


class StudentDocument(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="uploaded_documents")
    name = models.CharField(max_length=200)
    file = models.FileField(upload_to="students/documents/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "وثيقة طالب"
        verbose_name_plural = "وثائق الطلاب"
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"{self.student_id}: {self.name}"


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
    academic_term = models.ForeignKey(
        "AcademicTerm",
        on_delete=models.CASCADE,
        related_name="subject_grades",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "درجة مادة"
        verbose_name_plural = "درجات المواد"
        ordering = ["subject"]
        unique_together = [("student", "subject", "academic_term")]


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


class SubjectGradeScheme(models.Model):
    teacher = models.ForeignKey(
        "staff.TeacherProfile",
        on_delete=models.CASCADE,
        related_name="grade_schemes",
    )
    school_class = models.ForeignKey(
        SchoolClass,
        on_delete=models.CASCADE,
        related_name="grade_schemes",
    )
    subject = models.CharField(max_length=100)
    academic_term = models.ForeignKey(
        "AcademicTerm",
        on_delete=models.CASCADE,
        related_name="grade_schemes",
        null=True,
        blank=True,
    )
    max_score = models.DecimalField(max_digits=6, decimal_places=2, default=100)
    components = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("teacher", "school_class", "subject", "academic_term")]
        verbose_name = "تقسيمة علامات مادة"
        verbose_name_plural = "تقسيمات علامات المواد"
        ordering = ["-updated_at", "-id"]

    def __str__(self):
        return f"{self.subject} — {self.school_class.name}"


class GradeSchemeTemplate(models.Model):
    """تقسيمة علامات موحّدة يحددها المشرف لكل الفصول والمواد في الفصل الدراسي."""

    academic_term = models.OneToOneField(
        "AcademicTerm",
        on_delete=models.CASCADE,
        related_name="grade_scheme_template",
    )
    max_score = models.DecimalField(max_digits=6, decimal_places=2, default=100)
    components = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "تقسيمة علامات موحّدة"
        verbose_name_plural = "تقسيمات العلامات الموحّدة"
        ordering = ["-updated_at", "-id"]

    def __str__(self):
        return f"تقسيمة {self.academic_term}"


class SubjectGradeSchemeEntry(models.Model):
    scheme = models.ForeignKey(
        SubjectGradeScheme,
        on_delete=models.CASCADE,
        related_name="entries",
    )
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="grade_scheme_entries",
    )
    scores = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("scheme", "student")]
        verbose_name = "علامة طالب في تقسيمة"
        verbose_name_plural = "علامات الطلاب في التقسيمات"


class AcademicYear(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_ACTIVE = "active"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "مسودة"),
        (STATUS_ACTIVE, "نشطة"),
        (STATUS_ARCHIVED, "مؤرشفة"),
    ]

    name = models.CharField(max_length=20, unique=True)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "سنة دراسية"
        verbose_name_plural = "السنوات الدراسية"
        ordering = ["-start_date", "-id"]

    def __str__(self):
        return self.name


class AcademicTerm(models.Model):
    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.CASCADE,
        related_name="terms",
    )
    name = models.CharField(max_length=100)
    sort_order = models.PositiveIntegerField(default=1)
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)
    is_closed = models.BooleanField(default=False)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "فصل دراسي"
        verbose_name_plural = "الفصول الدراسية"
        ordering = ["academic_year", "sort_order", "id"]
        unique_together = [("academic_year", "sort_order")]

    def __str__(self):
        return f"{self.academic_year.name} — {self.name}"


class PromotionPolicy(models.Model):
    EVAL_SINGLE_TERM = "single_term"
    EVAL_FULL_YEAR = "full_year"
    EVALUATION_SCOPE_CHOICES = [
        (EVAL_SINGLE_TERM, "فصل واحد"),
        (EVAL_FULL_YEAR, "السنة كاملة"),
    ]

    CALC_TERM_AVERAGE = "term_average"
    CALC_YEAR_TOTAL = "year_total"
    CALC_PER_TERM_COMBINE = "per_term_combine"
    CALC_SINGLE_TERM = "single_term_only"
    YEAR_CALCULATION_CHOICES = [
        (CALC_TERM_AVERAGE, "متوسط الفصلين"),
        (CALC_YEAR_TOTAL, "مجموع السنة"),
        (CALC_PER_TERM_COMBINE, "كل فصل على حدة ثم يُجمع القرار"),
        (CALC_SINGLE_TERM, "فصل واحد محدد"),
    ]

    PASS_ALL_SUBJECTS = "all_subjects"
    PASS_MINIMUM_COUNT = "minimum_count"
    PASS_RULE_CHOICES = [
        (PASS_ALL_SUBJECTS, "جميع المواد"),
        (PASS_MINIMUM_COUNT, "عدد محدد من المواد"),
    ]

    MODE_AUTOMATIC = "automatic"
    MODE_MANUAL = "manual"
    PROMOTION_MODE_CHOICES = [
        (MODE_AUTOMATIC, "تلقائي"),
        (MODE_MANUAL, "يدوي"),
    ]

    FAIL_REPEAT_AUTO = "repeat_auto"
    FAIL_MANUAL_REVIEW = "manual_review"
    FAILURE_MODE_CHOICES = [
        (FAIL_REPEAT_AUTO, "إعادة تلقائية"),
        (FAIL_MANUAL_REVIEW, "اعتماد يدوي"),
    ]

    grade = models.OneToOneField(
        "Grade",
        on_delete=models.CASCADE,
        related_name="promotion_policy",
    )
    evaluation_scope = models.CharField(
        max_length=30,
        choices=EVALUATION_SCOPE_CHOICES,
        default=EVAL_FULL_YEAR,
    )
    year_calculation_method = models.CharField(
        max_length=30,
        choices=YEAR_CALCULATION_CHOICES,
        default=CALC_TERM_AVERAGE,
    )
    evaluation_term = models.ForeignKey(
        AcademicTerm,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="promotion_policies",
    )
    pass_rule = models.CharField(
        max_length=30,
        choices=PASS_RULE_CHOICES,
        default=PASS_MINIMUM_COUNT,
    )
    pass_minimum_count = models.PositiveIntegerField(default=1)
    required_subjects = models.JSONField(default=list, blank=True)
    pass_score_ratio = models.DecimalField(max_digits=4, decimal_places=3, default=0.5)
    pass_promotion_mode = models.CharField(
        max_length=20,
        choices=PROMOTION_MODE_CHOICES,
        default=MODE_AUTOMATIC,
    )
    fail_handling_mode = models.CharField(
        max_length=20,
        choices=FAILURE_MODE_CHOICES,
        default=FAIL_MANUAL_REVIEW,
    )
    is_configured = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "سياسة الترفيع"
        verbose_name_plural = "سياسات الترفيع"

    def __str__(self):
        return f"سياسة {self.grade.name}"


class YearEndPromotionRun(models.Model):
    STATUS_EXECUTED = "executed"
    STATUS_CHOICES = [
        (STATUS_EXECUTED, "منفّذ"),
    ]

    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.CASCADE,
        related_name="promotion_runs",
    )
    new_academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_from_runs",
    )
    executed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="promotion_runs",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_EXECUTED)
    summary = models.JSONField(default=dict, blank=True)
    student_results = models.JSONField(default=list, blank=True)
    executed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "تنفيذ نهاية سنة"
        verbose_name_plural = "تنفيذات نهاية السنة"
        ordering = ["-executed_at", "-id"]

    def __str__(self):
        return f"نهاية {self.academic_year.name}"


class CertificateConfig(models.Model):
    SCOPE_TERM = "term"
    SCOPE_YEAR = "year"
    ISSUANCE_SCOPE_CHOICES = [
        (SCOPE_TERM, "كل فصل دراسي"),
        (SCOPE_YEAR, "كل سنة دراسية"),
    ]

    academic_year = models.OneToOneField(
        AcademicYear,
        on_delete=models.CASCADE,
        related_name="certificate_config",
    )
    issuance_scope = models.CharField(
        max_length=20,
        choices=ISSUANCE_SCOPE_CHOICES,
        default=SCOPE_TERM,
    )
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    is_term_published = models.BooleanField(default=False)
    term_published_at = models.DateTimeField(null=True, blank=True)
    is_year_published = models.BooleanField(default=False)
    year_published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_certificates",
    )
    published_term = models.ForeignKey(
        AcademicTerm,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="certificate_publications",
    )
    honors_enabled = models.BooleanField(default=True)
    honors_min_average = models.DecimalField(max_digits=5, decimal_places=2, default=95)
    honors_title = models.CharField(max_length=120, default="شهادة تقدير")
    honors_message = models.TextField(
        default=(
            "تقديراً للتميز والاجتهاد، تُمنح هذه الشهادة اعترافاً بالمعدل العالي "
            "والأداء المتميز طوال الفترة الدراسية."
        )
    )
    certificate_title = models.CharField(max_length=120, default="شهادة علامات")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "إعدادات الشهادات"
        verbose_name_plural = "إعدادات الشهادات"

    def __str__(self):
        return f"شهادات {self.academic_year.name}"


class ParentGradesSeenState(models.Model):
    parent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="grades_seen_states",
    )
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="grades_seen_states",
    )
    last_seen_at = models.DateTimeField()

    class Meta:
        unique_together = [("parent", "student")]
        verbose_name = "آخر مشاهدة لعلامات ولي الأمر"
        verbose_name_plural = "آخر مشاهدة لعلامات أولياء الأمور"

    def __str__(self):
        return f"{self.parent_id}: {self.student_id}"


class ParentDismissedAlert(models.Model):
    parent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="dismissed_alerts",
    )
    alert_id = models.CharField(max_length=64)
    dismissed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("parent", "alert_id")]
        verbose_name = "إشعار مخفي لولي الأمر"
        verbose_name_plural = "إشعارات مخفية لأولياء الأمور"
        ordering = ["-dismissed_at"]

    def __str__(self):
        return f"{self.parent_id}: {self.alert_id}"
