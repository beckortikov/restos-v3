"""Restaurant-side license sync: достать токен из cloud, кэшировать,
проверять статус по кэшу.

Используется ТОЛЬКО когда `SUPERADMIN_ENABLED=False` (= это ресторанный
инстанс). Cloud-инстанс читает напрямую `License.objects`.

Поток:
1. `refresh_license_token()` → POST в `{CLOUD_BASE_URL}/api/v1/license/issue_token/`
   с заголовком `X-Restaurant-Key: <api_key>`.
2. Cloud возвращает {token, claims, expires_at}.
3. Локально декодируем JWT тем же SECRET_KEY (вендорский общий секрет) и
   проверяем подпись + ttl. Если ок — сохраняем в `LicenseTokenCache`.
4. `_enforce_license` читает кэш + проверяет:
   - is_blocked → 402 LICENSE_BLOCKED
   - expires_at + grace < now → 402 LICENSE_EXPIRED
   - fetched_at < now - LICENSE_TOKEN_MAX_OFFLINE_HOURS → 402 LICENSE_STALE
"""
from __future__ import annotations

from datetime import datetime, timedelta
from datetime import timezone as tz
from typing import TYPE_CHECKING

from django.conf import settings
from django.utils import timezone

if TYPE_CHECKING:
    from .models import LicenseTokenCache

# Grace days после expires_at — те же 7 что и на cloud-стороне.
GRACE_DAYS = 7


class LicenseSyncError(Exception):
    """Ошибки во время refresh (нет связи, неверный ключ, подделка)."""


def is_restaurant_mode() -> bool:
    """True если этот инстанс — ресторанный (читает кэш из cloud).

    На cloud-инстансе (`SUPERADMIN_ENABLED=True`) используем локальную
    `License`-модель как источник правды.
    """
    return not getattr(settings, "SUPERADMIN_ENABLED", False)


def refresh_license_token(*, app_version: str = "") -> "LicenseTokenCache":
    """Делает POST на cloud, получает JWT, кэширует. Бросает LicenseSyncError
    при сетевых/auth ошибках."""
    import jwt
    import requests
    from .models import LicenseTokenCache

    cloud_base = (settings.CLOUD_BASE_URL or "").rstrip("/")
    api_key = settings.RESTAURANT_API_KEY
    if not cloud_base:
        raise LicenseSyncError("CLOUD_BASE_URL не задан в настройках ресторана")
    if not api_key:
        raise LicenseSyncError("RESTAURANT_API_KEY не задан в настройках ресторана")

    url = f"{cloud_base}/api/v1/license/issue_token/"
    try:
        resp = requests.post(
            url,
            headers={"X-Restaurant-Key": api_key},
            json={"app_version": app_version} if app_version else {},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise LicenseSyncError(f"Сеть: {exc}") from exc

    if resp.status_code != 200:
        try:
            body = resp.json()
        except ValueError:
            body = {}
        code = (body.get("error") or {}).get("code", f"HTTP_{resp.status_code}")
        msg = (body.get("error") or {}).get("message", resp.text[:200])
        raise LicenseSyncError(f"[{code}] {msg}")

    data = resp.json().get("data") or {}
    token = data.get("token")
    if not token:
        raise LicenseSyncError("Ответ cloud без поля 'token'")

    # Верифицируем подпись JWT — тем же SECRET_KEY что и cloud.
    # (Простая модель: общий секрет вендора. В будущем можно RS256 + публичный.)
    try:
        claims = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    except jwt.InvalidTokenError as exc:
        raise LicenseSyncError(f"Подпись JWT невалидна: {exc}") from exc

    # Сохраняем в singleton-кэш (id=1)
    cache, _ = LicenseTokenCache.objects.get_or_create(
        id=LicenseTokenCache.SINGLETON_ID,
        defaults={"token": "", "claims": {}},
    )
    cache.token = token
    cache.claims = claims
    cache.plan = claims.get("plan", "")
    exp_iso = claims.get("license_expires_at")
    if exp_iso:
        cache.expires_at = datetime.fromisoformat(exp_iso)
    cache.is_blocked = bool(claims.get("is_blocked", False))
    cache.block_reason = (claims.get("block_reason") or "")[:255]
    cache.save()
    return cache


def get_cached_license() -> "LicenseTokenCache | None":
    """Возвращает singleton-кэш или None если ещё ни разу не refreshили."""
    from .models import LicenseTokenCache

    return LicenseTokenCache.objects.filter(
        id=LicenseTokenCache.SINGLETON_ID,
    ).first()


def evaluate_cached_status() -> tuple[str, str]:
    """Возвращает (code, message) для текущего состояния кэша.

    Разделяет «бизнес-лицензия истекла» от «нет связи с cloud»: POS
    работает offline пока бизнес-лицензия валидна; hard-block только
    когда HARD_OFFLINE_DAYS прошли БЕЗ refresh.

    Коды (только `expired/blocked/stale/missing` → read-only):
      ok       — всё хорошо
      degraded — нет refresh > SOFT_OFFLINE_DAYS, но писать ещё можно
                 (POS показывает баннер «offline N дней»)
      missing  — нет кэша вообще (первая установка без интернета)
      blocked  — vendor явно заблокировал в последнем известном claims
      expired  — бизнес-лицензия + grace реально истекли (по claims)
      stale    — нет refresh > HARD_OFFLINE_DAYS → принудительный read-only
    """
    cache = get_cached_license()
    if cache is None:
        return (
            "missing",
            "Лицензия ещё не получена от cloud. "
            "Запусти `manage.py refresh_license` после настройки RESTAURANT_API_KEY.",
        )

    now = timezone.now()
    age = now - cache.fetched_at
    hard_offline = timedelta(
        days=getattr(settings, "LICENSE_HARD_OFFLINE_DAYS", 30),
    )
    soft_offline = timedelta(
        days=getattr(settings, "LICENSE_SOFT_OFFLINE_DAYS", 2),
    )

    # 1. Vendor явно заблокировал — это последнее что мы знали.
    if cache.is_blocked:
        return ("blocked", cache.block_reason or "Лицензия заблокирована")

    # 2. Бизнес-лицензия реально истекла (+ grace) — независимо от refresh.
    if cache.expires_at is not None:
        grace_end = cache.expires_at + timedelta(days=GRACE_DAYS)
        if now > grace_end:
            return ("expired", "Срок лицензии + grace истёк")

    # 3. Hard-offline guard: нет связи слишком долго.
    if age > hard_offline:
        return (
            "stale",
            f"Нет связи с cloud > {hard_offline.days} дн. "
            "Подключите интернет и обновите лицензию (refresh_license).",
        )

    # 4. Soft-offline: запись разрешена, но баннер.
    if age > soft_offline:
        days_offline = int(age.total_seconds() // 86400)
        return (
            "degraded",
            f"Работа в offline-режиме: последний sync {days_offline} дн. назад.",
        )

    return ("ok", "")


def evaluate_for_enforce(restaurant) -> tuple[bool, str, str, dict]:
    """Унифицированный API для `_enforce_license`:
    возвращает (writable, error_code, error_message, detail_dict).
    """
    if not is_restaurant_mode():
        lic = getattr(restaurant, "license", None)
        if lic is None:
            return (False, "LICENSE_MISSING", "Лицензия не выдана", {})
        detail = {
            "status": lic.status,
            "expires_at": lic.expires_at.isoformat(),
            "grace_until": lic.grace_until.isoformat(),
            "is_blocked": lic.is_blocked,
            "block_reason": lic.block_reason,
        }
        if lic.is_blocked:
            return (False, "LICENSE_BLOCKED",
                    lic.block_reason or "Лицензия заблокирована", detail)
        if not lic.is_writable:
            return (False, "LICENSE_EXPIRED", "Срок лицензии истёк", detail)
        return (True, "", "", {})

    # Restaurant-инстанс
    code, msg = evaluate_cached_status()
    # ok и degraded → write разрешён (degraded = offline-mode с баннером).
    if code in ("ok", "degraded"):
        return (True, "", "", {})
    cache = get_cached_license()
    detail = {}
    if cache is not None:
        detail = {
            "status": code,
            "expires_at": cache.expires_at.isoformat() if cache.expires_at else None,
            "is_blocked": cache.is_blocked,
            "block_reason": cache.block_reason,
            "fetched_at": cache.fetched_at.isoformat(),
        }
    mapping = {
        "missing": "LICENSE_MISSING",
        "blocked": "LICENSE_BLOCKED",
        "expired": "LICENSE_EXPIRED",
        "stale":   "LICENSE_STALE",
    }
    return (False, mapping.get(code, "LICENSE_INVALID"), msg, detail)
