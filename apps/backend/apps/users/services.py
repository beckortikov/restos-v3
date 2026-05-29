from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from common.exceptions import BusinessError
from common.utils import generate_token

from .models import PinSession, User, UserRole


def login_with_pin(restaurant_id: int, raw_pin: str) -> PinSession:
    if not raw_pin or not raw_pin.isdigit() or not (4 <= len(raw_pin) <= 6):
        raise BusinessError("AUTH_INVALID_PIN", "PIN должен содержать 4–6 цифр", 401)

    # PIN-вход доступен ролям, которые работают на main POS-машине: cashier,
    # cook (KDS), manager (полный доступ). Waiter заходит через JWT с планшета.
    candidates = list(
        User.objects.select_related("restaurant").filter(
            restaurant_id=restaurant_id,
            role__in=(UserRole.CASHIER, UserRole.COOK, UserRole.MANAGER),
            is_active=True,
        )
    )

    matched: User | None = None
    for user in candidates:
        if user.locked_until and user.locked_until > timezone.now():
            continue
        if user.check_pin(raw_pin):
            matched = user
            break

    if matched is None:
        with transaction.atomic():
            for user in candidates:
                if user.locked_until and user.locked_until > timezone.now():
                    continue
                user.failed_pin_attempts += 1
                if user.failed_pin_attempts >= settings.PIN_LOCK_THRESHOLD:
                    user.locked_until = timezone.now() + timedelta(
                        minutes=settings.PIN_LOCK_DURATION_MIN
                    )
                    user.failed_pin_attempts = 0
                user.save(update_fields=["failed_pin_attempts", "locked_until"])
        raise BusinessError("AUTH_INVALID_PIN", "Неверный PIN", 401)

    with transaction.atomic():
        matched.failed_pin_attempts = 0
        matched.locked_until = None
        matched.save(update_fields=["failed_pin_attempts", "locked_until"])

        timeout = (
            matched.restaurant.pin_lock_timeout_min
            if matched.restaurant
            else settings.PIN_SESSION_TIMEOUT_MIN
        )
        session = PinSession.objects.create(
            user=matched,
            token=generate_token(),
            expires_at=timezone.now() + timedelta(minutes=timeout),
        )
        from apps.audit.services import audit_log
        audit_log(matched, "login", target=session, payload={"method": "pin"})
        return session


def authenticate_waiter_by_pin(restaurant_id: int, raw_pin: str) -> User:
    """PIN-аутентификация официанта для planшет-PWA.

    В отличие от login_with_pin (касса/KDS/менеджер → PinSession), здесь
    возвращается сам User — поверх него вызывающий код выписывает JWT
    (access+refresh). Контракт ответа /auth/waiter/pin/ совпадает с
    /auth/login/, поэтому axios-flow и refresh на planшете не меняется.
    """
    if not raw_pin or not raw_pin.isdigit() or not (4 <= len(raw_pin) <= 6):
        raise BusinessError("AUTH_INVALID_PIN", "PIN должен содержать 4–6 цифр", 401)

    candidates = list(
        User.objects.select_related("restaurant").filter(
            restaurant_id=restaurant_id,
            role=UserRole.WAITER,
            is_active=True,
        )
    )

    matched: User | None = None
    for user in candidates:
        if user.locked_until and user.locked_until > timezone.now():
            continue
        if user.check_pin(raw_pin):
            matched = user
            break

    if matched is None:
        with transaction.atomic():
            for user in candidates:
                if user.locked_until and user.locked_until > timezone.now():
                    continue
                user.failed_pin_attempts += 1
                if user.failed_pin_attempts >= settings.PIN_LOCK_THRESHOLD:
                    user.locked_until = timezone.now() + timedelta(
                        minutes=settings.PIN_LOCK_DURATION_MIN
                    )
                    user.failed_pin_attempts = 0
                user.save(update_fields=["failed_pin_attempts", "locked_until"])
        raise BusinessError("AUTH_INVALID_PIN", "Неверный PIN", 401)

    with transaction.atomic():
        matched.failed_pin_attempts = 0
        matched.locked_until = None
        matched.save(update_fields=["failed_pin_attempts", "locked_until"])
        from apps.audit.services import audit_log
        audit_log(matched, "login", target=matched, payload={"method": "pin", "channel": "waiter"})
        return matched
