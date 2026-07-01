from django.db import migrations, models
from django.db.models import Count


def split_shared_login_accounts(apps, schema_editor):
    Student = apps.get_model("academics", "Student")
    User = apps.get_model("accounts", "User")

    duplicate_parent_ids = (
        Student.objects.exclude(parent_id=None)
        .values("parent_id")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
        .values_list("parent_id", flat=True)
    )

    if not duplicate_parent_ids:
        return

    from accounts.utils import create_auto_user

    for parent_id in duplicate_parent_ids:
        students = list(
            Student.objects.filter(parent_id=parent_id).order_by("id")
        )
        for student in students[1:]:
            login_user, _password = create_auto_user(
                name=student.name,
                role="parent",
                username=student.student_number,
            )
            student.parent_id = login_user.id
            student.save(update_fields=["parent_id"])


class Migration(migrations.Migration):
    dependencies = [
        ("academics", "0023_operational_term_scope"),
    ]

    operations = [
        migrations.RunPython(split_shared_login_accounts, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="student",
            constraint=models.UniqueConstraint(
                fields=["parent"],
                condition=models.Q(parent__isnull=False),
                name="academics_student_unique_login_account",
            ),
        ),
    ]
