from django.apps import AppConfig


class MenuConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.menu"
    label = "menu"
    verbose_name = "Меню"

    def ready(self) -> None:
        from . import signals  # noqa: F401
        from . import signals_techcard  # noqa: F401  Phase 7C auto-recalc cogs
