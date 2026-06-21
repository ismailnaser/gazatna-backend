from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


def seed_certificate_configs(apps, schema_editor):
    AcademicYear = apps.get_model("academics", "AcademicYear")
    CertificateConfig = apps.get_model("academics", "CertificateConfig")
    for year in AcademicYear.objects.all():
        CertificateConfig.objects.get_or_create(
            academic_year=year,
            defaults={
                "honors_message": (
                    "تقديراً للتميز والاجتهاد، تُمنح هذه الشهادة اعترافاً بالمعدل العالي "
                    "والأداء المتميز طوال الفترة الدراسية."
                )
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("academics", "0013_yearendpromotionrun"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CertificateConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "issuance_scope",
                    models.CharField(
                        choices=[("term", "كل فصل دراسي"), ("year", "كل سنة دراسية")],
                        default="term",
                        max_length=20,
                    ),
                ),
                ("is_published", models.BooleanField(default=False)),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                ("honors_enabled", models.BooleanField(default=True)),
                ("honors_min_average", models.DecimalField(decimal_places=2, default=95, max_digits=5)),
                ("honors_title", models.CharField(default="شهادة تقدير", max_length=120)),
                (
                    "honors_message",
                    models.TextField(
                        default=(
                            "تقديراً للتميز والاجتهاد، تُمنح هذه الشهادة اعترافاً بالمعدل العالي "
                            "والأداء المتميز طوال الفترة الدراسية."
                        )
                    ),
                ),
                ("certificate_title", models.CharField(default="شهادة علامات", max_length=120)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "academic_year",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="certificate_config",
                        to="academics.academicyear",
                    ),
                ),
                (
                    "published_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="published_certificates",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "published_term",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="certificate_publications",
                        to="academics.academicterm",
                    ),
                ),
            ],
            options={
                "verbose_name": "إعدادات الشهادات",
                "verbose_name_plural": "إعدادات الشهادات",
            },
        ),
        migrations.RunPython(seed_certificate_configs, migrations.RunPython.noop),
    ]
