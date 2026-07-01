from django.db import migrations, models


def mark_existing_configured_policies(apps, schema_editor):
    PromotionPolicy = apps.get_model("academics", "PromotionPolicy")
    for policy in PromotionPolicy.objects.all():
        required_subjects = policy.required_subjects or []
        if (
            policy.pass_minimum_count != 1
            or policy.pass_rule != "minimum_count"
            or len(required_subjects) > 0
            or policy.pass_promotion_mode != "automatic"
            or policy.fail_handling_mode != "manual_review"
            or policy.evaluation_scope != "single_term"
        ):
            policy.is_configured = True
            policy.save(update_fields=["is_configured"])


class Migration(migrations.Migration):
    dependencies = [
        ("academics", "0019_academic_term_closed"),
    ]

    operations = [
        migrations.AddField(
            model_name="promotionpolicy",
            name="is_configured",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(mark_existing_configured_policies, migrations.RunPython.noop),
    ]
