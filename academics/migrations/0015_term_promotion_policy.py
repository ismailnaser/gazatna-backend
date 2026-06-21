from django.db import migrations, models
import django.db.models.deletion


def copy_year_policies_to_terms(apps, schema_editor):
    PromotionPolicy = apps.get_model("academics", "PromotionPolicy")
    AcademicTerm = apps.get_model("academics", "AcademicTerm")

    for policy in PromotionPolicy.objects.select_related("academic_year").all():
        year = policy.academic_year
        if year is None:
            continue
        terms = AcademicTerm.objects.filter(academic_year=year).order_by("sort_order", "id")
        for term in terms:
            PromotionPolicy.objects.create(
                academic_term=term,
                evaluation_scope="single_term",
                year_calculation_method=policy.year_calculation_method,
                evaluation_term_id=None,
                pass_rule=policy.pass_rule,
                pass_minimum_count=policy.pass_minimum_count,
                required_subjects=policy.required_subjects or [],
                pass_score_ratio=policy.pass_score_ratio,
                pass_promotion_mode=policy.pass_promotion_mode,
                fail_handling_mode=policy.fail_handling_mode,
            )
        policy.delete()


def ensure_term_policies_without_year(apps, schema_editor):
    PromotionPolicy = apps.get_model("academics", "PromotionPolicy")
    AcademicTerm = apps.get_model("academics", "AcademicTerm")

    for term in AcademicTerm.objects.order_by("academic_year", "sort_order", "id"):
        PromotionPolicy.objects.get_or_create(
            academic_term=term,
            defaults={
                "evaluation_scope": "single_term",
                "year_calculation_method": "term_average",
                "pass_rule": "minimum_count",
                "pass_minimum_count": 1,
                "required_subjects": [],
                "pass_score_ratio": 0.5,
                "pass_promotion_mode": "automatic",
                "fail_handling_mode": "manual_review",
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("academics", "0014_certificate_config"),
    ]

    operations = [
        migrations.AddField(
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
        migrations.AlterField(
            model_name="promotionpolicy",
            name="academic_year",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="promotion_policy",
                to="academics.academicyear",
            ),
        ),
        migrations.RunPython(copy_year_policies_to_terms, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="promotionpolicy",
            name="academic_year",
        ),
        migrations.AlterField(
            model_name="promotionpolicy",
            name="academic_term",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="promotion_policy",
                to="academics.academicterm",
            ),
        ),
        migrations.RunPython(ensure_term_policies_without_year, migrations.RunPython.noop),
    ]
