"""Stop-list: stop_list / restore endpoints + audit log + serializer fields."""
import pytest

pytestmark = pytest.mark.django_db


def _pin(api_client, cashier):
    return api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()["data"]["session_token"]


def test_stop_list_field_default(restaurant, menu_items):
    plov = menu_items["plov"]
    assert plov.is_available is True
    assert plov.stop_reason == ""
    assert plov.stop_until is None


def test_stop_list_endpoint_with_reason_and_until(
    api_client, restaurant, cashier, menu_items,
):
    plov = menu_items["plov"]
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        f"/api/v1/menu/items/{plov.id}/stop_list/",
        {"reason": "Закончилась говядина", "until": "2026-05-15"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200, resp.content
    data = resp.json()["data"]
    assert data["is_available"] is False
    assert data["stop_reason"] == "Закончилась говядина"
    assert data["stop_until"] == "2026-05-15"


def test_stop_list_without_until(
    api_client, restaurant, cashier, menu_items,
):
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        f"/api/v1/menu/items/{menu_items['plov'].id}/stop_list/",
        {"reason": "X"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["stop_until"] is None


def test_stop_list_invalid_until_format(
    api_client, restaurant, cashier, menu_items,
):
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        f"/api/v1/menu/items/{menu_items['plov'].id}/stop_list/",
        {"reason": "X", "until": "not-a-date"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code in (400, 422)


def test_restore_endpoint_clears_stop_fields(
    api_client, restaurant, cashier, menu_items,
):
    plov = menu_items["plov"]
    pin = _pin(api_client, cashier)
    api_client.post(
        f"/api/v1/menu/items/{plov.id}/stop_list/",
        {"reason": "X", "until": "2026-05-15"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    resp = api_client.post(
        f"/api/v1/menu/items/{plov.id}/restore/",
        {}, format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["is_available"] is True
    assert data["stop_reason"] == ""
    assert data["stop_until"] is None


def test_toggle_available_clears_stop_fields_when_returning_to_sale(
    api_client, restaurant, cashier, menu_items,
):
    """Старый toggle_available тоже должен очищать stop-поля при возврате в продажу."""
    pin = _pin(api_client, cashier)
    # Сначала в стоп через stop_list
    api_client.post(
        f"/api/v1/menu/items/{menu_items['plov'].id}/stop_list/",
        {"reason": "Y", "until": "2026-06-01"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    # Toggle обратно в продажу
    resp = api_client.post(
        f"/api/v1/menu/items/{menu_items['plov'].id}/toggle_available/",
        {}, format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    data = resp.json()["data"]
    assert data["is_available"] is True
    assert data["stop_reason"] == ""
    assert data["stop_until"] is None


def test_stop_list_writes_audit_log(
    api_client, restaurant, cashier, menu_items,
):
    from apps.audit.models import AuditAction, AuditEntry

    pin = _pin(api_client, cashier)
    api_client.post(
        f"/api/v1/menu/items/{menu_items['plov'].id}/stop_list/",
        {"reason": "Z"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    e = AuditEntry.objects.filter(
        action=AuditAction.SETTINGS_UPDATE,
        target_id=menu_items["plov"].id,
    ).first()
    assert e is not None
    assert e.payload.get("action") == "stop_list"
    assert e.payload.get("reason") == "Z"


def test_restore_writes_audit_log(
    api_client, restaurant, cashier, menu_items,
):
    from apps.audit.models import AuditAction, AuditEntry

    pin = _pin(api_client, cashier)
    api_client.post(
        f"/api/v1/menu/items/{menu_items['plov'].id}/stop_list/",
        {"reason": "Y"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    api_client.post(
        f"/api/v1/menu/items/{menu_items['plov'].id}/restore/",
        {}, format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    es = AuditEntry.objects.filter(
        action=AuditAction.SETTINGS_UPDATE,
        target_id=menu_items["plov"].id,
    ).order_by("-created_at")
    actions = [e.payload.get("action") for e in es]
    assert "restore" in actions
    assert "stop_list" in actions


def test_serializer_includes_stop_fields(
    api_client, restaurant, cashier, menu_items,
):
    """В list response каждое блюдо включает stop_reason и stop_until."""
    pin = _pin(api_client, cashier)
    resp = api_client.get(
        "/api/v1/menu/items/", HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    data = resp.json()["data"]
    assert all("stop_reason" in d for d in data)
    assert all("stop_until" in d for d in data)
