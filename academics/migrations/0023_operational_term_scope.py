from django.db import migrations, models


def assign_current_term(apps, schema_editor):
    AcademicTerm = apps.get_model("academics", "AcademicTerm")
    ClassSubjectAssignment = apps.get_model("academics", "ClassSubjectAssignment")
    term = AcademicTerm.objects.filter(is_current=True).order_by("sort_order", "id").first()
    if not term:
        term = AcademicTerm.objects.order_by("-id").first()
    if not term:
        return
    ClassSubjectAssignment.objects.filter(academic_term__isnull=True).update(academic_term=term)


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0022_certificate_dual_publish"),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name="classsubjectassignment",
            unique_together=set(),
        ),
        migrations.AddField(
            model_name="classsubjectassignment",
            name="academic_term",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.CASCADE,
                related_name="class_subject_assignments",
                to="academics.academicterm",
            ),
        ),
        migrations.RunPython(assign_current_term, migrations.RunPython.noop),
        migrations.AlterUniqueTogether(
            name="classsubjectassignment",
            unique_together={("subject", "school_class", "academic_term")},
        ),
    ]
