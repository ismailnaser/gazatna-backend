from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0027_student_unique_login_account"),
    ]

    operations = [
        migrations.AlterField(
            model_name="schoolclass",
            name="section",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AlterField(
            model_name="student",
            name="section",
            field=models.CharField(max_length=40),
        ),
    ]
