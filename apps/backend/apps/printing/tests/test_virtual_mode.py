"""Virtual printer mode (Restaurant.printer_virtual_mode) + preview endpoint."""
from pathlib import Path

import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def tcp_printer(restaurant):
    """Не-VIRTUAL принтер (TCP), чтобы проверить, что override-mode его виртуализирует."""
    from apps.printing.models import Printer, PrinterKind
    return Printer.objects.create(
        restaurant=restaurant, name="TCP-принтер",
        kind=PrinterKind.TCP, address="192.168.1.50:9100",
        is_active=True, is_default=True,
    )


def test_restaurant_virtual_mode_forces_virtual(restaurant, tcp_printer, tmp_path, settings):
    """Если restaurant.printer_virtual_mode=True — TCP-принтер тоже пишет в файл."""
    from apps.printing.escpos_sender import send_to_printer
    from apps.printing.models import PrintJob, PrintJobKind

    settings.PRINTER_OUTPUT_DIR = str(tmp_path)
    restaurant.printer_virtual_mode = True
    restaurant.save(update_fields=["printer_virtual_mode"])

    job = PrintJob.objects.create(
        restaurant=restaurant, printer=tcp_printer,
        kind=PrintJobKind.GUEST_RECEIPT,
        payload={
            "restaurant": {"name": "Test", "address": "", "phone": ""},
            "order": {
                "id": 1, "table": "", "guests": 1, "waiter": "", "comment": "",
                "total": "45.00", "currency": "TJS",
            },
            "items": [{"name": "Плов", "qty": 1, "note": "", "price": "45.00", "subtotal": "45.00"}],
        },
    )
    send_to_printer(job)

    f = tmp_path / f"{job.id}.txt"
    assert f.exists(), "Должен был писать в файл, а не на TCP"
    assert "Плов" in f.read_text(encoding="utf-8")


def test_restaurant_virtual_mode_off_uses_real_printer(
    restaurant, tcp_printer, tmp_path, settings,
):
    """Если flag=False и принтер TCP — пытается реально подключиться (и упадёт)."""
    from apps.printing.escpos_sender import send_to_printer
    from apps.printing.models import PrintJob, PrintJobKind

    settings.PRINTER_OUTPUT_DIR = str(tmp_path)
    assert restaurant.printer_virtual_mode is False

    job = PrintJob.objects.create(
        restaurant=restaurant, printer=tcp_printer,
        kind=PrintJobKind.GUEST_RECEIPT,
        payload={
            "restaurant": {"name": "Test", "address": "", "phone": ""},
            "order": {"id": 2, "table": "", "guests": 1, "waiter": "", "comment": ""},
            "items": [],
            "total": "0.00", "currency": "TJS",
        },
    )
    # Ожидаем ошибку подключения (TCP несуществующий)
    with pytest.raises(Exception):
        send_to_printer(job)
    # И файл создан НЕ должен быть
    assert not (tmp_path / f"{job.id}.txt").exists()


# ─── Preview endpoint ───────────────────────────────────────────────────────


def test_preview_endpoint_from_disk(
    api_client, cashier, restaurant, tcp_printer, tmp_path, settings,
):
    """Если на диске есть файл — preview отдаёт его."""
    from apps.printing.models import PrintJob, PrintJobKind

    settings.PRINTER_OUTPUT_DIR = str(tmp_path)
    job = PrintJob.objects.create(
        restaurant=restaurant, printer=tcp_printer,
        kind=PrintJobKind.GUEST_RECEIPT,
        payload={"order": {"id": 1}, "items": [], "total": "0", "currency": "TJS"},
    )
    (tmp_path / f"{job.id}.txt").write_text("=== FAKE PREVIEW ===\nПлов  45.00\n", encoding="utf-8")

    api_client.force_authenticate(user=cashier)
    resp = api_client.get(f"/api/v1/printing/jobs/{job.id}/preview/")
    assert resp.status_code == 200, resp.content
    body = resp.json()["data"]
    assert "FAKE PREVIEW" in body["text"]
    assert body["job_id"] == job.id


def test_preview_endpoint_renders_on_fly(
    api_client, cashier, restaurant, tcp_printer, tmp_path, settings,
):
    """Если файла нет — preview рендерит шаблон."""
    from apps.printing.models import PrintJob, PrintJobKind

    settings.PRINTER_OUTPUT_DIR = str(tmp_path / "empty")  # папка пустая
    job = PrintJob.objects.create(
        restaurant=restaurant, printer=tcp_printer,
        kind=PrintJobKind.GUEST_RECEIPT,
        payload={
            "restaurant": {"name": "Test resto", "address": "", "phone": ""},
            "order": {
                "id": 42, "table": "Стол 5", "guests": 2, "waiter": "Иван", "comment": "",
                "total": "90.00", "currency": "TJS",
            },
            "items": [{"name": "Плов", "qty": 2, "note": "", "price": "45.00", "subtotal": "90.00"}],
        },
    )

    api_client.force_authenticate(user=cashier)
    resp = api_client.get(f"/api/v1/printing/jobs/{job.id}/preview/")
    assert resp.status_code == 200
    text = resp.json()["data"]["text"]
    assert "Плов" in text
    assert "90.00" in text


def test_jobs_list_endpoint(api_client, cashier, restaurant, tcp_printer):
    """GET /printing/jobs/ — список последних 100 jobs."""
    from apps.printing.models import PrintJob, PrintJobKind

    for i in range(5):
        PrintJob.objects.create(
            restaurant=restaurant, printer=tcp_printer,
            kind=PrintJobKind.GUEST_RECEIPT,
            payload={"items": []},
        )

    api_client.force_authenticate(user=cashier)
    resp = api_client.get("/api/v1/printing/jobs/")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert len(body) == 5
    # Order desc by id
    ids = [j["id"] for j in body]
    assert ids == sorted(ids, reverse=True)
