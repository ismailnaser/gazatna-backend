from django.db import models


class AssignmentStatus(models.TextChoices):
    ACTIVE = "active", "نشط"
    CLOSED = "closed", "مغلق"


class Homework(models.Model):
    school_class = models.ForeignKey("academics.SchoolClass", on_delete=models.CASCADE, related_name="homework")
    teacher = models.ForeignKey("staff.TeacherProfile", on_delete=models.CASCADE, related_name="homework")
    title = models.CharField(max_length=200)
    description = models.TextField()
    due_date = models.DateField()
    status = models.CharField(max_length=20, choices=AssignmentStatus.choices, default=AssignmentStatus.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "واجب"
        verbose_name_plural = "الواجبات"
        ordering = ["-created_at"]


class HomeworkSubmission(models.Model):
    homework = models.ForeignKey(Homework, on_delete=models.CASCADE, related_name="submissions")
    student = models.ForeignKey("academics.Student", on_delete=models.CASCADE, related_name="homework_submissions")
    content = models.TextField()
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("homework", "student")]
        verbose_name = "تسليم واجب"
        verbose_name_plural = "تسليمات الواجبات"


class Quiz(models.Model):
    school_class = models.ForeignKey("academics.SchoolClass", on_delete=models.CASCADE, related_name="quizzes")
    teacher = models.ForeignKey("staff.TeacherProfile", on_delete=models.CASCADE, related_name="quizzes")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    due_date = models.DateField()
    start_at = models.DateTimeField()
    duration_minutes = models.PositiveSmallIntegerField(default=30)
    status = models.CharField(max_length=20, choices=AssignmentStatus.choices, default=AssignmentStatus.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "اختبار"
        verbose_name_plural = "الاختبارات"
        ordering = ["-created_at"]


class QuizQuestion(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="questions")
    prompt = models.TextField()
    options = models.JSONField(default=list)
    correct_index = models.PositiveSmallIntegerField()
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order"]
        verbose_name = "سؤال اختبار"
        verbose_name_plural = "أسئلة الاختبارات"


class QuizSubmission(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="submissions")
    student = models.ForeignKey("academics.Student", on_delete=models.CASCADE, related_name="quiz_submissions")
    answers = models.JSONField(default=list)
    score = models.DecimalField(max_digits=5, decimal_places=2)
    max_score = models.DecimalField(max_digits=5, decimal_places=2)
    time_spent_seconds = models.PositiveIntegerField(default=0)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("quiz", "student")]
        verbose_name = "تسليم اختبار"
        verbose_name_plural = "تسليمات الاختبارات"
