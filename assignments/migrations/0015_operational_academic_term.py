from django.db import migrations, models


def assign_current_term(apps, schema_editor):
    AcademicTerm = apps.get_model("academics", "AcademicTerm")
    Homework = apps.get_model("assignments", "Homework")
    Quiz = apps.get_model("assignments", "Quiz")
    SubjectAnnouncement = apps.get_model("assignments", "SubjectAnnouncement")
    SubjectMaterial = apps.get_model("assignments", "SubjectMaterial")
    term = AcademicTerm.objects.filter(is_current=True).order_by("sort_order", "id").first()
    if not term:
        term = AcademicTerm.objects.order_by("-id").first()
    if not term:
        return
    for model in (Homework, Quiz, SubjectAnnouncement, SubjectMaterial):
        model.objects.filter(academic_term__isnull=True).update(academic_term=term)


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0023_operational_term_scope"),
        ("assignments", "0014_quiz_max_attempts"),
    ]

    operations = [
        migrations.AddField(
            model_name="homework",
            name="academic_term",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.CASCADE,
                related_name="homework_items",
                to="academics.academicterm",
            ),
        ),
        migrations.AddField(
            model_name="quiz",
            name="academic_term",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.CASCADE,
                related_name="quizzes",
                to="academics.academicterm",
            ),
        ),
        migrations.AddField(
            model_name="subjectannouncement",
            name="academic_term",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.CASCADE,
                related_name="subject_announcements",
                to="academics.academicterm",
            ),
        ),
        migrations.AddField(
            model_name="subjectmaterial",
            name="academic_term",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.CASCADE,
                related_name="subject_materials",
                to="academics.academicterm",
            ),
        ),
        migrations.RunPython(assign_current_term, migrations.RunPython.noop),
    ]
