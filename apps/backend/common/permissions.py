from rest_framework import permissions


def _enforce_license(request) -> None:
    """Проверка лицензии для write-методов. На SAFE_METHODS — не проверяет.

    Бросает LicenseExpired (HTTP 402) если лицензия истекла или заблокирована.
    Исключения (auth/license/heartbeat пути) — проверка пропускается.
    """
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    user = request.user
    if not user or not user.is_authenticated:
        return
    path = request.path or ""
    if any(p in path for p in ("/auth/", "/license/", "/heartbeat/")):
        return
    rest = getattr(user, "restaurant", None)
    if rest is None:
        return
    from apps.licensing.permissions import LicenseExpired
    from apps.licensing.sync import evaluate_for_enforce

    # SA-7 — machine binding на write-методах
    lic = getattr(rest, "license", None)
    if lic is not None and lic.hardware_uuid:
        header_hwid = request.META.get("HTTP_X_MACHINE_UUID", "").strip()
        if header_hwid != lic.hardware_uuid:
            raise LicenseExpired(
                code="MACHINE_MISMATCH",
                message="Лицензия привязана к другой машине. Обратитесь к поставщику.",
                detail={"required_hardware_uuid_prefix": lic.hardware_uuid[:8] + "…"},
                status_code=403,
            )

    # Унифицированная проверка:
    # - На cloud-инстансе (SUPERADMIN_ENABLED=True) — читает локальную License-модель
    # - На restaurant-инстансе — читает JWT-кэш LicenseTokenCache от cloud
    writable, code, msg, detail = evaluate_for_enforce(rest)
    if writable:
        return
    raise LicenseExpired(code=code, message=msg, detail=detail)


class IsCashier(permissions.BasePermission):
    """Кассир (или менеджер — у него все права)."""

    def has_permission(self, request, view):
        user = request.user
        if not (
            user
            and user.is_authenticated
            and getattr(user, "role", None) in {"cashier", "manager"}
        ):
            return False
        _enforce_license(request)
        return True


class IsWaiter(permissions.BasePermission):
    """Официант (или менеджер)."""

    def has_permission(self, request, view):
        user = request.user
        if not (
            user
            and user.is_authenticated
            and getattr(user, "role", None) in {"waiter", "manager"}
        ):
            return False
        _enforce_license(request)
        return True


class IsCashierOrWaiter(permissions.BasePermission):
    """Кассир, официант или менеджер."""

    def has_permission(self, request, view):
        user = request.user
        if not (
            user
            and user.is_authenticated
            and getattr(user, "role", None) in {"cashier", "waiter", "manager"}
        ):
            return False
        _enforce_license(request)
        return True


class IsAuthenticatedAndLicensed(permissions.IsAuthenticated):
    """IsAuthenticated + license check. Используется в DEFAULT_PERMISSION_CLASSES."""

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        _enforce_license(request)
        return True
