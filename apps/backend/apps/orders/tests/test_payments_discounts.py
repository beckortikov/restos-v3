"""PaymentProvider + Discount CRUD + auto-seed для нового ресторана."""
import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def cashier_token(api_client, cashier):
    resp = api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()
    return resp["data"]["session_token"]


# -------- Auto-seed --------


def test_new_restaurant_seeds_payment_providers(db):
    from apps.orders.defaults import DEFAULT_PAYMENT_PROVIDERS
    from apps.orders.models import PaymentProvider
    from apps.users.models import Restaurant

    resto = Restaurant.objects.create(name="Pay seed", currency="TJS")
    seeded = set(
        PaymentProvider.objects.filter(restaurant=resto).values_list(
            "kind", flat=True
        )
    )
    expected = {p["kind"] for p in DEFAULT_PAYMENT_PROVIDERS}
    assert seeded == expected


def test_new_restaurant_seeds_discounts(db):
    from apps.orders.defaults import DEFAULT_DISCOUNTS
    from apps.orders.models import Discount
    from apps.users.models import Restaurant

    resto = Restaurant.objects.create(name="Disc seed", currency="TJS")
    seeded = set(
        Discount.objects.filter(restaurant=resto).values_list("name", flat=True)
    )
    expected = {d["name"] for d in DEFAULT_DISCOUNTS}
    assert seeded == expected
    # Сервисный сбор есть, type=service
    assert Discount.objects.filter(restaurant=resto, type="service").count() == 1


# -------- PaymentProvider API --------


def test_list_payment_providers(api_client, cashier, cashier_token):
    resp = api_client.get(
        "/api/v1/payment_providers/",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] >= 4


def test_create_payment_provider(api_client, cashier, cashier_token):
    resp = api_client.post(
        "/api/v1/payment_providers/",
        {
            "kind": "card",
            "name": "Корти Милли",
            "description": "Терминал: Korti Milli",
            "commission_pct": "2.00",
            "is_active": True,
            "sort_order": 4,
        },
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["name"] == "Корти Милли"


def test_create_payment_provider_invalid_kind(api_client, cashier, cashier_token):
    resp = api_client.post(
        "/api/v1/payment_providers/",
        {"kind": "crypto", "name": "Bitcoin", "value": "0"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 400


def test_toggle_payment_provider(api_client, cashier, cashier_token, restaurant):
    from apps.orders.models import PaymentProvider

    pp = PaymentProvider.objects.filter(
        restaurant=restaurant, kind="wallet"
    ).first()
    assert pp is not None
    resp = api_client.patch(
        f"/api/v1/payment_providers/{pp.id}/",
        {"is_active": True},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 200
    pp.refresh_from_db()
    assert pp.is_active is True


def test_destroy_payment_provider(api_client, cashier, cashier_token, restaurant):
    from apps.orders.models import PaymentProvider

    pp = PaymentProvider.objects.filter(
        restaurant=restaurant, kind="wallet"
    ).first()
    pid = pp.id
    resp = api_client.delete(
        f"/api/v1/payment_providers/{pid}/",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 204
    assert not PaymentProvider.objects.filter(id=pid).exists()


def test_payment_providers_cross_tenant_isolation(api_client, cashier, cashier_token):
    from apps.orders.models import PaymentProvider
    from apps.users.models import Restaurant

    other = Restaurant.objects.create(name="Other", currency="USD")
    other_pp = PaymentProvider.objects.filter(restaurant=other).first()
    assert other_pp is not None  # сидер сработал

    resp = api_client.get(
        "/api/v1/payment_providers/",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    ids = {p["id"] for p in resp.json()["data"]}
    assert other_pp.id not in ids


# -------- Discount API --------


def test_list_discounts_includes_service(api_client, cashier, cashier_token):
    resp = api_client.get(
        "/api/v1/discounts/",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 200
    types = {d["type"] for d in resp.json()["data"]}
    assert "discount" in types
    assert "service" in types


def test_filter_discounts_by_type(api_client, cashier, cashier_token):
    resp = api_client.get(
        "/api/v1/discounts/?type=discount",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 200
    assert all(d["type"] == "discount" for d in resp.json()["data"])


def test_create_discount(api_client, cashier, cashier_token):
    resp = api_client.post(
        "/api/v1/discounts/",
        {
            "type": "discount",
            "name": "День рождения",
            "description": "По паспорту",
            "kind": "percent",
            "value": "25.00",
            "is_active": True,
        },
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 201


def test_create_discount_invalid_kind(api_client, cashier, cashier_token):
    resp = api_client.post(
        "/api/v1/discounts/",
        {"type": "discount", "name": "X", "kind": "crazy", "value": "1"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 400


def test_update_service_charge(api_client, cashier, cashier_token, restaurant):
    from apps.orders.models import Discount

    svc = Discount.objects.get(restaurant=restaurant, type="service")
    resp = api_client.patch(
        f"/api/v1/discounts/{svc.id}/",
        {"value": "10.00"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 200
    svc.refresh_from_db()
    from decimal import Decimal
    assert svc.value == Decimal("10.00")


def test_waiter_can_read_only(api_client, cashier, waiter):
    login = api_client.post(
        "/api/v1/auth/login/",
        {"username": "waiter1", "password": "waiter-pass"},
        format="json",
    ).json()
    access = login["data"]["access"]

    resp = api_client.get(
        "/api/v1/payment_providers/",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert resp.status_code == 200

    resp = api_client.post(
        "/api/v1/payment_providers/",
        {"kind": "cash", "name": "x", "value": "0"},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert resp.status_code == 403
