from django.apps import AppConfig


class LicensingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.licensing"
    verbose_name = "Лицензии"

    def ready(self):
        # Подключаем сигналы (auto-trial для новых ресторанов)
        from . import signals  # noqa: F401
        # Monkey-patch DRF IsAuthenticated: добавляем license check после
        # стандартной проверки auth. Так покрываем все views, которые
        # явно ставят permission_classes=[IsAuthenticated], не меняя их код.
        self._patch_drf_isauthenticated()

    @staticmethod
    def _patch_drf_isauthenticated() -> None:
        from rest_framework.permissions import IsAuthenticated

        from common.permissions import _enforce_license

        original = IsAuthenticated.has_permission

        def patched(self, request, view):
            ok = original(self, request, view)
            if ok:
                _enforce_license(request)
            return ok

        # Идемпотентность: не патчим повторно
        if not getattr(IsAuthenticated, "_license_patched", False):
            IsAuthenticated.has_permission = patched
            IsAuthenticated._license_patched = True
