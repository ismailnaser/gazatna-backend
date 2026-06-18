from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("content", "0008_admissionapplication_approval_audit"),
    ]

    operations = [
        migrations.AddField(
            model_name="contactmessage",
            name="phone",
            field=models.CharField(blank=True, default="", max_length=50),
        ),
        migrations.AlterField(
            model_name="contactmessage",
            name="email",
            field=models.EmailField(blank=True, default="", max_length=254),
        ),
    ]
