from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0008_parentdismissedalert"),
    ]

    operations = [
        migrations.CreateModel(
            name="ClassSubjectAssignment",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "school_class",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="subject_assignments",
                        to="academics.schoolclass",
                    ),
                ),
                (
                    "subject",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="class_assignments",
                        to="academics.subject",
                    ),
                ),
            ],
            options={
                "verbose_name": "إسناد مادة لصف",
                "verbose_name_plural": "إسنادات المواد للصفوف",
                "ordering": ["school_class__name", "subject__name"],
                "unique_together": {("subject", "school_class")},
            },
        ),
    ]
