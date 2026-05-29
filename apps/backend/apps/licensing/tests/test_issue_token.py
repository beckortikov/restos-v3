"""Cloud-эндпоинт `/license/issue_token/` — выпуск JWT по api_key ресторана.

Структура:
    - Cloud (SUPERADMIN_ENABLED=True) выдаёт токен по X-Restaurant-Key.
    - Restaurant-инстанс (SUPERADMIN_ENABLED=False) возвращает 404.
    - Токен подписан HS256 SECRET_KEY, содержит claims license.
    - Heartbeat фиксируется как побочный эффект (cloud видит «жив»).
"""
from datetime import timedelta
from importlib import reload

import pytest
from django.test import override_settings
from django.urls import clear_url_caches
from django.utils import timezone

pytestmark = pytest.mark.django_db


def _refresh_urlconf():
    from config import urls as cfg_urls

    clear_url_caches()
    reload(cfg_urls)


# -------- Cloud (SUPERADMIN_ENABLED=True) --------


def test_issue_token_success(api_client, restaurant):
    restaurant.api_key = "test-key-abc123"
    restaurant.save(update_fields=["api_key"])

    resp = api_client.post(
        "/api/v1/license/issue_token/",
        {"app_version": "1.5.0"},
        format="json",
        HTTP_X_RESTAURANT_KEY="test-key-abc123",
    )
    assert resp.status_code == 200, resp.content
    data = resp.json()["data"]
    assert "token" in data
    assert "expires_at" in data
    claims = data["claims"]
    assert claims["iss"] == "restos-cloud"
    assert claims["sub"] == str(restaurant.id)
    assert claims["restaurant_name"] == restaurant.name
    assert claims["plan"] == "trial"  # auto-trial signal
    assert claims["is_blocked"] is False
    # Side effect: heartbeat обновился
    restaurant.refresh_from_db()
    assert restaurant.last_heartbeat_at is not None
    assert restaurant.app_version == "1.5.0"


def test_issue_token_jwt_decodes_with_secret(api_client, restaurant, settings):
    import jwt as pyjwt

    restaurant.api_key = "k-decode"
    restaurant.save(update_fields=["api_key"])
    resp = api_client.post(
        "/api/v1/license/issue_token/",
        {},
        format="json",
        HTTP_X_RESTAURANT_KEY="k-decode",
    )
    token = resp.json()["data"]["token"]
    # Декодируем с тем же секретом — должны получить те же claims
    decoded = pyjwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    assert decoded["sub"] == str(restaurant.id)
    # С неправильным секретом — ошибка подписи
    with pytest.raises(pyjwt.InvalidSignatureError):
        pyjwt.decode(token, "wrong-secret", algorithms=["HS256"])


def test_issue_token_missing_header(api_client, restaurant):
    resp = api_client.post(
        "/api/v1/license/issue_token/", {}, format="json",
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "AUTH_REQUIRED"


def test_issue_token_unknown_key(api_client, restaurant):
    resp = api_client.post(
        "/api/v1/license/issue_token/", {}, format="json",
        HTTP_X_RESTAURANT_KEY="not-in-db",
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "AUTH_INVALID"


def test_issue_token_blocked_license_still_issued(api_client, restaurant):
    """Заблокированная лицензия тоже выдаёт токен — но с is_blocked=True.

    Локальный сервер видит блокировку в claims и переключается в read-only.
    Не получить токен ВООБЩЕ — хуже: ресторан может работать в кеше.
    """
    restaurant.api_key = "k-blocked"
    restaurant.save(update_fields=["api_key"])
    restaurant.license.is_blocked = True
    restaurant.license.block_reason = "Не оплачено"
    restaurant.license.save(update_fields=["is_blocked", "block_reason"])

    resp = api_client.post(
        "/api/v1/license/issue_token/", {}, format="json",
        HTTP_X_RESTAURANT_KEY="k-blocked",
    )
    assert resp.status_code == 200
    claims = resp.json()["data"]["claims"]
    assert claims["is_blocked"] is True
    assert claims["block_reason"] == "Не оплачено"


def test_issue_token_no_license_record(api_client, restaurant):
    """Если у ресторана почему-то нет License — 422."""
    restaurant.api_key = "k-nolic"
    restaurant.save(update_fields=["api_key"])
    restaurant.license.delete()
    resp = api_client.post(
        "/api/v1/license/issue_token/", {}, format="json",
        HTTP_X_RESTAURANT_KEY="k-nolic",
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "NO_LICENSE"


# -------- Restaurant mode (SUPERADMIN_ENABLED=False) — endpoint вернёт 404 --------


def test_issue_token_returns_404_in_restaurant_mode(api_client, restaurant):
    restaurant.api_key = "k-resto"
    restaurant.save(update_fields=["api_key"])
    with override_settings(SUPERADMIN_ENABLED=False):
        _refresh_urlconf()
        try:
            resp = api_client.post(
                "/api/v1/license/issue_token/", {}, format="json",
                HTTP_X_RESTAURANT_KEY="k-resto",
            )
            assert resp.status_code == 404
            assert resp.json()["error"]["code"] == "NOT_AVAILABLE"
        finally:
            _refresh_urlconf()


# -------- Management command --------


def test_generate_api_key_command(db, restaurant):
    from io import StringIO

    from django.core.management import call_command

    out = StringIO()
    call_command(
        "generate_restaurant_api_key",
        "--restaurant-id", str(restaurant.id),
        stdout=out,
    )
    restaurant.refresh_from_db()
    assert len(restaurant.api_key) == 64
    text = out.getvalue()
    assert "RESTAURANT_API_KEY=" in text
    assert restaurant.api_key in text


def test_generate_api_key_command_rotates_existing(db, restaurant):
    from django.core.management import call_command

    restaurant.api_key = "old-key"
    restaurant.save(update_fields=["api_key"])
    call_command(
        "generate_restaurant_api_key",
        "--restaurant-id", str(restaurant.id),
        verbosity=0,
    )
    restaurant.refresh_from_db()
    assert restaurant.api_key != "old-key"
    assert len(restaurant.api_key) == 64


def test_generate_api_key_command_unknown_restaurant(db):
    from django.core.management import call_command
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command(
            "generate_restaurant_api_key",
            "--restaurant-id", "99999",
            verbosity=0,
        )
