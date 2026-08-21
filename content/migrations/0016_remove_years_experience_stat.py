from django.db import migrations


def delete_years_stat(apps, schema_editor):
    SchoolStat = apps.get_model("content", "SchoolStat")
    SchoolStat.objects.filter(key="years").delete()
    SchoolStat.objects.filter(label__icontains="سنوات خبرة").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("content", "0015_sitesettings_hero_image"),
    ]

    operations = [
        migrations.RunPython(delete_years_stat, migrations.RunPython.noop),
    ]
