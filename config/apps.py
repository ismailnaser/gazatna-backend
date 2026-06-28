from django.apps import AppConfig


class ProjectConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "config"

    def ready(self) -> None:
        import config.event_handlers  # noqa: F401
        from config.model_signals import register

        register()
