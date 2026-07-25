from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0024_student_unique_login_account"),
    ]

    operations = [
        migrations.AddField(
            model_name="student",
            name="parent_phone",
            field=models.CharField(
                blank=True, default="", max_length=50, verbose_name="رقم جوال ولي الأمر"
            ),
        ),
        migrations.AddField(
            model_name="student",
            name="address",
            field=models.CharField(
                blank=True, default="", max_length=300, verbose_name="العنوان"
            ),
        ),
        migrations.AddField(
            model_name="student",
            name="evaluation",
            field=models.TextField(
                blank=True, default="", verbose_name="تقييم الطالب"
            ),
        ),
    ]
