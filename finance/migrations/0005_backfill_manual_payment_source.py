from django.db import migrations


def backfill_manual_source(apps, schema_editor):
    PaymentNotice = apps.get_model("finance", "PaymentNotice")
    PaymentNotice.objects.filter(note__startswith="دفع يدوي").update(source="manual")


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0004_payment_notice_source"),
    ]

    operations = [
        migrations.RunPython(backfill_manual_source, migrations.RunPython.noop),
    ]
