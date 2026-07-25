from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("content", "0013_schedule_academic_term"),
    ]

    operations = [
        migrations.AddField(
            model_name="admissionapplication",
            name="address",
            field=models.CharField(
                blank=True, default="", max_length=300, verbose_name="العنوان"
            ),
        ),
    ]
