from django.apps import AppConfig


class OrdersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.orders"
    label = "orders"
    verbose_name = "Заказы"

    def ready(self) -> None:
        # Подключаем signal handlers (auto-seed cancel reasons и т.д.)
        from . import signals  # noqa: F401
