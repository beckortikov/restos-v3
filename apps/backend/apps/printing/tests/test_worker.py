import threading
from datetime import timedelta
from pathlib import Path

import pytest

pytestmark = pytest.mark.django_db


def test_virtual_printer_writes_file(closed_order, tmp_path, settings):
    from apps.printing.models import PrintJobStatus
    from apps.printing.services import process_one_job

    settings.PRINTER_VIRTUAL = True
    settings.PRINTER_OUTPUT_DIR = str(tmp_path)

    _, job = closed_order
    assert job.status == PrintJobStatus.PENDING

    processed = process_one_job()
    assert processed

    job.refresh_from_db()
    assert job.status == PrintJobStatus.DONE
    assert job.finished_at is not None
    assert job.error == ""

    out = Path(tmp_path) / f"{job.id}.txt"
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "ИТОГО" in content
    assert "98.00" in content
    assert "Плов" in content


def test_worker_backoff_progression(closed_order, monkeypatch, settings):
    from apps.printing import services as svc
    from apps.printing.models import PrintJob, PrintJobStatus

    settings.PRINTER_VIRTUAL = False

    def boom(_job):
        raise ConnectionError("printer offline")

    monkeypatch.setattr(svc, "send_to_printer", boom)

    _, job = closed_order

    # Эмулируем 5 неудачных попыток с прокруткой scheduled_at
    for attempt in range(1, PrintJob.MAX_RETRIES + 1):
        # сбрасываем scheduled_at в прошлое, чтобы tick подхватил job
        PrintJob.objects.filter(id=job.id).update(
            scheduled_at=svc.timezone.now() - timedelta(seconds=1)
        )
        processed = svc.process_one_job()
        assert processed, f"attempt {attempt}: ничего не обработано"
        job.refresh_from_db()
        assert job.retries == attempt
        assert "ConnectionError" in job.error

        if attempt < PrintJob.MAX_RETRIES:
            assert job.status == PrintJobStatus.FAILED
            expected_delay = PrintJob.BACKOFF_SECONDS[attempt - 1]
            actual_delay = (job.scheduled_at - job.started_at).total_seconds()
            assert abs(actual_delay - expected_delay) < 5
        else:
            assert job.status == PrintJobStatus.DEAD
            assert job.finished_at is not None


@pytest.mark.django_db(transaction=True)
def test_worker_skip_locked_when_only_one_job():
    """Когда есть ровно одна job — один воркер берёт её, второй ничего не получает."""
    import threading

    from django.db import connections

    from apps.printing import services as svc
    from apps.printing.models import PrintJob, PrintJobKind, Printer, PrinterKind
    from apps.users.models import Restaurant

    r = Restaurant.objects.create(name="X", currency="TJS")
    p = Printer.objects.create(
        restaurant=r, name="Касса", kind=PrinterKind.VIRTUAL, is_default=True
    )
    PrintJob.objects.create(
        restaurant=r, printer=p, kind=PrintJobKind.GUEST_RECEIPT,
        payload={"restaurant": {"name": "X", "currency": "TJS",
                                  "address": "", "phone": ""},
                 "order": {"id": 1, "table": "T1", "guests": 1,
                           "waiter": "W", "cashier": "",
                           "closed_at": "", "payment_method": "cash",
                           "total": "0.00"},
                 "items": []},
        scheduled_at=svc.timezone.now(),
    )

    barrier = threading.Barrier(2)
    results: list[bool] = []

    def worker():
        barrier.wait()
        try:
            results.append(svc.process_one_job())
        finally:
            # Явно закрываем thread-local соединения — иначе остаточные locks
            # могут вызвать deadlock при TRUNCATE в следующем transactional-тесте.
            for conn in connections.all():
                conn.close()

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert sorted(results) == [False, True]
