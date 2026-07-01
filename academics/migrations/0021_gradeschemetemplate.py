from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0020_promotionpolicy_is_configured"),
    ]

    operations = [
        migrations.CreateModel(
            name="GradeSchemeTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("max_score", models.DecimalField(decimal_places=2, default=100, max_digits=6)),
                ("components", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "academic_term",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="grade_scheme_template",
                        to="academics.academicterm",
                    ),
                ),
            ],
            options={
                "verbose_name": "تقسيمة علامات موحّدة",
                "verbose_name_plural": "تقسيمات العلامات الموحّدة",
                "ordering": ["-updated_at", "-id"],
            },
        ),
    ]
