from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0010_student_national_id"),
        ("content", "0010_admissionapplication_national_id"),
    ]

    operations = [
        migrations.CreateModel(
            name="Schedule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200)),
                (
                    "schedule_type",
                    models.CharField(
                        choices=[("exam", "جدول الاختبارات"), ("class", "جدول الحصص")],
                        max_length=20,
                    ),
                ),
                ("entries", models.JSONField(blank=True, default=list)),
                ("is_published", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "school_classes",
                    models.ManyToManyField(blank=True, related_name="schedules", to="academics.schoolclass"),
                ),
            ],
            options={
                "verbose_name": "جدول",
                "verbose_name_plural": "الجداول",
                "ordering": ["-updated_at", "-id"],
            },
        ),
    ]
