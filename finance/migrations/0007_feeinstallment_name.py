from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0006_feeplan_billing_period"),
    ]

    operations = [
        migrations.AddField(
            model_name="feeinstallment",
            name="name",
            field=models.CharField(
                blank=True,
                default="",
                max_length=120,
                verbose_name="اسم الدفعة",
            ),
        ),
    ]
