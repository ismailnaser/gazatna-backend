from django.apps import AppConfig


class ProjectConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "config"

    def ready(self) -> None:
        # Import once so @on handlers attach. register() is idempotent.
        import config.event_handlers  # noqa: F401
        from config.cacheops_helpers import patch_file_cache_unpickle_errors
        from config.model_signals import register

        patch_file_cache_unpickle_errors()
        register()
