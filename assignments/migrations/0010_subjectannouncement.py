import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0001_initial"),
        ("staff", "0001_initial"),
        ("assignments", "0009_quizsubmission_manual_grading"),
    ]

    operations = [
        migrations.CreateModel(
            name="SubjectAnnouncement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("subject", models.CharField(blank=True, default="", max_length=100)),
                ("title", models.CharField(max_length=200)),
                ("body", models.TextField()),
                ("group_id", models.UUIDField(db_index=True, default=uuid.uuid4)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "school_class",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="subject_announcements",
                        to="academics.schoolclass",
                    ),
                ),
                (
                    "teacher",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="subject_announcements",
                        to="staff.teacherprofile",
                    ),
                ),
            ],
            options={
                "verbose_name": "إعلان مادة",
                "verbose_name_plural": "إعلانات المواد",
                "ordering": ["-created_at"],
            },
        ),
    ]
