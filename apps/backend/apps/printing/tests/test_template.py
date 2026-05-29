import pytest

pytestmark = pytest.mark.django_db


def test_text_preview_contains_required_fragments(closed_order):
    from apps.printing.services import build_receipt_payload
    from apps.printing.templates.receipt import render_text_preview

    order, _ = closed_order
    order.restaurant.name = "Demo Cafe"
    order.restaurant.address = "ул. Рудаки, 1"
    order.restaurant.phone = "+992 90 000 00 00"
    order.restaurant.save()

    payload = build_receipt_payload(order)
    payload["order"]["closed_at"] = "2026-05-08T10:30:00+00:00"

    text = render_text_preview(payload)

    expected_fragments = [
        "Demo Cafe",
        "ул. Рудаки, 1",
        "тел. +992 90 000 00 00",
        f"Чек № {order.id}",
        "15:30",  # Asia/Dushanbe = UTC+5
        "Стол: Стол 1",
        "Гостей: 2",
        "Официант: Карим Официант",
        "Кассир:   Анна Кассир",
        "Плов",
        "2 x 45.00 = 90.00",
        "Чай",
        "1 x 8.00 = 8.00",
        "ИТОГО: 98.00 TJS",
        "Оплата: Наличные",
        "Спасибо за визит!",
    ]
    for frag in expected_fragments:
        assert frag in text, f"в чеке отсутствует: {frag!r}\n---\n{text}"

    # Все строки чека ширины 32 символа (кроме trailing-пустой)
    for line in text.rstrip("\n").split("\n"):
        assert len(line) <= 32, f"строка длиннее 32 символов: {line!r}"


def test_render_escpos_uses_dummy(closed_order):
    pytest.importorskip("escpos.printer")

    from escpos.printer import Dummy

    from apps.printing.services import build_receipt_payload
    from apps.printing.templates.receipt import render_escpos

    order, _ = closed_order
    payload = build_receipt_payload(order)
    payload["order"]["closed_at"] = "2026-05-08T10:30:00+00:00"

    p = Dummy()
    render_escpos(p, payload)
    out = p.output

    assert isinstance(out, (bytes, bytearray))
    assert len(out) > 0
    assert b"\x1b" in out  # ESC-команды присутствуют
