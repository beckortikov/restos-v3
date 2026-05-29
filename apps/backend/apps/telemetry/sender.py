"""Restaurant-side: push telemetry в cloud с offline-буфером.

Поток:
1. collect_telemetry() → payload
2. Сохраняем в PendingTelemetrySnapshot (upsert по business_date)
3. push_pending_to_cloud() пытается отправить все pending записи
4. Успех → delete; ошибка → инкремент attempts, оставляем

Так данные не теряются даже если cloud недоступен N дней.
"""
from __future__ import annotations

from datetime import date

from django.conf import settings
from django.utils import timezone

from .models import PendingTelemetrySnapshot


class TelemetryPushError(Exception):
    """Cloud вернул ошибку или сеть отвалилась."""


def queue_telemetry(*, restaurant, payload: dict) -> PendingTelemetrySnapshot:
    """Положить snapshot в локальный буфер (upsert по business_date)."""
    bdate = date.fromisoformat(payload["business_date"])
    snap, _ = PendingTelemetrySnapshot.objects.update_or_create(
        restaurant_id=restaurant.id,
        business_date=bdate,
        defaults={
            "captured_at": payload["captured_at"],
            "payload": payload,
        },
    )
    return snap


def push_catalog_to_cloud(*, restaurant) -> bool:
    """Отправить снимок каталога меню в cloud. True если успех.

    Каталог НЕ буферизуется при offline (это снимок) — при следующем
    успешном push отправится свежий вариант.
    """
    import requests
    from .collector import collect_catalog

    cloud_base = (settings.CLOUD_BASE_URL or "").rstrip("/")
    api_key = settings.RESTAURANT_API_KEY
    if not cloud_base or not api_key:
        raise TelemetryPushError(
            "CLOUD_BASE_URL / RESTAURANT_API_KEY не заданы",
        )
    payload = collect_catalog(restaurant=restaurant)
    try:
        resp = requests.post(
            f"{cloud_base}/api/v1/telemetry/catalog/",
            headers={"X-Restaurant-Key": api_key},
            json=payload, timeout=30,
        )
    except requests.RequestException as exc:
        raise TelemetryPushError(f"Сеть: {exc}") from exc
    return resp.status_code == 200


def push_pending_to_cloud() -> tuple[int, int]:
    """Шлёт все pending записи в cloud. Возвращает (sent, failed).

    Использует те же settings что и license sync: CLOUD_BASE_URL,
    RESTAURANT_API_KEY.
    """
    import requests

    cloud_base = (settings.CLOUD_BASE_URL or "").rstrip("/")
    api_key = settings.RESTAURANT_API_KEY
    if not cloud_base:
        raise TelemetryPushError("CLOUD_BASE_URL не задан")
    if not api_key:
        raise TelemetryPushError("RESTAURANT_API_KEY не задан")

    url = f"{cloud_base}/api/v1/telemetry/push/"
    sent = failed = 0
    for snap in PendingTelemetrySnapshot.objects.order_by("business_date"):
        try:
            resp = requests.post(
                url,
                headers={"X-Restaurant-Key": api_key},
                json=snap.payload,
                timeout=15,
            )
        except requests.RequestException as exc:
            snap.attempts += 1
            snap.last_attempt_at = timezone.now()
            snap.last_error = f"Сеть: {exc}"[:500]
            snap.save(update_fields=["attempts", "last_attempt_at", "last_error"])
            failed += 1
            continue

        if resp.status_code == 200:
            snap.delete()  # успех → выкидываем из буфера
            sent += 1
        else:
            snap.attempts += 1
            snap.last_attempt_at = timezone.now()
            try:
                body = resp.json()
                code = (body.get("error") or {}).get("code", f"HTTP_{resp.status_code}")
                msg = (body.get("error") or {}).get("message", "")
            except ValueError:
                code, msg = f"HTTP_{resp.status_code}", resp.text[:200]
            snap.last_error = f"[{code}] {msg}"[:500]
            snap.save(update_fields=["attempts", "last_attempt_at", "last_error"])
            failed += 1
    return sent, failed
