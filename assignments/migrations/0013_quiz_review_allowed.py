from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("assignments", "0012_quizanswerattachment"),
    ]

    operations = [
        migrations.AddField(
            model_name="quiz",
            name="review_allowed",
            field=models.BooleanField(default=False),
        ),
    ]
