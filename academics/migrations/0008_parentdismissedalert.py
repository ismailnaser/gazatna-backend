from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("academics", "0007_grade_sort_order"),
    ]

    operations = [
        migrations.CreateModel(
            name="ParentDismissedAlert",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("alert_id", models.CharField(max_length=64)),
                ("dismissed_at", models.DateTimeField(auto_now_add=True)),
                (
                    "parent",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="dismissed_alerts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "إشعار مخفي لولي الأمر",
                "verbose_name_plural": "إشعارات مخفية لأولياء الأمور",
                "ordering": ["-dismissed_at"],
                "unique_together": {("parent", "alert_id")},
            },
        ),
    ]
