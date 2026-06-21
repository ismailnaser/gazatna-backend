from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("content", "0009_contactmessage_phone"),
    ]

    operations = [
        migrations.AddField(
            model_name="admissionapplication",
            name="national_id",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
    ]
