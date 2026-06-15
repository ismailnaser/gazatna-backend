from django.db import models


class NewsCategory(models.TextChoices):
    NEWS = "أخبار", "أخبار"
    EVENTS = "فعاليات", "فعاليات"
    ACHIEVEMENTS = "إنجازات", "إنجازات"


class NewsItem(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
    body = models.TextField(blank=True)
    date = models.DateField()
    category = models.CharField(max_length=20, choices=NewsCategory.choices, default=NewsCategory.NEWS)
    gradient = models.CharField(max_length=200, blank=True)
    image = models.ImageField(upload_to="news/", blank=True, null=True)
    featured = models.BooleanField(default=False)
    is_published = models.BooleanField(default=True)

    class Meta:
        verbose_name = "خبر"
        verbose_name_plural = "الأخبار"
        ordering = ["-date"]


class Program(models.Model):
    title = models.CharField(max_length=200)
    grades = models.CharField(max_length=100)
    description = models.TextField()
    features = models.JSONField(default=list)
    accent = models.CharField(max_length=100, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order"]
        verbose_name = "برنامج دراسي"
        verbose_name_plural = "البرامج الدراسية"


class Activity(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order"]
        verbose_name = "نشاط"
        verbose_name_plural = "الأنشطة"


class Alumni(models.Model):
    name = models.CharField(max_length=200)
    year = models.CharField(max_length=10)
    achievement = models.TextField()
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order"]
        verbose_name = "خريج"
        verbose_name_plural = "الخريجون"


class Policy(models.Model):
    title = models.CharField(max_length=200)
    text = models.TextField()
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order"]
        verbose_name = "سياسة"
        verbose_name_plural = "السياسات"


class Accreditation(models.Model):
    name = models.CharField(max_length=200)
    description = models.CharField(max_length=200)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order"]
        verbose_name = "اعتماد"
        verbose_name_plural = "الاعتمادات"


class SchoolStat(models.Model):
    key = models.CharField(max_length=50, unique=True)
    label = models.CharField(max_length=100)
    value = models.CharField(max_length=50)
    icon_name = models.CharField(max_length=50, blank=True)
    icon_bg = models.CharField(max_length=50, blank=True)
    icon_color = models.CharField(max_length=50, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order"]
        verbose_name = "إحصائية"
        verbose_name_plural = "الإحصائيات"


class SchoolValue(models.Model):
    title = models.CharField(max_length=100)
    description = models.TextField()
    number = models.CharField(max_length=10, default="01")
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order"]
        verbose_name = "قيمة مدرسية"
        verbose_name_plural = "القيم المدرسية"
