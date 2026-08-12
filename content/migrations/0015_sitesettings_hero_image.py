from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("content", "0014_admissionapplication_address"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitesettings",
            name="hero_image",
            field=models.ImageField(blank=True, null=True, upload_to="site/"),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="hero_image_height",
            field=models.CharField(
                default="100dvh",
                help_text="ارتفاع قسم الهيرو (مثل 100dvh أو 80vh أو 600px)",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="hero_image_object_fit",
            field=models.CharField(
                choices=[("cover", "cover"), ("contain", "contain")],
                default="cover",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="hero_image_object_position",
            field=models.CharField(
                default="center top",
                help_text="موضع الصورة داخل الإطار (مثل center top)",
                max_length=50,
            ),
        ),
    ]
