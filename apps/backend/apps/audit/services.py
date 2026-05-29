"""Audit service — единая точка для записи в журнал.

Использование:
    from apps.audit.services import audit_log
    audit_log(user, AuditAction.ORDER_CANCEL, target=order, payload={"reason": "..."})

Если user=None (system action) — запись делается с user=None и user_full_name=''.
"""
from __future__ import annotations

from typing import Any

from django.db import models

from .models import AuditAction, AuditEntry


def audit_log(
    user,
    action: str | AuditAction,
    *,
    target: models.Model | None = None,
    payload: dict | None = None,
    restaurant=None,
    ip_address: str | None = None,
) -> AuditEntry:
    """Записать действие в журнал.

    user: User | None — кто действовал
    action: AuditAction (или строка с допустимым кодом)
    target: ORM-объект (Order/User/...) — auto-определяет target_type+id
    payload: произвольный dict (любая JSON-сериализуемая нагрузка)
    restaurant: явно передать ресторан (если user=None или нужно перекрыть)
    """
    action_str = action.value if hasattr(action, "value") else str(action)

    target_type = ""
    target_id: int | None = None
    if target is not None:
        target_type = type(target).__name__
        target_id = getattr(target, "id", None) or getattr(target, "pk", None)

    resto = restaurant
    if resto is None and user is not None:
        resto = getattr(user, "restaurant", None)
    if resto is None and target is not None:
        resto = getattr(target, "restaurant", None)
    if resto is None:
        # Без ресторана запись бессмысленна — не пишем (защита от загрязнения).
        return None  # type: ignore[return-value]

    return AuditEntry.objects.create(
        restaurant=resto,
        user=user if (user and getattr(user, "id", None)) else None,
        user_full_name=getattr(user, "full_name", "") or "",
        action=action_str,
        target_type=target_type,
        target_id=target_id,
        payload=payload or {},
        ip_address=ip_address,
    )


def log_request(request, action: str | AuditAction, **kwargs: Any) -> AuditEntry:
    """Хелпер для DRF view: подставляет user и ip из request."""
    ip = request.META.get("HTTP_X_FORWARDED_FOR") or request.META.get("REMOTE_ADDR")
    if ip and "," in ip:
        ip = ip.split(",")[0].strip()
    return audit_log(
        user=getattr(request, "user", None),
        action=action,
        ip_address=ip if ip else None,
        **kwargs,
    )
