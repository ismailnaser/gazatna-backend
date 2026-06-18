import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0001_initial"),
        ("staff", "0001_initial"),
        ("assignments", "0010_subjectannouncement"),
    ]

    operations = [
        migrations.CreateModel(
            name="SubjectMaterial",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("subject", models.CharField(blank=True, default="", max_length=100)),
                ("title", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True, default="")),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("book", "كتاب / كتيب"),
                            ("slides", "سلايدات"),
                            ("resources", "مصادر"),
                            ("other", "أخرى"),
                        ],
                        default="resources",
                        max_length=20,
                    ),
                ),
                ("group_id", models.UUIDField(db_index=True, default=uuid.uuid4)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "school_class",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="subject_materials",
                        to="academics.schoolclass",
                    ),
                ),
                (
                    "teacher",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="subject_materials",
                        to="staff.teacherprofile",
                    ),
                ),
            ],
            options={
                "verbose_name": "مرفق مادة",
                "verbose_name_plural": "مرفقات المواد",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="SubjectMaterialFile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("file", models.FileField(upload_to="subject_materials/")),
                ("original_name", models.CharField(blank=True, default="", max_length=255)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "material",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="files",
                        to="assignments.subjectmaterial",
                    ),
                ),
            ],
            options={
                "verbose_name": "ملف مرفق مادة",
                "verbose_name_plural": "ملفات مرفقات المواد",
                "ordering": ["sort_order", "id"],
            },
        ),
    ]
