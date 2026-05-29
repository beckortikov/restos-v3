"""Кастомизация чека: receipt_header_extra, receipt_footer, auto_open_cash_drawer."""
import pytest

pytestmark = pytest.mark.django_db


def _pin(api_client, cashier):
    return api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()["data"]["session_token"]


def test_default_receipt_footer(restaurant):
    assert restaurant.receipt_footer == "Спасибо за визит!"


def test_default_header_extra_empty(restaurant):
    assert restaurant.receipt_header_extra == ""


def test_default_auto_open_cash_drawer_false(restaurant):
    assert restaurant.auto_open_cash_drawer is False


def test_patch_header_extra(api_client, restaurant, cashier):
    pin = _pin(api_client, cashier)
    resp = api_client.patch(
        "/api/v1/restaurant/",
        {"receipt_header_extra": "ИНН 123456789\nЛицензия №42"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200
    restaurant.refresh_from_db()
    assert "ИНН" in restaurant.receipt_header_extra


def test_patch_footer(api_client, restaurant, cashier):
    pin = _pin(api_client, cashier)
    resp = api_client.patch(
        "/api/v1/restaurant/",
        {"receipt_footer": "Wi-Fi: GUEST / 12345"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200
    restaurant.refresh_from_db()
    assert "Wi-Fi" in restaurant.receipt_footer


def test_patch_auto_open_cash_drawer(api_client, restaurant, cashier):
    pin = _pin(api_client, cashier)
    resp = api_client.patch(
        "/api/v1/restaurant/",
        {"auto_open_cash_drawer": True},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200
    restaurant.refresh_from_db()
    assert restaurant.auto_open_cash_drawer is True


def test_receipt_template_uses_header_extra():
    from apps.printing.templates.receipt import render_text_preview

    payload = {
        "restaurant": {
            "name": "Кафе",
            "currency": "TJS",
            "receipt_header_extra": "ИНН 123\nЛицензия №42",
            "receipt_footer": "Спасибо!",
        },
        "order": {
            "id": 1, "table": "1", "guests": 1,
            "waiter": "X", "cashier": "Y",
            "closed_at": "2026-05-09T12:00:00",
            "payment_method": "cash",
            "subtotal": "10", "service_charge_amount": "0",
            "discount_amount": "0", "tip_amount": "0", "total": "10",
        },
        "items": [{"name": "Чай", "qty": 1, "price": "10", "subtotal": "10"}],
    }
    text = render_text_preview(payload, width=48)
    assert "ИНН 123" in text
    assert "Лицензия №42" in text


def test_receipt_template_custom_footer():
    from apps.printing.templates.receipt import render_text_preview

    payload = {
        "restaurant": {
            "name": "Кафе",
            "currency": "TJS",
            "receipt_footer": "Wi-Fi: GUEST",
        },
        "order": {
            "id": 1, "table": "1", "guests": 1,
            "waiter": "X", "cashier": "Y",
            "closed_at": "2026-05-09T12:00:00",
            "payment_method": "cash",
            "subtotal": "10", "service_charge_amount": "0",
            "discount_amount": "0", "tip_amount": "0", "total": "10",
        },
        "items": [{"name": "Чай", "qty": 1, "price": "10", "subtotal": "10"}],
    }
    text = render_text_preview(payload, width=48)
    assert "Wi-Fi: GUEST" in text
    # Дефолтное «Спасибо за визит» не должно быть (override)
    assert "Спасибо за визит" not in text


def test_receipt_template_default_footer_when_not_set():
    from apps.printing.templates.receipt import render_text_preview

    payload = {
        "restaurant": {"name": "Кафе", "currency": "TJS"},  # no receipt_footer
        "order": {
            "id": 1, "table": "1", "guests": 1,
            "waiter": "X", "cashier": "Y",
            "closed_at": "2026-05-09T12:00:00",
            "payment_method": "cash",
            "subtotal": "10", "service_charge_amount": "0",
            "discount_amount": "0", "tip_amount": "0", "total": "10",
        },
        "items": [{"name": "Чай", "qty": 1, "price": "10", "subtotal": "10"}],
    }
    text = render_text_preview(payload, width=48)
    # Backwards compat: дефолт «Спасибо за визит!»
    assert "Спасибо за визит!" in text
