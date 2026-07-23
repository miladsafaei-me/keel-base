from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="SiteProfile",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("brand_name", models.CharField(default="Keel Site", max_length=120)),
                ("brand_tagline", models.CharField(blank=True, default="", max_length=255)),
                ("primary_domain", models.CharField(blank=True, default="", max_length=255)),
                ("theme_signal", models.CharField(default="data-keel-theme", max_length=64)),
                ("enabled_capabilities", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Site profile",
                "verbose_name_plural": "Site profile",
                "db_table": "keel_base_core_siteprofile",
            },
        ),
    ]
