from django.db import migrations, models


def assign_initial_sort_order(apps, schema_editor):
    Grade = apps.get_model("academics", "Grade")
    for index, grade in enumerate(Grade.objects.order_by("name", "id")):
        grade.sort_order = index
        grade.save(update_fields=["sort_order"])


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0006_studentdocument"),
    ]

    operations = [
        migrations.AddField(
            model_name="grade",
            name="sort_order",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.RunPython(assign_initial_sort_order, migrations.RunPython.noop),
        migrations.AlterModelOptions(
            name="grade",
            options={
                "ordering": ["sort_order", "name"],
                "verbose_name": "فصل دراسي",
                "verbose_name_plural": "الفصول الدراسية",
            },
        ),
    ]
