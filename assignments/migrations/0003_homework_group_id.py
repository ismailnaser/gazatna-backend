import uuid
from collections import defaultdict

from django.db import migrations, models


def backfill_homework_groups(apps, schema_editor):
    Homework = apps.get_model("assignments", "Homework")
    buckets: dict[tuple, list] = defaultdict(list)
    for hw in Homework.objects.all().order_by("created_at", "id"):
        created_key = hw.created_at.replace(microsecond=0) if hw.created_at else None
        key = (
            hw.teacher_id,
            hw.title,
            hw.start_at,
            hw.end_at,
            hw.subject,
            hw.description,
            created_key,
        )
        buckets[key].append(hw.id)

    for ids in buckets.values():
        group = uuid.uuid4()
        Homework.objects.filter(id__in=ids).update(group_id=group)


class Migration(migrations.Migration):

    dependencies = [
        ("assignments", "0002_homework_enhancements"),
    ]

    operations = [
        migrations.AddField(
            model_name="homework",
            name="group_id",
            field=models.UUIDField(db_index=True, default=uuid.uuid4),
        ),
        migrations.RunPython(backfill_homework_groups, migrations.RunPython.noop),
    ]
