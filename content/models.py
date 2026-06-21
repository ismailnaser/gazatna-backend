from django.conf import settings
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


class NewsImage(models.Model):
    news_item = models.ForeignKey(NewsItem, on_delete=models.CASCADE, related_name="images")
    file = models.ImageField(upload_to="news/gallery/")
    is_cover = models.BooleanField(default=False)
    order = models.PositiveSmallIntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "صورة خبر"
        verbose_name_plural = "صور الأخبار"
        ordering = ["order", "id"]


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


class SiteSettings(models.Model):
    """Singleton row — always use SiteSettings.get()."""

    # Hero section
    hero_welcome = models.CharField(max_length=200, default="مرحبا بكم في")
    hero_school_name = models.CharField(max_length=200, default="مدرسة غَزتنا")
    hero_tagline = models.CharField(max_length=300, default="التعليم الرقمي بمعايير عالمية")
    hero_description = models.TextField(
        default="من أصالة الانتماء إلى ريادة المستقبل — منصة تعليمية حديثة تجمع بين التميز الأكاديمي والتقنية، لبناء جيل واعٍ ومبدع في غزة"
    )
    hero_cta_primary = models.CharField(max_length=100, default="ابدأ رحلتك")
    hero_cta_secondary = models.CharField(max_length=100, default="تعرّف علينا")

    # About section
    about_description = models.TextField(
        default="مدرسة غَزتنا مؤسسة تعليمية رقمية تهدف إلى تمكين الطلاب من خلال بيئة تعلم آمنة، مبتكرة، ومتصلة بالمستقبل."
    )
    about_vision = models.TextField(
        default="أن نكون المدرسة الرقمية الرائدة في فلسطين، نُخرّج جيلاً قادراً على المنافسة عالمياً مع الحفاظ على الهوية والقيم الوطنية."
    )
    about_mission = models.TextField(
        default="توفير تعليم عالي الجودة يجمع بين المناهج الأكاديمية والمهارات الرقمية، مع دعم شامل لأولياء الأمور والمجتمع."
    )

    # Footer / contact info
    contact_address = models.CharField(max_length=300, default="غزة، فلسطين")
    contact_phone = models.CharField(max_length=50, default="+970 599 000 000")
    contact_email = models.EmailField(default="info@ghazatna.edu.ps")
    footer_tagline = models.CharField(max_length=300, default="منصة تعليمية رقمية تجمع بين التراث الفلسطيني والتقنية الحديثة.")

    # Registration form fields config (which optional fields to show)
    reg_show_notes = models.BooleanField(default=True)
    reg_show_birth_date = models.BooleanField(default=True)
    reg_grade_choices = models.JSONField(
        default=list,
        help_text="قائمة المراحل الدراسية المتاحة في فورم التسجيل. مثال: [{\"value\":\"primary\",\"label\":\"ابتدائي\"}]",
    )

    # Programs per grade (key: Grade.name, value: description)
    programs_by_grade = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "إعدادات الموقع"
        verbose_name_plural = "إعدادات الموقع"

    @classmethod
    def get(cls) -> "SiteSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class AdmissionStatus(models.TextChoices):
    PENDING = "pending", "قيد المراجعة"
    APPROVED = "approved", "معتمد"
    REJECTED = "rejected", "مرفوض"


class AdmissionApplication(models.Model):
    student_name = models.CharField(max_length=200)
    national_id = models.CharField(max_length=20, blank=True, default="")
    birth_date = models.DateField(null=True, blank=True)
    grade = models.CharField(max_length=50)
    parent_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=50)
    email = models.EmailField(blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=AdmissionStatus.choices, default=AdmissionStatus.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    # When approved we create a Student and link it
    approved_student = models.ForeignKey(
        "academics.Student",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="admission_source",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_admissions",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "طلب قبول/تسجيل"
        verbose_name_plural = "طلبات القبول والتسجيل"


class MessageStatus(models.TextChoices):
    NEW = "new", "جديد"
    ARCHIVED = "archived", "مؤرشف"


class ContactMessage(models.Model):
    name = models.CharField(max_length=200)
    email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=50, blank=True, default="")
    message = models.TextField()
    status = models.CharField(max_length=20, choices=MessageStatus.choices, default=MessageStatus.NEW)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "رسالة تواصل"
        verbose_name_plural = "رسائل تواصل معنا"


class ScheduleType(models.TextChoices):
    EXAM = "exam", "جدول الاختبارات"
    CLASS = "class", "جدول الحصص"


class Schedule(models.Model):
    name = models.CharField(max_length=200)
    schedule_type = models.CharField(max_length=20, choices=ScheduleType.choices)
    school_classes = models.ManyToManyField(
        "academics.SchoolClass",
        related_name="schedules",
        blank=True,
    )
    entries = models.JSONField(default=list, blank=True)
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        verbose_name = "جدول"
        verbose_name_plural = "الجداول"
