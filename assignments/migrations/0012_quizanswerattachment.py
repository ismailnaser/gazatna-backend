import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("assignments", "0011_subjectmaterial"),
    ]

    operations = [
        migrations.CreateModel(
            name="QuizAnswerAttachment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("question_id", models.BigIntegerField(db_index=True)),
                ("file", models.FileField(upload_to="quiz/answer_attachments/")),
                ("original_name", models.CharField(blank=True, default="", max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "submission",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="answer_attachments",
                        to="assignments.quizsubmission",
                    ),
                ),
            ],
            options={
                "verbose_name": "مرفق إجابة اختبار",
                "verbose_name_plural": "مرفقات إجابات الاختبارات",
                "ordering": ["id"],
            },
        ),
    ]
