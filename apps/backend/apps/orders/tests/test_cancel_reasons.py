"""CancelReason CRUD + auto-seed для нового ресторана."""
import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def cashier_token(api_client, cashier):
    resp = api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()
    return resp["data"]["session_token"]


def test_new_restaurant_auto_seeds_reasons(db):
    """post_save сигнал на Restaurant сидит дефолтные причины."""
    from apps.orders.defaults import DEFAULT_CANCEL_REASONS
    from apps.orders.models import CancelReason
    from apps.users.models import Restaurant

    resto = Restaurant.objects.create(name="Auto-seed test", currency="TJS")
    for kind, labels in DEFAULT_CANCEL_REASONS.items():
        seeded = CancelReason.objects.filter(
            restaurant=resto, kind=kind
        ).values_list("label", flat=True)
        assert set(seeded) == set(labels)


def test_list_reasons_filtered_by_kind(api_client, cashier, cashier_token, restaurant):
    # Сидеры из миграции 0006 уже создали дефолтные причины.
    resp = api_client.get(
        "/api/v1/cancel_reasons/?kind=item",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] >= 1
    assert all(r["kind"] == "item" for r in body["data"])


def test_create_reason(api_client, cashier, cashier_token):
    resp = api_client.post(
        "/api/v1/cancel_reasons/",
        {"kind": "item", "label": "Кастомная причина", "sort_order": 99},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["label"] == "Кастомная причина"


def test_create_invalid_kind(api_client, cashier, cashier_token):
    resp = api_client.post(
        "/api/v1/cancel_reasons/",
        {"kind": "invalid", "label": "x"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 400


def test_update_reason(api_client, cashier, cashier_token, restaurant):
    from apps.orders.models import CancelReason

    r = CancelReason.objects.filter(
        restaurant=restaurant, kind="item"
    ).first()
    assert r is not None
    resp = api_client.patch(
        f"/api/v1/cancel_reasons/{r.id}/",
        {"label": "Изменено"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 200
    r.refresh_from_db()
    assert r.label == "Изменено"


def test_destroy_reason(api_client, cashier, cashier_token, restaurant):
    from apps.orders.models import CancelReason

    r = CancelReason.objects.filter(
        restaurant=restaurant, kind="item"
    ).first()
    rid = r.id
    resp = api_client.delete(
        f"/api/v1/cancel_reasons/{rid}/",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 204
    assert not CancelReason.objects.filter(id=rid).exists()


def test_waiter_can_read_only(api_client, cashier, waiter, restaurant):
    """Официант видит причины (для waiter PWA), но не может их изменять."""
    login = api_client.post(
        "/api/v1/auth/login/",
        {"username": "waiter1", "password": "waiter-pass"},
        format="json",
    ).json()
    access = login["data"]["access"]

    # GET — ок
    resp = api_client.get(
        "/api/v1/cancel_reasons/?kind=item",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert resp.status_code == 200

    # POST — 403
    resp = api_client.post(
        "/api/v1/cancel_reasons/",
        {"kind": "item", "label": "x"},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert resp.status_code == 403


def test_cross_restaurant_isolation(api_client, cashier, cashier_token):
    """Чужие причины не видны и не редактируются."""
    from apps.orders.models import CancelReason
    from apps.users.models import Restaurant

    other = Restaurant.objects.create(name="Other resto", currency="USD")
    other_reason = CancelReason.objects.create(
        restaurant=other, kind="item", label="Чужой", sort_order=0
    )

    resp = api_client.get(
        "/api/v1/cancel_reasons/",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    ids = {r["id"] for r in resp.json()["data"]}
    assert other_reason.id not in ids

    # Попытка обновить чужую причину → 404 (она не в queryset нашего ресторана)
    resp = api_client.patch(
        f"/api/v1/cancel_reasons/{other_reason.id}/",
        {"label": "хак"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 404
