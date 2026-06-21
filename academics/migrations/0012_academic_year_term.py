from datetime import datetime

from django.db import migrations, models


def seed_academic_calendar(apps, schema_editor):
    AcademicYear = apps.get_model("academics", "AcademicYear")
    AcademicTerm = apps.get_model("academics", "AcademicTerm")
    PromotionPolicy = apps.get_model("academics", "PromotionPolicy")
    SubjectGrade = apps.get_model("academics", "SubjectGrade")
    SubjectGradeScheme = apps.get_model("academics", "SubjectGradeScheme")

    year, _ = AcademicYear.objects.get_or_create(
        name="2025-2026",
        defaults={
            "start_date": datetime(2025, 9, 1).date(),
            "end_date": datetime(2026, 6, 30).date(),
            "status": "active",
            "is_active": True,
        },
    )
    year.status = "active"
    year.is_active = True
    year.save(update_fields=["status", "is_active"])

    term_one, _ = AcademicTerm.objects.get_or_create(
        academic_year=year,
        sort_order=1,
        defaults={
            "name": "الفصل الأول",
            "start_date": datetime(2025, 9, 1).date(),
            "end_date": datetime(2026, 1, 31).date(),
            "is_current": True,
        },
    )
    term_one.is_current = True
    term_one.save(update_fields=["is_current"])

    AcademicTerm.objects.get_or_create(
        academic_year=year,
        sort_order=2,
        defaults={
            "name": "الفصل الثاني",
            "start_date": datetime(2026, 2, 1).date(),
            "end_date": datetime(2026, 6, 30).date(),
            "is_current": False,
        },
    )
    AcademicTerm.objects.filter(academic_year=year).exclude(id=term_one.id).update(is_current=False)

    PromotionPolicy.objects.get_or_create(
        academic_year=year,
        defaults={
            "evaluation_scope": "full_year",
            "year_calculation_method": "term_average",
            "pass_rule": "minimum_count",
            "pass_minimum_count": 1,
            "required_subjects": [],
            "pass_score_ratio": 0.5,
            "pass_promotion_mode": "automatic",
            "fail_handling_mode": "manual_review",
        },
    )

    SubjectGrade.objects.filter(academic_term__isnull=True).update(academic_term=term_one)
    SubjectGradeScheme.objects.filter(academic_term__isnull=True).update(academic_term=term_one)


class Migration(migrations.Migration):
    dependencies = [
        ("academics", "0011_subject_grade_scheme"),
    ]

    operations = [
        migrations.CreateModel(
            name="AcademicYear",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=20, unique=True)),
                ("start_date", models.DateField()),
                ("end_date", models.DateField()),
                ("status", models.CharField(choices=[("draft", "مسودة"), ("active", "نشطة"), ("archived", "مؤرشفة")], default="draft", max_length=20)),
                ("is_active", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "سنة دراسية",
                "verbose_name_plural": "السنوات الدراسية",
                "ordering": ["-start_date", "-id"],
            },
        ),
        migrations.CreateModel(
            name="AcademicTerm",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("sort_order", models.PositiveIntegerField(default=1)),
                ("start_date", models.DateField()),
                ("end_date", models.DateField()),
                ("is_current", models.BooleanField(default=False)),
                ("academic_year", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="terms", to="academics.academicyear")),
            ],
            options={
                "verbose_name": "فصل دراسي",
                "verbose_name_plural": "الفصول الدراسية",
                "ordering": ["academic_year", "sort_order", "id"],
                "unique_together": {("academic_year", "sort_order")},
            },
        ),
        migrations.CreateModel(
            name="PromotionPolicy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("evaluation_scope", models.CharField(choices=[("single_term", "فصل واحد"), ("full_year", "السنة كاملة")], default="full_year", max_length=30)),
                ("year_calculation_method", models.CharField(choices=[("term_average", "متوسط الفصلين"), ("year_total", "مجموع السنة"), ("per_term_combine", "كل فصل على حدة ثم يُجمع القرار"), ("single_term_only", "فصل واحد محدد")], default="term_average", max_length=30)),
                ("pass_rule", models.CharField(choices=[("all_subjects", "جميع المواد"), ("minimum_count", "عدد محدد من المواد")], default="minimum_count", max_length=30)),
                ("pass_minimum_count", models.PositiveIntegerField(default=1)),
                ("required_subjects", models.JSONField(blank=True, default=list)),
                ("pass_score_ratio", models.DecimalField(decimal_places=3, default=0.5, max_digits=4)),
                ("pass_promotion_mode", models.CharField(choices=[("automatic", "تلقائي"), ("manual", "يدوي")], default="automatic", max_length=20)),
                ("fail_handling_mode", models.CharField(choices=[("repeat_auto", "إعادة تلقائية"), ("manual_review", "اعتماد يدوي")], default="manual_review", max_length=20)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("academic_year", models.OneToOneField(on_delete=models.deletion.CASCADE, related_name="promotion_policy", to="academics.academicyear")),
                ("evaluation_term", models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name="promotion_policies", to="academics.academicterm")),
            ],
            options={
                "verbose_name": "سياسة الترفيع",
                "verbose_name_plural": "سياسات الترفيع",
            },
        ),
        migrations.AddField(
            model_name="subjectgrade",
            name="academic_term",
            field=models.ForeignKey(blank=True, null=True, on_delete=models.deletion.CASCADE, related_name="subject_grades", to="academics.academicterm"),
        ),
        migrations.AddField(
            model_name="subjectgradescheme",
            name="academic_term",
            field=models.ForeignKey(blank=True, null=True, on_delete=models.deletion.CASCADE, related_name="grade_schemes", to="academics.academicterm"),
        ),
        migrations.AlterUniqueTogether(
            name="subjectgrade",
            unique_together={("student", "subject", "academic_term")},
        ),
        migrations.AlterUniqueTogether(
            name="subjectgradescheme",
            unique_together={("teacher", "school_class", "subject", "academic_term")},
        ),
        migrations.RunPython(seed_academic_calendar, migrations.RunPython.noop),
    ]
