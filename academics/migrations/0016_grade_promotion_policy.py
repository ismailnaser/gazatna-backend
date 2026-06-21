from django.db import migrations, models
import django.db.models.deletion


def _default_policy_values():
    return {
        "evaluation_scope": "single_term",
        "year_calculation_method": "term_average",
        "pass_rule": "minimum_count",
        "pass_minimum_count": 1,
        "required_subjects": [],
        "pass_score_ratio": 0.5,
        "pass_promotion_mode": "automatic",
        "fail_handling_mode": "manual_review",
    }


def migrate_term_policies_to_grades(apps, schema_editor):
    Grade = apps.get_model("academics", "Grade")
    PromotionPolicy = apps.get_model("academics", "PromotionPolicy")

    sample = PromotionPolicy.objects.first()
    defaults = _default_policy_values()
    if sample:
        defaults = {
            "evaluation_scope": sample.evaluation_scope,
            "year_calculation_method": sample.year_calculation_method,
            "pass_rule": sample.pass_rule,
            "pass_minimum_count": sample.pass_minimum_count,
            "required_subjects": sample.required_subjects or [],
            "pass_score_ratio": sample.pass_score_ratio,
            "pass_promotion_mode": sample.pass_promotion_mode,
            "fail_handling_mode": sample.fail_handling_mode,
        }

    for grade in Grade.objects.order_by("sort_order", "id"):
        PromotionPolicy.objects.get_or_create(grade=grade, defaults=defaults)

    PromotionPolicy.objects.filter(grade__isnull=True).delete()


def ensure_grade_policies(apps, schema_editor):
    Grade = apps.get_model("academics", "Grade")
    PromotionPolicy = apps.get_model("academics", "PromotionPolicy")
    defaults = _default_policy_values()

    for grade in Grade.objects.order_by("sort_order", "id"):
        PromotionPolicy.objects.get_or_create(grade=grade, defaults=defaults)


class Migration(migrations.Migration):
    dependencies = [
        ("academics", "0015_term_promotion_policy"),
    ]

    operations = [
        migrations.AddField(
            model_name="promotionpolicy",
            name="grade",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="promotion_policy",
                to="academics.grade",
            ),
        ),
        migrations.AlterField(
            model_name="promotionpolicy",
            name="academic_term",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="promotion_policy",
                to="academics.academicterm",
            ),
        ),
        migrations.RunPython(migrate_term_policies_to_grades, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="promotionpolicy",
            name="academic_term",
        ),
        migrations.AlterField(
            model_name="promotionpolicy",
            name="grade",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="promotion_policy",
                to="academics.grade",
            ),
        ),
        migrations.RunPython(ensure_grade_policies, migrations.RunPython.noop),
    ]
