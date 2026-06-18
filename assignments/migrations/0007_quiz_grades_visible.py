from django.db import migrations, models


def show_existing_quiz_grades(apps, schema_editor):
    Quiz = apps.get_model("assignments", "Quiz")
    Quiz.objects.all().update(grades_visible=True)


class Migration(migrations.Migration):

    dependencies = [
        ("assignments", "0006_homework_max_score"),
    ]

    operations = [
        migrations.AddField(
            model_name="quiz",
            name="grades_visible",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(show_existing_quiz_grades, migrations.RunPython.noop),
    ]
