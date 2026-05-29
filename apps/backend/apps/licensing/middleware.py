"""License middleware — блокировка writes при истёкшей/блокированной лицензии.

Применяется ПОСЛЕ AuthenticationMiddleware (нужен request.user). Если у
пользователя есть restaurant и у ресторана `License.is_writable == False`:
- Пропускает GET / HEAD / OPTIONS (read-only mode).
- На прочие методы (POST/PUT/PATCH/DELETE) возвращает 402 Payment Required
  с ErrorEnvelope `{error: {code: "LICENSE_EXPIRED", message: "...",
  detail: {status, expires_at, grace_until}}}`.

Исключения (всегда разрешены):
- /api/v1/auth/* — логин/выход должны работать всегда
- /api/v1/license/status/ — статус лицензии (для баннера)
- /api/v1/heartbeat/ — heartbeat
- /admin/* — Django admin для super-admin'а
"""
import json

from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# Префиксы путей, которые работают даже при истёкшей лицензии (write-методы тоже).
ALWAYS_ALLOWED_PREFIXES = (
    "/api/v1/auth/",
    "/api/v1/license/",
    "/api/v1/heartbeat/",
    "/admin/",
    "/static/",
    "/media/",
)


class LicenseMiddleware(MiddlewareMixin):
    def process_request(self, request):
        path = request.path
        if any(path.startswith(p) for p in ALWAYS_ALLOWED_PREFIXES):
            return None
        # Read-only методы пропускаем всегда (даже на expired).
        if request.method in SAFE_METHODS:
            return None
        # Аноним — пусть DRF сам ответит 401.
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return None
        restaurant = getattr(user, "restaurant", None)
        if restaurant is None:
            return None

        license_obj = getattr(restaurant, "license", None)
        if license_obj is None:
            # Нет лицензии — считаем нелицензированным; в проде вендор обязан
            # сразу при регистрации создать License (хотя бы trial). Если нет
            # — блокируем writes.
            return _license_error(
                "LICENSE_NOT_FOUND",
                "Лицензия не найдена для этого ресторана. Обратитесь к поставщику.",
                {},
            )
        # SA-7 — machine binding: на write-методах сверяем заголовок с привязкой
        if license_obj.hardware_uuid:
            header_hwid = request.META.get("HTTP_X_MACHINE_UUID", "").strip()
            if header_hwid != license_obj.hardware_uuid:
                return _license_error(
                    "MACHINE_MISMATCH",
                    "Лицензия привязана к другой машине. Обратитесь к поставщику.",
                    {"required_hardware_uuid_prefix": license_obj.hardware_uuid[:8] + "…"},
                    status=403,
                )
        # else: hardware_uuid пуст — лицензия не активирована ни на какой машине;
        # пускаем (юзер должен открыть LicenseActivationScreen и привязать).
        if license_obj.is_writable:
            return None
        return _license_error(
            "LICENSE_EXPIRED",
            (
                "Лицензия заблокирована"
                if license_obj.status == "blocked"
                else "Лицензия истекла. Продлите подписку для возобновления работы."
            ),
            {
                "status": license_obj.status,
                "expires_at": license_obj.expires_at.isoformat(),
                "grace_until": license_obj.grace_until.isoformat(),
                "is_blocked": license_obj.is_blocked,
                "block_reason": license_obj.block_reason,
            },
        )


def _license_error(code: str, message: str, detail: dict, status: int = 402) -> JsonResponse:
    return JsonResponse(
        {"error": {"code": code, "message": message, "detail": detail}},
        status=status,
    )
