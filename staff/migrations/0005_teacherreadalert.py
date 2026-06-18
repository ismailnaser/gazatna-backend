from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("staff", "0004_teacherprofile_image"),
    ]

    operations = [
        migrations.CreateModel(
            name="TeacherReadAlert",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("alert_key", models.CharField(max_length=80)),
                ("read_at", models.DateTimeField(auto_now_add=True)),
                (
                    "teacher",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="read_teacher_alerts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "إشعار معلم مفتوح",
                "verbose_name_plural": "إشعارات المعلم المفتوحة",
                "ordering": ["-read_at"],
                "unique_together": {("teacher", "alert_key")},
            },
        ),
    ]
