from django.db import migrations, models
from django.db.models import Count, Q


def split_shared_login_accounts(apps, schema_editor):
    Student = apps.get_model("academics", "Student")
    User = apps.get_model("accounts", "User")

    duplicate_parent_ids = list(
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
        students = list(Student.objects.filter(parent_id=parent_id).order_by("id"))
        for student in students[1:]:
            username = student.student_number
            if not username or User.objects.filter(username=username).exists():
                username = None
            login_user, _password = create_auto_user(
                name=student.name,
                role="parent",
                username=username,
            )
            student.parent_id = login_user.id
            student.save(update_fields=["parent_id"])


class Migration(migrations.Migration):
    dependencies = [
        ("academics", "0026_student_siblings_indexes_upload_validators"),
    ]

    operations = [
        migrations.RunPython(split_shared_login_accounts, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="student",
            constraint=models.UniqueConstraint(
                fields=["parent"],
                condition=Q(parent__isnull=False),
                name="academics_student_unique_login_account",
            ),
        ),
    ]
