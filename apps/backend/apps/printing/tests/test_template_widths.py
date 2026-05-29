"""ESC/POS template поддерживает paper_size: 58/76/80мм + новые поля
(subtotal/discount/service)."""
import pytest

pytestmark = pytest.mark.django_db


PAYLOAD_BASE = {
    "restaurant": {
        "name": "Demo", "address": "ул. Рудаки 1",
        "phone": "+992 90 000 00 00", "currency": "TJS",
    },
    "order": {
        "id": 1187, "table": "Стол 1", "guests": 2,
        "waiter": "Карим", "cashier": "Анна",
        "closed_at": "2026-05-08T15:30:00+05:00",
        "payment_method": "cash",
        "subtotal": "98.00",
        "service_charge_pct": "12.00",
        "service_charge_amount": "11.76",
        "total": "109.76",
    },
    "items": [
        {"name": "Плов", "qty": 2, "price": "45.00", "subtotal": "90.00"},
        {"name": "Чай", "qty": 1, "price": "8.00", "subtotal": "8.00"},
    ],
}


def test_default_width_32():
    """Без указания paper_size — 32 символа (58мм)."""
    from apps.printing.templates.receipt import render_text_preview

    text = render_text_preview(PAYLOAD_BASE)
    # Каждая строка ≤ 32 символов (но "─" UTF-8 char занимает 1 в str-длине).
    for line in text.splitlines():
        # Линии с "─" — len 32; центрирование/правая граница соблюдены.
        assert len(line) <= 32 + 5  # запас на UTF + emoji
    # Должны быть линии с подытогом и сервисом.
    assert "Подитог: 98.00 TJS" in text
    assert "Обслуживание (12.00%): +11.76 TJS" in text
    assert "ИТОГО: 109.76 TJS" in text


def test_width_for_80mm_is_48():
    from apps.printing.templates.receipt import width_for

    assert width_for("80mm") == 48
    assert width_for("76mm") == 42
    assert width_for("58mm") == 32
    assert width_for(None) == 32  # default


def test_render_uses_printer_paper_size_from_payload():
    """Если в data есть printer_paper_size=80mm — width=48."""
    from apps.printing.templates.receipt import render_text_preview

    payload = {**PAYLOAD_BASE, "printer_paper_size": "80mm"}
    text = render_text_preview(payload)
    # Хотя бы одна линия HR имеет ширину 48.
    hr_lines = [l for l in text.splitlines() if l.strip().startswith("─")]
    assert any(len(l) == 48 for l in hr_lines)


def test_render_explicit_width_overrides():
    from apps.printing.templates.receipt import render_text_preview

    text = render_text_preview(PAYLOAD_BASE, width=42)
    hr_lines = [l for l in text.splitlines() if l.strip().startswith("─")]
    assert any(len(l) == 42 for l in hr_lines)


def test_render_skips_zero_lines():
    """Если subtotal/discount/service_amount == 0 → строка не печатается."""
    from apps.printing.templates.receipt import render_text_preview

    payload = {
        **PAYLOAD_BASE,
        "order": {
            **PAYLOAD_BASE["order"],
            "subtotal": "0.00",
            "service_charge_pct": "0",
            "service_charge_amount": "0.00",
        },
    }
    text = render_text_preview(payload)
    assert "Подитог" not in text
    assert "Обслуживание" not in text


def test_render_with_discount():
    from apps.printing.templates.receipt import render_text_preview

    payload = {
        **PAYLOAD_BASE,
        "order": {
            **PAYLOAD_BASE["order"],
            "discount_amount": "9.80",
            "discount_name": "Сотрудник",
        },
    }
    text = render_text_preview(payload)
    assert "Сотрудник: −9.80 TJS" in text


def test_escpos_sender_passes_paper_size(restaurant, printer, waiter, table, menu_items):
    """Smoke: write через виртуальный принтер 58mm vs 80mm — разная длина строк."""
    from uuid import uuid4

    from apps.orders.services import close_order, create_order
    from apps.printing.escpos_sender import send_to_printer
    from apps.printing.models import Printer, PrinterKind, PrintJob, PrintJobKind
    from apps.printing.services import build_receipt_payload as bp
    from django.conf import settings

    settings.PRINTER_VIRTUAL = True

    # Создадим заказ + закроем
    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1,
        items_data=[{"menu_item_id": menu_items["plov"].id, "qty": 1}],
        comment="", idempotency_key=uuid4(),
    )
    closed, job_default = close_order(
        order_id=order.id, cashier=waiter, payment_method="cash"
    )
    # job_default использует default printer (paper_size=80mm-default)
    send_to_printer(job_default)

    # Создадим вторую партию с принтером 58mm
    p58 = Printer.objects.create(
        restaurant=restaurant, name="Узкий", kind=PrinterKind.VIRTUAL,
        address="narrow", paper_size="58mm", is_active=True,
    )
    job58 = PrintJob.objects.create(
        restaurant=restaurant, printer=p58, order=closed,
        kind=PrintJobKind.GUEST_RECEIPT, payload=bp(closed),
    )
    send_to_printer(job58)

    out_dir = settings.PRINTER_OUTPUT_DIR
    text80 = open(f"{out_dir}/{job_default.id}.txt", encoding="utf-8").read()
    text58 = open(f"{out_dir}/{job58.id}.txt", encoding="utf-8").read()

    # Линии HR разной длины
    hr80 = [l for l in text80.splitlines() if l.strip().startswith("─")]
    hr58 = [l for l in text58.splitlines() if l.strip().startswith("─")]
    assert any(len(l) == 80 for l in hr80) or any(len(l) == 48 for l in hr80)
    assert any(len(l) == 32 for l in hr58)
