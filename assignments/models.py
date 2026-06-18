import uuid

from django.db import models


class AssignmentStatus(models.TextChoices):
    ACTIVE = "active", "نشط"
    CLOSED = "closed", "مغلق"


class QuestionType(models.TextChoices):
    CHOICE = "choice", "اختيار من متعدد"
    TRUE_FALSE = "true_false", "صح أو خطأ"
    ESSAY = "essay", "مقالي"
    TERM = "term", "مصطلح"
    MATCHING = "matching", "مطابقة"


class Homework(models.Model):
    school_class = models.ForeignKey("academics.SchoolClass", on_delete=models.CASCADE, related_name="homework")
    teacher = models.ForeignKey("staff.TeacherProfile", on_delete=models.CASCADE, related_name="homework")
    subject = models.CharField(max_length=100, blank=True, default="")
    title = models.CharField(max_length=200)
    description = models.TextField()
    due_date = models.DateField()
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    attachment = models.FileField(upload_to="homework/attachments/", blank=True, null=True)
    grades_visible = models.BooleanField(default=False)
    max_score = models.DecimalField(max_digits=5, decimal_places=2, default=100)
    group_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    status = models.CharField(max_length=20, choices=AssignmentStatus.choices, default=AssignmentStatus.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "واجب"
        verbose_name_plural = "الواجبات"
        ordering = ["-created_at"]


class HomeworkAttachment(models.Model):
    homework = models.ForeignKey(Homework, on_delete=models.CASCADE, related_name="attachment_files")
    file = models.FileField(upload_to="homework/attachments/")
    original_name = models.CharField(max_length=255, blank=True, default="")
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "مرفق واجب"
        verbose_name_plural = "مرفقات الواجبات"
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.original_name or self.file.name


class HomeworkSubmission(models.Model):
    homework = models.ForeignKey(Homework, on_delete=models.CASCADE, related_name="submissions")
    student = models.ForeignKey("academics.Student", on_delete=models.CASCADE, related_name="homework_submissions")
    content = models.TextField(blank=True, default="")
    attachment = models.FileField(upload_to="homework/submissions/", blank=True, null=True)
    score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    max_score = models.DecimalField(max_digits=5, decimal_places=2, default=100)
    teacher_note = models.TextField(blank=True, default="")
    graded_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("homework", "student")]
        verbose_name = "تسليم واجب"
        verbose_name_plural = "تسليمات الواجبات"


class Quiz(models.Model):
    school_class = models.ForeignKey("academics.SchoolClass", on_delete=models.CASCADE, related_name="quizzes")
    teacher = models.ForeignKey("staff.TeacherProfile", on_delete=models.CASCADE, related_name="quizzes")
    subject = models.CharField(max_length=100, blank=True, default="")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    due_date = models.DateField()
    start_at = models.DateTimeField()
    end_at = models.DateTimeField(null=True, blank=True)
    duration_minutes = models.PositiveSmallIntegerField(default=30)
    max_attempts = models.PositiveSmallIntegerField(default=1)
    grades_visible = models.BooleanField(default=False)
    review_allowed = models.BooleanField(default=False)
    max_score = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    group_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    status = models.CharField(max_length=20, choices=AssignmentStatus.choices, default=AssignmentStatus.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "اختبار"
        verbose_name_plural = "الاختبارات"
        ordering = ["-created_at"]


class QuizQuestion(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="questions")
    prompt = models.TextField()
    question_type = models.CharField(
        max_length=20,
        choices=QuestionType.choices,
        default=QuestionType.CHOICE,
    )
    options = models.JSONField(default=list)
    correct_index = models.PositiveSmallIntegerField(null=True, blank=True)
    correct_text = models.CharField(max_length=500, blank=True, default="")
    pairs = models.JSONField(default=list)
    points = models.DecimalField(max_digits=5, decimal_places=2, default=1)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order"]
        verbose_name = "سؤال اختبار"
        verbose_name_plural = "أسئلة الاختبارات"


class QuizSubmission(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="submissions")
    student = models.ForeignKey("academics.Student", on_delete=models.CASCADE, related_name="quiz_submissions")
    answers = models.JSONField(default=list)
    auto_score = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    manual_scores = models.JSONField(default=dict, blank=True)
    score = models.DecimalField(max_digits=7, decimal_places=2)
    max_score = models.DecimalField(max_digits=7, decimal_places=2)
    teacher_note = models.TextField(blank=True, default="")
    graded_at = models.DateTimeField(null=True, blank=True)
    attempt_number = models.PositiveSmallIntegerField(default=1)
    time_spent_seconds = models.PositiveIntegerField(default=0)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("quiz", "student", "attempt_number")]
        verbose_name = "تسليم اختبار"
        verbose_name_plural = "تسليمات الاختبارات"


class QuizAnswerAttachment(models.Model):
    submission = models.ForeignKey(
        QuizSubmission, on_delete=models.CASCADE, related_name="answer_attachments"
    )
    question_id = models.BigIntegerField(db_index=True)
    file = models.FileField(upload_to="quiz/answer_attachments/")
    original_name = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "مرفق إجابة اختبار"
        verbose_name_plural = "مرفقات إجابات الاختبارات"
        ordering = ["id"]

    def __str__(self):
        return self.original_name or self.file.name


class SubjectAnnouncement(models.Model):
    school_class = models.ForeignKey(
        "academics.SchoolClass", on_delete=models.CASCADE, related_name="subject_announcements"
    )
    teacher = models.ForeignKey(
        "staff.TeacherProfile", on_delete=models.CASCADE, related_name="subject_announcements"
    )
    subject = models.CharField(max_length=100, blank=True, default="")
    title = models.CharField(max_length=200)
    body = models.TextField()
    group_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "إعلان مادة"
        verbose_name_plural = "إعلانات المواد"


class MaterialCategory(models.TextChoices):
    BOOK = "book", "كتاب / كتيب"
    SLIDES = "slides", "سلايدات"
    RESOURCES = "resources", "مصادر"
    OTHER = "other", "أخرى"


class SubjectMaterial(models.Model):
    school_class = models.ForeignKey(
        "academics.SchoolClass", on_delete=models.CASCADE, related_name="subject_materials"
    )
    teacher = models.ForeignKey(
        "staff.TeacherProfile", on_delete=models.CASCADE, related_name="subject_materials"
    )
    subject = models.CharField(max_length=100, blank=True, default="")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    category = models.CharField(
        max_length=20,
        choices=MaterialCategory.choices,
        default=MaterialCategory.RESOURCES,
    )
    group_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "مرفق مادة"
        verbose_name_plural = "مرفقات المواد"


class SubjectMaterialFile(models.Model):
    material = models.ForeignKey(SubjectMaterial, on_delete=models.CASCADE, related_name="files")
    file = models.FileField(upload_to="subject_materials/")
    original_name = models.CharField(max_length=255, blank=True, default="")
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "ملف مرفق مادة"
        verbose_name_plural = "ملفات مرفقات المواد"

    def __str__(self):
        return self.original_name or self.file.name
