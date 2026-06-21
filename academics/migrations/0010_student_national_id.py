from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0009_classsubjectassignment"),
    ]

    operations = [
        migrations.AddField(
            model_name="student",
            name="national_id",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
    ]
