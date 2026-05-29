"""License sync: cloud → restaurant через JWT-токен.

Сценарии:
- refresh_license_token успешно достаёт токен и кэширует claims
- неправильная подпись отклоняется
- restaurant-режим: _enforce_license читает кэш
- blocked в claims → 402 LICENSE_BLOCKED
- expired в claims → 402 LICENSE_EXPIRED
- stale (fetched_at > MAX_OFFLINE_HOURS назад) → 402 LICENSE_STALE
- LicenseStatusView возвращает source=cloud_cache в restaurant-режиме
"""
import time
from datetime import timedelta
from importlib import reload
from unittest.mock import patch

import jwt as pyjwt
import pytest
import responses
from django.conf import settings
from django.test import override_settings
from django.urls import clear_url_caches
from django.utils import timezone

pytestmark = pytest.mark.django_db


def _refresh_urlconf():
    from config import urls as cfg_urls

    clear_url_caches()
    reload(cfg_urls)


# -------- refresh_license_token --------


@responses.activate
def test_refresh_license_token_success(settings, restaurant):
    """Restaurant-инстанс получает JWT, декодирует, кэширует claims."""
    from apps.licensing.models import LicenseTokenCache
    from apps.licensing.sync import refresh_license_token

    # Подделаем cloud-ответ: подпишем токен тем же SECRET_KEY
    now = int(time.time())
    claims = {
        "iss": "restos-cloud",
        "sub": str(restaurant.id),
        "restaurant_name": restaurant.name,
        "plan": "business",
        "license_started_at": "2026-01-01T00:00:00+00:00",
        "license_expires_at": "2027-01-01T00:00:00+00:00",
        "is_blocked": False,
        "block_reason": "",
        "issued_at": now,
        "exp": now + 3600,
    }
    token = pyjwt.encode(claims, settings.SECRET_KEY, algorithm="HS256")

    settings.CLOUD_BASE_URL = "https://cloud.example.com"
    settings.RESTAURANT_API_KEY = "test-key"

    responses.add(
        responses.POST,
        "https://cloud.example.com/api/v1/license/issue_token/",
        json={"data": {"token": token, "expires_at": now + 3600, "claims": claims}},
        status=200,
    )

    cache = refresh_license_token(app_version="1.0.0")
    assert cache.plan == "business"
    assert cache.is_blocked is False
    assert cache.claims["restaurant_name"] == restaurant.name
    # Singleton — id всегда 1
    assert LicenseTokenCache.objects.count() == 1


@responses.activate
def test_refresh_rejects_invalid_signature(settings, restaurant):
    """Если токен подписан НЕ нашим SECRET_KEY — отвергаем."""
    from apps.licensing.sync import LicenseSyncError, refresh_license_token

    bad_token = pyjwt.encode({"sub": "1"}, "WRONG-SECRET", algorithm="HS256")
    settings.CLOUD_BASE_URL = "https://cloud.example.com"
    settings.RESTAURANT_API_KEY = "test-key"
    responses.add(
        responses.POST,
        "https://cloud.example.com/api/v1/license/issue_token/",
        json={"data": {"token": bad_token, "claims": {}}},
        status=200,
    )
    with pytest.raises(LicenseSyncError) as exc:
        refresh_license_token()
    assert "подпись" in str(exc.value).lower() or "signature" in str(exc.value).lower()


def test_refresh_requires_settings(settings, restaurant):
    """Без CLOUD_BASE_URL или RESTAURANT_API_KEY — ошибка."""
    from apps.licensing.sync import LicenseSyncError, refresh_license_token

    settings.CLOUD_BASE_URL = ""
    settings.RESTAURANT_API_KEY = ""
    with pytest.raises(LicenseSyncError) as exc:
        refresh_license_token()
    assert "CLOUD_BASE_URL" in str(exc.value)


# -------- evaluate_cached_status --------


def test_evaluate_missing_when_no_cache(db, settings):
    settings.SUPERADMIN_ENABLED = False
    from apps.licensing.sync import evaluate_cached_status

    code, msg = evaluate_cached_status()
    assert code == "missing"


def test_evaluate_ok_when_cache_fresh(db, settings, restaurant):
    settings.SUPERADMIN_ENABLED = False
    from apps.licensing.models import LicenseTokenCache
    from apps.licensing.sync import evaluate_cached_status

    LicenseTokenCache.objects.create(
        id=1, token="x", claims={}, plan="business",
        expires_at=timezone.now() + timedelta(days=30),
        is_blocked=False,
    )
    code, _ = evaluate_cached_status()
    assert code == "ok"


def test_evaluate_blocked(db, settings, restaurant):
    settings.SUPERADMIN_ENABLED = False
    from apps.licensing.models import LicenseTokenCache
    from apps.licensing.sync import evaluate_cached_status

    LicenseTokenCache.objects.create(
        id=1, token="x", claims={}, plan="business",
        expires_at=timezone.now() + timedelta(days=30),
        is_blocked=True, block_reason="Неуплата",
    )
    code, msg = evaluate_cached_status()
    assert code == "blocked"
    assert "Неуплата" in msg


def test_evaluate_expired_after_grace(db, settings, restaurant):
    settings.SUPERADMIN_ENABLED = False
    from apps.licensing.models import LicenseTokenCache
    from apps.licensing.sync import evaluate_cached_status

    # Истекло 30 дней назад → grace (7 дней) тоже прошёл
    LicenseTokenCache.objects.create(
        id=1, token="x", claims={}, plan="business",
        expires_at=timezone.now() - timedelta(days=30),
    )
    code, _ = evaluate_cached_status()
    assert code == "expired"


def test_evaluate_stale_only_after_hard_offline_days(db, settings, restaurant):
    """stale = read-only возникает ТОЛЬКО когда нет refresh > HARD_OFFLINE_DAYS."""
    settings.SUPERADMIN_ENABLED = False
    settings.LICENSE_HARD_OFFLINE_DAYS = 30
    settings.LICENSE_SOFT_OFFLINE_DAYS = 2
    from apps.licensing.models import LicenseTokenCache
    from apps.licensing.sync import evaluate_cached_status

    LicenseTokenCache.objects.create(
        id=1, token="x", claims={}, plan="business",
        expires_at=timezone.now() + timedelta(days=365),
    )
    LicenseTokenCache.objects.filter(id=1).update(
        fetched_at=timezone.now() - timedelta(days=31),
    )
    code, _ = evaluate_cached_status()
    assert code == "stale"


def test_evaluate_degraded_in_soft_offline_window(db, settings, restaurant):
    """3-29 дней без refresh = degraded — баннер, но write ещё разрешён."""
    settings.SUPERADMIN_ENABLED = False
    settings.LICENSE_HARD_OFFLINE_DAYS = 30
    settings.LICENSE_SOFT_OFFLINE_DAYS = 2
    from apps.licensing.models import LicenseTokenCache
    from apps.licensing.sync import evaluate_cached_status, evaluate_for_enforce

    LicenseTokenCache.objects.create(
        id=1, token="x", claims={}, plan="business",
        expires_at=timezone.now() + timedelta(days=365),
    )
    LicenseTokenCache.objects.filter(id=1).update(
        fetched_at=timezone.now() - timedelta(days=10),
    )
    code, msg = evaluate_cached_status()
    assert code == "degraded"
    # Write РАЗРЕШЁН в degraded
    writable, *_ = evaluate_for_enforce(restaurant)
    assert writable is True


def test_offline_long_time_but_business_license_valid_still_writable(
    db, settings, restaurant,
):
    """Главный кейс правильного дизайна: 20 дней без интернета,
    но business license валидна → write OK (баннер degraded)."""
    settings.SUPERADMIN_ENABLED = False
    settings.LICENSE_HARD_OFFLINE_DAYS = 30
    settings.LICENSE_SOFT_OFFLINE_DAYS = 2
    from apps.licensing.models import LicenseTokenCache
    from apps.licensing.sync import evaluate_for_enforce

    LicenseTokenCache.objects.create(
        id=1, token="x", claims={}, plan="business",
        expires_at=timezone.now() + timedelta(days=200),
        is_blocked=False,
    )
    LicenseTokenCache.objects.filter(id=1).update(
        fetched_at=timezone.now() - timedelta(days=20),
    )
    writable, code, _, _ = evaluate_for_enforce(restaurant)
    assert writable is True
    assert code == ""


# -------- _enforce_license использует sync --------


@pytest.fixture
def cashier_token(api_client, cashier):
    resp = api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json",
    )
    return resp.json()["data"]["session_token"]


def test_enforce_license_blocked_in_restaurant_mode(
    api_client, settings, restaurant, cashier, cashier_token,
):
    """В restaurant-режиме write возвращает 402 LICENSE_BLOCKED если кэш заблокирован."""
    settings.SUPERADMIN_ENABLED = False
    from apps.licensing.models import LicenseTokenCache

    LicenseTokenCache.objects.create(
        id=1, token="x", claims={}, plan="business",
        expires_at=timezone.now() + timedelta(days=30),
        is_blocked=True, block_reason="Не оплачено",
    )
    # Создание заказа должно вернуть 402
    from uuid import uuid4
    resp = api_client.post(
        "/api/v1/orders/",
        {
            "order_type": "takeaway",
            "guests_count": 1,
            "items": [{"menu_item_id": 999, "qty": 1}],
        },
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert resp.status_code == 402
    assert resp.json()["error"]["code"] == "LICENSE_BLOCKED"


def test_enforce_license_stale_hard_offline(
    api_client, settings, restaurant, cashier, cashier_token,
):
    """Hard-offline (> 30 дней без refresh) → 402 LICENSE_STALE."""
    settings.SUPERADMIN_ENABLED = False
    settings.LICENSE_HARD_OFFLINE_DAYS = 30
    from apps.licensing.models import LicenseTokenCache

    LicenseTokenCache.objects.create(
        id=1, token="x", claims={}, plan="business",
        expires_at=timezone.now() + timedelta(days=200),
        is_blocked=False,
    )
    LicenseTokenCache.objects.filter(id=1).update(
        fetched_at=timezone.now() - timedelta(days=31),
    )
    from uuid import uuid4
    resp = api_client.post(
        "/api/v1/orders/",
        {
            "order_type": "takeaway", "guests_count": 1,
            "items": [{"menu_item_id": 999, "qty": 1}],
        },
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert resp.status_code == 402
    assert resp.json()["error"]["code"] == "LICENSE_STALE"


# -------- LicenseStatusView в restaurant-режиме --------


def test_status_returns_cache_in_restaurant_mode(
    api_client, settings, restaurant, cashier, cashier_token,
):
    settings.SUPERADMIN_ENABLED = False
    from apps.licensing.models import LicenseTokenCache

    LicenseTokenCache.objects.create(
        id=1, token="x", claims={"plan": "pro"}, plan="pro",
        expires_at=timezone.now() + timedelta(days=10),
        is_blocked=False,
    )
    resp = api_client.get(
        "/api/v1/license/status/",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["source"] == "cloud_cache"
    assert data["plan"] == "pro"
    assert data["is_writable"] is True


def test_status_returns_master_in_cloud_mode(
    api_client, settings, restaurant, cashier, cashier_token,
):
    settings.SUPERADMIN_ENABLED = True
    # У restaurant фикстуры есть auto-trial лицензия
    resp = api_client.get(
        "/api/v1/license/status/",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["source"] == "master"
    assert data["plan"] == "trial"


# -------- Auto-trial signal gating --------


def test_auto_trial_signal_skipped_in_restaurant_mode(settings, db):
    """В ресторанном режиме создание Restaurant НЕ создаёт локальную License."""
    settings.SUPERADMIN_ENABLED = False
    from apps.licensing.models import License
    from apps.users.models import Restaurant

    before = License.objects.count()
    Restaurant.objects.create(name="No-license restaurant", currency="TJS")
    after = License.objects.count()
    assert after == before  # ни одной новой License не создалось


def test_auto_trial_signal_fires_in_cloud_mode(settings, db):
    """В cloud-режиме создание Restaurant создаёт триал-лицензию."""
    settings.SUPERADMIN_ENABLED = True
    from apps.licensing.models import License
    from apps.users.models import Restaurant

    r = Restaurant.objects.create(name="With-license restaurant", currency="TJS")
    assert License.objects.filter(restaurant=r).exists()
