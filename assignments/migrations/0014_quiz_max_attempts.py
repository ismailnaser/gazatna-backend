from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("assignments", "0013_quiz_review_allowed"),
    ]

    operations = [
        migrations.AddField(
            model_name="quiz",
            name="max_attempts",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="quizsubmission",
            name="attempt_number",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AlterUniqueTogether(
            name="quizsubmission",
            unique_together={("quiz", "student", "attempt_number")},
        ),
    ]
