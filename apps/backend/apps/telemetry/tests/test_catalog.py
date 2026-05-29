"""Telemetry catalog: восстановление меню/категорий ресторана на cloud."""
from decimal import Decimal

import pytest
import responses
from django.test import override_settings
from django.utils import timezone

pytestmark = pytest.mark.django_db


# -------- collect_catalog --------


@pytest.fixture
def menu_setup(restaurant):
    from apps.menu.models import Category, MenuItem

    hot = Category.objects.create(restaurant=restaurant, name="Горячее", sort_order=1)
    drinks = Category.objects.create(restaurant=restaurant, name="Напитки", sort_order=2)
    MenuItem.objects.create(
        restaurant=restaurant, category=hot, name="Плов",
        price=Decimal("45.00"), kind="hot_kitchen",
    )
    MenuItem.objects.create(
        restaurant=restaurant, category=hot, name="Лагман",
        price=Decimal("40.00"), kind="hot_kitchen",
    )
    MenuItem.objects.create(
        restaurant=restaurant, category=drinks, name="Чай",
        price=Decimal("8.00"), kind="drink", is_available=False,
    )
    return {"hot": hot, "drinks": drinks}


def test_collect_catalog_structure(restaurant, menu_setup):
    from apps.telemetry.collector import collect_catalog

    payload = collect_catalog(restaurant=restaurant)
    assert payload["restaurant"]["name"] == restaurant.name
    assert payload["restaurant"]["currency"] == restaurant.currency
    # 2 категории
    assert len(payload["categories"]) == 2
    cat_names = [c["name"] for c in payload["categories"]]
    assert "Горячее" in cat_names
    # 3 блюда (1 unavailable)
    assert payload["totals"]["items"] == 3
    assert payload["totals"]["active_items"] == 2
    # У Горячего — 2 блюда
    hot = next(c for c in payload["categories"] if c["name"] == "Горячее")
    assert hot["items_count"] == 2


def test_collect_catalog_excludes_sensitive_fields(restaurant, menu_setup):
    """Catalog НЕ должен содержать cogs / cook_time_min / ingredients."""
    from apps.telemetry.collector import collect_catalog

    payload = collect_catalog(restaurant=restaurant)
    for item in payload["items"]:
        assert "cogs" not in item
        assert "cook_time_min" not in item
        assert "image_url" not in item


# -------- push_catalog_to_cloud --------


@responses.activate
def test_push_catalog_to_cloud_success(settings, restaurant, menu_setup):
    from apps.telemetry.sender import push_catalog_to_cloud

    settings.CLOUD_BASE_URL = "https://cloud.example.com"
    settings.RESTAURANT_API_KEY = "test-key"
    responses.add(
        responses.POST,
        "https://cloud.example.com/api/v1/telemetry/catalog/",
        json={"data": {"ok": True, "items": 3, "categories": 2}},
        status=200,
    )
    ok = push_catalog_to_cloud(restaurant=restaurant)
    assert ok is True
    # Проверим что отправленный payload содержит блюда
    request_body = responses.calls[0].request.body
    assert b"Plov".lower() or b"\xd0\x9f\xd0\xbb\xd0\xbe\xd0\xb2" in request_body  # UTF-8 "Плов"


@responses.activate
def test_push_catalog_returns_false_on_error(settings, restaurant, menu_setup):
    from apps.telemetry.sender import push_catalog_to_cloud

    settings.CLOUD_BASE_URL = "https://cloud.example.com"
    settings.RESTAURANT_API_KEY = "test-key"
    responses.add(
        responses.POST,
        "https://cloud.example.com/api/v1/telemetry/catalog/",
        json={"error": {"code": "AUTH_INVALID"}},
        status=401,
    )
    ok = push_catalog_to_cloud(restaurant=restaurant)
    assert ok is False


# -------- Cloud endpoint POST /telemetry/catalog/ --------


def test_cloud_catalog_push_creates_snapshot(
    api_client, settings, restaurant, menu_setup,
):
    settings.SUPERADMIN_ENABLED = True
    restaurant.api_key = "test-key-abc"
    restaurant.save(update_fields=["api_key"])

    from apps.telemetry.collector import collect_catalog

    payload = collect_catalog(restaurant=restaurant)
    resp = api_client.post(
        "/api/v1/telemetry/catalog/", payload, format="json",
        HTTP_X_RESTAURANT_KEY="test-key-abc",
    )
    assert resp.status_code == 200, resp.content
    data = resp.json()["data"]
    assert data["categories"] == 2
    assert data["items"] == 3
    assert data["active_items"] == 2

    from apps.telemetry.models import RestaurantCatalogSnapshot

    snap = RestaurantCatalogSnapshot.objects.get(restaurant=restaurant)
    assert snap.items_count == 3
    assert snap.active_items_count == 2
    assert snap.data["restaurant"]["name"] == restaurant.name


def test_cloud_catalog_push_upserts(
    api_client, settings, restaurant, menu_setup,
):
    """Повторный push обновляет существующий snapshot (один на ресторан)."""
    settings.SUPERADMIN_ENABLED = True
    restaurant.api_key = "test-key-upsert"
    restaurant.save(update_fields=["api_key"])

    from apps.telemetry.collector import collect_catalog
    from apps.telemetry.models import RestaurantCatalogSnapshot

    for _ in range(3):
        api_client.post(
            "/api/v1/telemetry/catalog/",
            collect_catalog(restaurant=restaurant),
            format="json",
            HTTP_X_RESTAURANT_KEY="test-key-upsert",
        )
    assert RestaurantCatalogSnapshot.objects.count() == 1


def test_cloud_catalog_push_unknown_key(api_client, settings, restaurant):
    settings.SUPERADMIN_ENABLED = True
    resp = api_client.post(
        "/api/v1/telemetry/catalog/", {"totals": {}}, format="json",
        HTTP_X_RESTAURANT_KEY="not-in-db",
    )
    assert resp.status_code == 401


def test_cloud_catalog_push_404_in_restaurant_mode(api_client, restaurant):
    from importlib import reload

    from django.urls import clear_url_caches

    restaurant.api_key = "k-resto"
    restaurant.save(update_fields=["api_key"])
    with override_settings(SUPERADMIN_ENABLED=False):
        from config import urls as cfg_urls
        clear_url_caches()
        reload(cfg_urls)
        try:
            resp = api_client.post(
                "/api/v1/telemetry/catalog/", {}, format="json",
                HTTP_X_RESTAURANT_KEY="k-resto",
            )
            assert resp.status_code == 404
        finally:
            clear_url_caches()
            reload(cfg_urls)
