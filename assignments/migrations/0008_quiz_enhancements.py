import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("assignments", "0007_quiz_grades_visible"),
    ]

    operations = [
        migrations.AddField(
            model_name="quiz",
            name="end_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="quiz",
            name="group_id",
            field=models.UUIDField(db_index=True, default=uuid.uuid4),
        ),
        migrations.AddField(
            model_name="quiz",
            name="max_score",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=7),
        ),
        migrations.AddField(
            model_name="quizquestion",
            name="correct_text",
            field=models.CharField(blank=True, default="", max_length=500),
        ),
        migrations.AddField(
            model_name="quizquestion",
            name="pairs",
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name="quizquestion",
            name="points",
            field=models.DecimalField(decimal_places=2, default=1, max_digits=5),
        ),
        migrations.AddField(
            model_name="quizquestion",
            name="question_type",
            field=models.CharField(
                choices=[
                    ("choice", "اختيار من متعدد"),
                    ("true_false", "صح أو خطأ"),
                    ("essay", "مقالي"),
                    ("term", "مصطلح"),
                    ("matching", "مطابقة"),
                ],
                default="choice",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="quizquestion",
            name="correct_index",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
    ]
