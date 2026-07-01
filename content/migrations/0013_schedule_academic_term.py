from django.db import migrations, models


def assign_current_term(apps, schema_editor):
    AcademicTerm = apps.get_model("academics", "AcademicTerm")
    Schedule = apps.get_model("content", "Schedule")
    term = AcademicTerm.objects.filter(is_current=True).order_by("sort_order", "id").first()
    if not term:
        term = AcademicTerm.objects.order_by("-id").first()
    if not term:
        return
    Schedule.objects.filter(academic_term__isnull=True).update(academic_term=term)


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0023_operational_term_scope"),
        ("content", "0012_remove_legacy_public_content"),
    ]

    operations = [
        migrations.AddField(
            model_name="schedule",
            name="academic_term",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.CASCADE,
                related_name="schedules",
                to="academics.academicterm",
            ),
        ),
        migrations.RunPython(assign_current_term, migrations.RunPython.noop),
    ]
