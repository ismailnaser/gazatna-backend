from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("academics", "0018_parent_grades_notification"),
    ]

    operations = [
        migrations.AddField(
            model_name="academicterm",
            name="is_closed",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="academicterm",
            name="closed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
