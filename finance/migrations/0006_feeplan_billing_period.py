from django.db import migrations, models
import django.db.models.deletion


def backfill_fee_plan_academic_year(apps, schema_editor):
    FeePlan = apps.get_model("finance", "FeePlan")
    AcademicYear = apps.get_model("academics", "AcademicYear")
    year = (
        AcademicYear.objects.filter(is_active=True).order_by("-id").first()
        or AcademicYear.objects.order_by("-id").first()
    )
    if year:
        FeePlan.objects.filter(academic_year__isnull=True).update(academic_year_id=year.id)


class Migration(migrations.Migration):
    dependencies = [
        ("academics", "0019_academic_term_closed"),
        ("finance", "0005_backfill_manual_payment_source"),
    ]

    operations = [
        migrations.AddField(
            model_name="feeplan",
            name="billing_period",
            field=models.CharField(
                choices=[("full_year", "السنة الدراسية كاملة"), ("single_term", "فصل دراسي واحد")],
                default="full_year",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="feeplan",
            name="academic_year",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="fee_plans",
                to="academics.academicyear",
            ),
        ),
        migrations.AddField(
            model_name="feeplan",
            name="academic_term",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="fee_plans",
                to="academics.academicterm",
            ),
        ),
        migrations.RunPython(backfill_fee_plan_academic_year, migrations.RunPython.noop),
    ]
