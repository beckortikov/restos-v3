"""DRF permission classes для permission-key проверок + manager override.

Использование во views:
    permission_classes = [HasPerm("orders.cancel")]

Manager override flow:
- Кассир пытается сделать действие требующее `manager.override`
  (например, отмена заказа > 1000 TJS) — backend проверяет:
  1. У кассира есть базовый permission (orders.cancel) — да
  2. Сумма > порога — да → нужен manager-pin
- POS вызывает endpoint с `X-Manager-Pin: 9999`
- Backend проверяет PIN, находит manager, audit-логирует override
- Действие выполняется
"""
from rest_framework import permissions

from common.permissions import _enforce_license


def HasPerm(*perm_keys: str):
    """Фабрика permission-класса. Требует наличие ВСЕХ перечисленных perm-keys.

    Пример:
        permission_classes = [HasPerm("orders.cancel")]
    """

    class _HasPermClass(permissions.BasePermission):
        def has_permission(self, request, view) -> bool:
            user = request.user
            if not (user and user.is_authenticated):
                return False
            for key in perm_keys:
                if not user.has_perm_key(key):
                    return False
            _enforce_license(request)
            return True

    _HasPermClass.__name__ = f"HasPerm_{'_'.join(perm_keys)}"
    return _HasPermClass


def verify_manager_override(*, request, restaurant) -> "User | None":
    """Проверить заголовок `X-Manager-Pin` и вернуть User-менеджера.

    Используется в сервисах: «эта операция требует подтверждения менеджера».
    Если PIN валиден и относится к менеджеру/кассиру с `manager.override` —
    возвращает User. Иначе → BusinessError MANAGER_OVERRIDE_REQUIRED (403).

    Audit-лог пишется автоматически.
    """
    from common.exceptions import BusinessError

    from .models import User, UserRole

    pin = request.META.get("HTTP_X_MANAGER_PIN", "").strip()
    if not pin:
        raise BusinessError(
            "MANAGER_OVERRIDE_REQUIRED",
            "Это действие требует подтверждения менеджера. "
            "Введите PIN менеджера.",
            403,
        )
    # Ищем активного юзера с этим PIN'ом в этом ресторане
    candidates = User.objects.filter(
        restaurant=restaurant, is_active=True,
    )
    matched = None
    for u in candidates:
        if u.check_pin(pin):
            matched = u
            break
    if matched is None:
        raise BusinessError(
            "MANAGER_OVERRIDE_INVALID_PIN",
            "Неверный PIN менеджера",
            403,
        )
    # Должен быть Manager или иметь manager.override permission
    if matched.role != UserRole.MANAGER and not matched.has_perm_key(
        "manager.override"
    ):
        raise BusinessError(
            "MANAGER_OVERRIDE_INVALID_USER",
            f"{matched.full_name} не имеет права подтверждать действия",
            403,
        )
    # Audit
    from apps.audit.services import audit_log

    audit_log(
        matched, "manager_override", target=None,
        payload={
            "approved_for_user": request.user.username,
            "endpoint": request.path,
            "method": request.method,
        },
    )
    return matched
