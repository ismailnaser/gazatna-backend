from django.db import migrations, models


def backfill_auto_scores(apps, schema_editor):
    QuizSubmission = apps.get_model("assignments", "QuizSubmission")
    for sub in QuizSubmission.objects.all():
        QuizSubmission.objects.filter(pk=sub.pk).update(auto_score=sub.score)


class Migration(migrations.Migration):

    dependencies = [
        ("assignments", "0008_quiz_enhancements"),
    ]

    operations = [
        migrations.AddField(
            model_name="quizsubmission",
            name="auto_score",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=7),
        ),
        migrations.AddField(
            model_name="quizsubmission",
            name="manual_scores",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="quizsubmission",
            name="teacher_note",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="quizsubmission",
            name="graded_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="quizsubmission",
            name="max_score",
            field=models.DecimalField(decimal_places=2, max_digits=7),
        ),
        migrations.AlterField(
            model_name="quizsubmission",
            name="score",
            field=models.DecimalField(decimal_places=2, max_digits=7),
        ),
        migrations.RunPython(backfill_auto_scores, migrations.RunPython.noop),
    ]
