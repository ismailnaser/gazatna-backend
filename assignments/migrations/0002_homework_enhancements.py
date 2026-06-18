from datetime import datetime, time

from django.db import migrations, models
from django.utils import timezone


def backfill_homework_times(apps, schema_editor):
    Homework = apps.get_model("assignments", "Homework")
    for hw in Homework.objects.all().iterator():
        updated = False
        if not hw.start_at and hw.created_at:
            hw.start_at = hw.created_at
            updated = True
        if not hw.end_at and hw.due_date:
            end_naive = datetime.combine(hw.due_date, time(23, 59, 59))
            if timezone.is_naive(end_naive):
                hw.end_at = timezone.make_aware(end_naive, timezone.get_current_timezone())
            else:
                hw.end_at = end_naive
            updated = True
        if updated:
            hw.save(update_fields=["start_at", "end_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("assignments", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="homework",
            name="attachment",
            field=models.FileField(blank=True, null=True, upload_to="homework/attachments/"),
        ),
        migrations.AddField(
            model_name="homework",
            name="end_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="homework",
            name="grades_visible",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="homework",
            name="start_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="homework",
            name="subject",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="homeworksubmission",
            name="attachment",
            field=models.FileField(blank=True, null=True, upload_to="homework/submissions/"),
        ),
        migrations.AddField(
            model_name="homeworksubmission",
            name="graded_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="homeworksubmission",
            name="max_score",
            field=models.DecimalField(decimal_places=2, default=100, max_digits=5),
        ),
        migrations.AddField(
            model_name="homeworksubmission",
            name="score",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True),
        ),
        migrations.AddField(
            model_name="homeworksubmission",
            name="teacher_note",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AlterField(
            model_name="homeworksubmission",
            name="content",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.RunPython(backfill_homework_times, migrations.RunPython.noop),
    ]
