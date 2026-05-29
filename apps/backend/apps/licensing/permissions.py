"""License DRF-permission — режет write-методы при истёкшей лицензии.

Применяется как глобальный `DEFAULT_PERMISSION_CLASSES` в DRF settings.
Работает на уровне DRF view-dispatch (после authentication), в отличие от
Django middleware который видит ещё AnonymousUser.

Логика:
- SAFE_METHODS (GET/HEAD/OPTIONS) → всегда разрешены (read-only режим)
- Write-методы → проверка `License.is_writable`
- ALWAYS_ALLOWED_PATHS (auth/license/heartbeat) → всегда разрешены
- При нарушении возвращает 402 через PermissionDenied + кастомное сообщение
"""
from rest_framework import permissions
from rest_framework.exceptions import APIException


class LicenseExpired(APIException):
    """402 Payment Required с детализацией."""

    status_code = 402
    default_code = "LICENSE_EXPIRED"
    default_detail = "Лицензия истекла"

    def __init__(self, *, code: str, message: str,
                 detail: dict | None = None,
                 status_code: int | None = None):
        self.detail_data = detail or {}
        self.error_code = code
        self.error_message = message
        if status_code is not None:
            self.status_code = status_code
        super().__init__(detail=message)


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

ALWAYS_ALLOWED_PATH_FRAGMENTS = (
    "/auth/",
    "/license/",
    "/heartbeat/",
)


class LicensePermission(permissions.BasePermission):
    def has_permission(self, request, view) -> bool:
        # Read-методы всегда разрешены
        if request.method in SAFE_METHODS:
            return True
        # Анонимы — пусть IsAuthenticated разрулит сам (даст 401)
        user = request.user
        if not user or not user.is_authenticated:
            return True
        # Исключения: auth/license/heartbeat пути
        path = request.path or ""
        if any(p in path for p in ALWAYS_ALLOWED_PATH_FRAGMENTS):
            return True
        # Проверка лицензии ресторана
        rest = getattr(user, "restaurant", None)
        if rest is None:
            return True
        from .models import License

        try:
            lic = rest.license  # OneToOne related
        except License.DoesNotExist:
            raise LicenseExpired(
                code="LICENSE_NOT_FOUND",
                message="Лицензия не выдана. Обратитесь к поставщику.",
                detail={},
            )
        if not lic.is_writable:
            raise LicenseExpired(
                code="LICENSE_EXPIRED" if not lic.is_blocked else "LICENSE_BLOCKED",
                message=(
                    f"Лицензия заблокирована: {lic.block_reason or 'без указания причины'}"
                    if lic.is_blocked
                    else "Лицензия истекла. Продлите подписку для возобновления работы."
                ),
                detail={
                    "status": lic.status,
                    "expires_at": lic.expires_at.isoformat(),
                    "grace_until": lic.grace_until.isoformat(),
                    "is_blocked": lic.is_blocked,
                    "block_reason": lic.block_reason,
                },
            )
        return True
