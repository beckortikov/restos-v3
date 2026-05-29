from django.apps import AppConfig


class EventsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.events"
    label = "events"
    verbose_name = "Real-time события (SSE)"

    def ready(self):
        from . import signals  # noqa: F401
