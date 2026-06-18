from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("assignments", "0003_homework_group_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="quiz",
            name="subject",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
    ]
