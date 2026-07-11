import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


DEFAULT_STAFF_TYPES = [
    ("معلم", True, 1),
    ("مدير", False, 2),
    ("نائب مدير", False, 3),
    ("سكرتير", False, 4),
    ("محاسب", False, 5),
    ("مراقب", False, 6),
]


def seed_staff_types(apps, schema_editor):
    StaffType = apps.get_model("staff", "StaffType")
    for name, is_teacher, sort_order in DEFAULT_STAFF_TYPES:
        StaffType.objects.get_or_create(
            name=name,
            defaults={"is_teacher": is_teacher, "sort_order": sort_order},
        )


def backfill_teacher_profiles(apps, schema_editor):
    StaffType = apps.get_model("staff", "StaffType")
    TeacherProfile = apps.get_model("staff", "TeacherProfile")
    teacher_type = StaffType.objects.filter(is_teacher=True).order_by("sort_order").first()
    if not teacher_type:
        teacher_type = StaffType.objects.create(name="معلم", is_teacher=True, sort_order=1)
    for profile in TeacherProfile.objects.all().order_by("id"):
        updates = []
        if not profile.staff_type_id:
            profile.staff_type_id = teacher_type.id
            updates.append("staff_type_id")
        if not profile.national_id:
            profile.national_id = str(900_000_000 + profile.id).zfill(9)
            updates.append("national_id")
        if updates:
            profile.save(update_fields=updates)


class Migration(migrations.Migration):
    dependencies = [
        ("staff", "0005_teacherreadalert"),
    ]

    operations = [
        migrations.CreateModel(
            name="StaffType",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, unique=True)),
                (
                    "is_teacher",
                    models.BooleanField(
                        default=False,
                        help_text="إذا كان معلماً يُنشأ حساب دخول وتظهر حقول الإسناد التعليمي.",
                    ),
                ),
                ("sort_order", models.PositiveIntegerField(default=0)),
            ],
            options={
                "verbose_name": "نوع الكادر",
                "verbose_name_plural": "أنواع الكادر",
                "ordering": ["sort_order", "name"],
            },
        ),
        migrations.AddField(
            model_name="teacherprofile",
            name="staff_type",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="members",
                to="staff.stafftype",
            ),
        ),
        migrations.AddField(
            model_name="teacherprofile",
            name="name_en",
            field=models.CharField(blank=True, default="", max_length=200, verbose_name="الاسم بالإنجليزي"),
        ),
        migrations.AddField(
            model_name="teacherprofile",
            name="national_id",
            field=models.CharField(
                blank=True,
                default="",
                max_length=9,
                validators=[django.core.validators.RegexValidator("^\\d{9}$", message="رقم الهوية يجب أن يكون 9 أرقام.")],
                verbose_name="رقم الهوية",
            ),
        ),
        migrations.AddField(
            model_name="teacherprofile",
            name="date_of_birth",
            field=models.DateField(blank=True, null=True, verbose_name="تاريخ الميلاد"),
        ),
        migrations.AddField(
            model_name="teacherprofile",
            name="gender",
            field=models.CharField(
                blank=True,
                choices=[("male", "ذكر"), ("female", "أنثى")],
                default="",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="teacherprofile",
            name="marital_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("single", "أعزب/عزباء"),
                    ("married", "متزوج/ة"),
                    ("divorced", "مطلق/ة"),
                    ("widowed", "أرمل/ة"),
                ],
                default="",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="teacherprofile",
            name="mobile",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
        migrations.AddField(
            model_name="teacherprofile",
            name="alt_mobile",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
        migrations.AddField(
            model_name="teacherprofile",
            name="address",
            field=models.TextField(blank=True, default="", verbose_name="مكان السكن"),
        ),
        migrations.AddField(
            model_name="teacherprofile",
            name="join_date",
            field=models.DateField(blank=True, null=True, verbose_name="تاريخ الالتحاق"),
        ),
        migrations.AddField(
            model_name="teacherprofile",
            name="notes",
            field=models.TextField(blank=True, default="", verbose_name="ملاحظات"),
        ),
        migrations.RunPython(seed_staff_types, migrations.RunPython.noop),
        migrations.RunPython(backfill_teacher_profiles, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="teacherprofile",
            name="staff_type",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="members",
                to="staff.stafftype",
            ),
        ),
        migrations.AlterField(
            model_name="teacherprofile",
            name="national_id",
            field=models.CharField(
                max_length=9,
                unique=True,
                validators=[django.core.validators.RegexValidator("^\\d{9}$", message="رقم الهوية يجب أن يكون 9 أرقام.")],
                verbose_name="رقم الهوية",
            ),
        ),
        migrations.AlterModelOptions(
            name="teacherprofile",
            options={"ordering": ["name"], "verbose_name": "عضو كادر", "verbose_name_plural": "الكادر"},
        ),
    ]
