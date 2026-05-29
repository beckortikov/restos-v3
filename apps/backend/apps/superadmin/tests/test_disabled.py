"""Когда `SUPERADMIN_ENABLED=False` (restaurant-режим) — SA полностью недоступен.

Это критическая проверка: владелец заведения не должен иметь возможности
открыть SA-страницу или вызвать SA-API на своём локальном сервере.
"""
from importlib import reload

import pytest
from django.test import override_settings
from django.urls import clear_url_caches


def _refresh_urlconf():
    """Перезагружаем URLconf, чтобы условные `if SUPERADMIN_ENABLED:` пересчитались."""
    from config import urls as cfg_urls

    clear_url_caches()
    reload(cfg_urls)


@pytest.fixture
def restaurant_mode(db):
    """Контекст: SA выключён (= ресторанный деплой)."""
    with override_settings(SUPERADMIN_ENABLED=False):
        _refresh_urlconf()
        yield
    # После теста — возвращаем dev-настройки (SA включён).
    _refresh_urlconf()


def test_sa_web_login_returns_404_when_disabled(client, restaurant_mode):
    resp = client.get("/superadmin/login/")
    assert resp.status_code == 404


def test_sa_web_dashboard_returns_404_when_disabled(client, restaurant_mode):
    resp = client.get("/superadmin/")
    assert resp.status_code == 404


def test_sa_api_login_returns_404_when_disabled(api_client, restaurant_mode):
    resp = api_client.post(
        "/api/v1/superadmin/auth/login/",
        {"username": "vendor", "password": "x"},
        format="json",
    )
    assert resp.status_code == 404


def test_sa_api_restaurants_returns_404_when_disabled(api_client, restaurant_mode):
    resp = api_client.get("/api/v1/superadmin/restaurants/")
    assert resp.status_code == 404


def test_pos_api_still_works_when_sa_disabled(api_client, restaurant_mode, cashier):
    """В ресторанном режиме обычный POS-API должен работать как обычно."""
    resp = api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json",
    )
    assert resp.status_code == 200


def test_django_admin_blocked_in_restaurant_mode(client, db):
    """В ресторанном режиме /admin/ тоже отдаёт 404 — никакой ручной
    правки License через стандартный Django-admin."""
    with override_settings(SUPERADMIN_ENABLED=False, DJANGO_ADMIN_ENABLED=False):
        _refresh_urlconf()
        try:
            resp = client.get("/admin/")
            assert resp.status_code == 404
        finally:
            _refresh_urlconf()


def test_django_admin_available_in_dev_mode(client, db):
    """В dev/cloud-режиме admin доступен (для нас, чтобы лазить вручную)."""
    with override_settings(SUPERADMIN_ENABLED=True, DJANGO_ADMIN_ENABLED=True):
        _refresh_urlconf()
        try:
            resp = client.get("/admin/")
            # 302 (редирект на admin login) — норм; главное не 404.
            assert resp.status_code in (200, 302)
        finally:
            _refresh_urlconf()
