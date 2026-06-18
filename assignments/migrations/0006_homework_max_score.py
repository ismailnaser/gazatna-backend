from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("assignments", "0005_homeworkattachment"),
    ]

    operations = [
        migrations.AddField(
            model_name="homework",
            name="max_score",
            field=models.DecimalField(decimal_places=2, default=100, max_digits=5),
        ),
    ]
