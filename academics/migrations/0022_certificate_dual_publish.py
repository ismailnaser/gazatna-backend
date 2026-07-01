from django.db import migrations, models


def migrate_existing_certificate_publish_flags(apps, schema_editor):
    CertificateConfig = apps.get_model("academics", "CertificateConfig")
    for config in CertificateConfig.objects.all():
        if not config.is_published:
            continue
        if config.issuance_scope == "year":
            config.is_year_published = True
            config.year_published_at = config.published_at
        else:
            config.is_term_published = True
            config.term_published_at = config.published_at
        config.save(
            update_fields=[
                "is_term_published",
                "term_published_at",
                "is_year_published",
                "year_published_at",
            ]
        )


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0021_gradeschemetemplate"),
    ]

    operations = [
        migrations.AddField(
            model_name="certificateconfig",
            name="is_term_published",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="certificateconfig",
            name="term_published_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="certificateconfig",
            name="is_year_published",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="certificateconfig",
            name="year_published_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(migrate_existing_certificate_publish_flags, migrations.RunPython.noop),
    ]
