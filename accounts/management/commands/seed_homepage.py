"""بذر سريع لمحتوى الصفحة الرئيسية فقط (هيرو + أخبار + إحصائيات)."""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from academics.models import Grade
from content.models import NewsItem, SchoolStat, SiteSettings


class Command(BaseCommand):
    help = "ملء بيانات أقسام الصفحة الرئيسية للمعاينة"

    def handle(self, *args, **options):
        today = timezone.localdate()

        news_items = [
            (
                "افتتاح معمل الحاسوب الجديد",
                "أخبار",
                "تم افتتاح معمل حاسوب مجهّز بأحدث الأجهزة لطلاب المرحلة الابتدائية، مع ورش تعريفية للأهل.",
            ),
            (
                "يوم التطوع المدرسي",
                "فعاليات",
                "شارك الطلاب في حملة تجميل ساحة المدرسة وتشجير الحديقة بالتعاون مع مجلس أولياء الأمور.",
            ),
            (
                "فوز فريق الروبوتيك",
                "إنجازات",
                "حقق فريق غَزتنا للروبوتيك المركز الأول في المسابقة المحلية بعد مشروع ابتكاري مميز.",
            ),
            (
                "ورشة القراءة الإبداعية",
                "فعاليات",
                "ورشة أسبوعية لتعزيز مهارات القراءة والكتابة والتعبير الشفوي لدى طلاب الصفوف الأولى.",
            ),
            (
                "معرض العلوم السنوي",
                "فعاليات",
                "عرض طلاب العلوم تجاربهم ومشاريعهم أمام الأهالي والزوار في قاعة الأنشطة.",
            ),
            (
                "تكريم المتفوقين",
                "إنجازات",
                "حفل تكريم للطلاب المتفوقين في الفصل الدراسي مع شهادات تقدير وهدايا رمزية.",
            ),
        ]
        for i, (title, category, desc) in enumerate(news_items):
            NewsItem.objects.update_or_create(
                title=title,
                defaults={
                    "description": desc,
                    "body": f"{desc}\n\nتفاصيل إضافية ضمن برنامج غَزتنا التعليمي.",
                    "date": today - timedelta(days=i * 3),
                    "category": category,
                    "featured": i < 3,
                    "is_published": True,
                },
            )

        stats = [
            ("students", "طلاب مسجّلون", "320", "Users"),
            ("teachers", "معلمون", "28", "GraduationCap"),
            ("programs", "برامج تعليمية", "12", "Star"),
            ("satisfaction", "رضا الأهالي", "98%", "Star"),
        ]
        for i, (key, label, value, icon) in enumerate(stats):
            SchoolStat.objects.update_or_create(
                key=key,
                defaults={"label": label, "value": value, "icon_name": icon, "order": i},
            )
        SchoolStat.objects.filter(key="years").delete()

        grades = list(Grade.objects.order_by("sort_order", "id"))
        site = SiteSettings.get()
        site.hero_welcome = "مرحبا بكم في"
        site.hero_school_name = "مدرسة غَزتنا الخاصة"
        site.hero_tagline = "التعليم الرقمي بمعايير عالمية"
        site.hero_description = (
            "من أصالة الانتماء إلى ريادة المستقبل — منصة تعليمية حديثة تجمع بين "
            "التميز الأكاديمي والتقنية، لبناء جيل واعٍ ومبدع في غزة"
        )
        site.hero_cta_primary = "ابدأ رحلتك"
        site.hero_cta_secondary = "تعرّف علينا"
        if grades:
            site.reg_grade_choices = [{"value": g.name, "label": g.name} for g in grades]
            site.programs_by_grade = {
                g.name: f"برنامج تعليمي متكامل لـ{g.name}." for g in grades
            }
        site.save()

        self.stdout.write(self.style.SUCCESS("تم تجهيز بيانات الصفحة الرئيسية للمعاينة."))
        self.stdout.write(f"  أخبار منشورة: {NewsItem.objects.filter(is_published=True).count()}")
        self.stdout.write(f"  إحصائيات: {SchoolStat.objects.count()}")
        self.stdout.write(f"  الهيرو: {site.hero_school_name}")
