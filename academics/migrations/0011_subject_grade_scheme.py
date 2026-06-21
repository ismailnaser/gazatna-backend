import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0010_student_national_id"),
        ("staff", "0004_teacherprofile_image"),
    ]

    operations = [
        migrations.CreateModel(
            name="SubjectGradeScheme",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("subject", models.CharField(max_length=100)),
                ("max_score", models.DecimalField(decimal_places=2, default=100, max_digits=6)),
                ("components", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "school_class",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="grade_schemes",
                        to="academics.schoolclass",
                    ),
                ),
                (
                    "teacher",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="grade_schemes",
                        to="staff.teacherprofile",
                    ),
                ),
            ],
            options={
                "verbose_name": "تقسيمة علامات مادة",
                "verbose_name_plural": "تقسيمات علامات المواد",
                "ordering": ["-updated_at", "-id"],
                "unique_together": {("teacher", "school_class", "subject")},
            },
        ),
        migrations.CreateModel(
            name="SubjectGradeSchemeEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("scores", models.JSONField(blank=True, default=dict)),
                (
                    "scheme",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="entries",
                        to="academics.subjectgradescheme",
                    ),
                ),
                (
                    "student",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="grade_scheme_entries",
                        to="academics.student",
                    ),
                ),
            ],
            options={
                "verbose_name": "علامة طالب في تقسيمة",
                "verbose_name_plural": "علامات الطلاب في التقسيمات",
                "unique_together": {("scheme", "student")},
            },
        ),
    ]
