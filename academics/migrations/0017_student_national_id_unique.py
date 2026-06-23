from django.db import migrations, models


def dedupe_student_national_ids(apps, schema_editor):
    Student = apps.get_model("academics", "Student")
    seen: set[str] = set()
    for student in Student.objects.order_by("id"):
        national_id = (student.national_id or "").strip()
        if not national_id:
            continue
        if national_id in seen:
            student.national_id = ""
            student.save(update_fields=["national_id"])
        else:
            seen.add(national_id)


class Migration(migrations.Migration):
    dependencies = [
        ("academics", "0016_grade_promotion_policy"),
    ]

    operations = [
        migrations.RunPython(dedupe_student_national_ids, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="student",
            constraint=models.UniqueConstraint(
                condition=models.Q(("national_id__gt", "")),
                fields=("national_id",),
                name="academics_student_national_id_unique",
            ),
        ),
    ]
