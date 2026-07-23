from django.apps import AppConfig


class KeelBaseConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "keel_base"
    label = "keel_base_core"
    verbose_name = "Keel Base — Core"
