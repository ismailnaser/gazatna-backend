from django.db import migrations, models
import django.db.models.deletion


def migrate_legacy_attachments(apps, schema_editor):
    Homework = apps.get_model("assignments", "Homework")
    HomeworkAttachment = apps.get_model("assignments", "HomeworkAttachment")
    for hw in Homework.objects.exclude(attachment="").exclude(attachment__isnull=True):
        if not hw.attachment:
            continue
        HomeworkAttachment.objects.create(
            homework_id=hw.id,
            file=hw.attachment,
            original_name=hw.attachment.name.split("/")[-1],
            sort_order=0,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("assignments", "0004_quiz_subject"),
    ]

    operations = [
        migrations.CreateModel(
            name="HomeworkAttachment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("file", models.FileField(upload_to="homework/attachments/")),
                ("original_name", models.CharField(blank=True, default="", max_length=255)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "homework",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attachment_files",
                        to="assignments.homework",
                    ),
                ),
            ],
            options={
                "verbose_name": "مرفق واجب",
                "verbose_name_plural": "مرفقات الواجبات",
                "ordering": ["sort_order", "id"],
            },
        ),
        migrations.RunPython(migrate_legacy_attachments, migrations.RunPython.noop),
    ]
