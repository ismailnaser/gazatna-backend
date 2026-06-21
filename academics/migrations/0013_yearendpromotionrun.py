from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):
    dependencies = [
        ("academics", "0012_academic_year_term"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="YearEndPromotionRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("executed", "منفّذ")], default="executed", max_length=20)),
                ("summary", models.JSONField(blank=True, default=dict)),
                ("student_results", models.JSONField(blank=True, default=list)),
                ("executed_at", models.DateTimeField(auto_now_add=True)),
                (
                    "academic_year",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="promotion_runs",
                        to="academics.academicyear",
                    ),
                ),
                (
                    "executed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="promotion_runs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "new_academic_year",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_from_runs",
                        to="academics.academicyear",
                    ),
                ),
            ],
            options={
                "verbose_name": "تنفيذ نهاية سنة",
                "verbose_name_plural": "تنفيذات نهاية السنة",
                "ordering": ["-executed_at", "-id"],
            },
        ),
    ]
