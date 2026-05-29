"""ReceiptStatusDialog: рендер по статусам, banner на failed/dead, retry."""
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt


@pytest.fixture
def make_dialog(qtbot):
    def _make(initial_status: str = "pending"):
        from pos.screens.receipt_status_dialog import ReceiptStatusDialog

        client = MagicMock()
        d = ReceiptStatusDialog(
            print_job={"id": 7711, "status": initial_status, "retries": 0, "error": ""},
            client=client,
            printer_name="Главная касса",
            printer_address="192.168.1.50",
        )
        qtbot.addWidget(d)
        return d, client

    return _make


def test_pending_state(make_dialog):
    d, _ = make_dialog("pending")
    assert "очереди" in d._title.text().lower() or "ожида" in d._title.text().lower()
    assert not d._banner.isVisible() or d._banner.isVisibleTo(d) is False


def test_done_state_shows_check(make_dialog):
    d, _ = make_dialog("done")
    assert "напечатан" in d._title.text().lower()
    assert d._icon.text() == "✓"


def test_failed_state_shows_banner(qtbot, make_dialog):
    d, _ = make_dialog("failed")
    d.show()
    qtbot.waitExposed(d)
    assert d._banner.isVisible()
    assert "Главная касса" in d._banner_text.text()
    assert "192.168.1.50" in d._banner_text.text()


def test_dead_state_shows_message(qtbot, make_dialog):
    d, _ = make_dialog("dead")
    d.show()
    qtbot.waitExposed(d)
    assert "не напечатан" in d._title.text().lower() or "не удалась" in d._subtitle.text().lower()
    assert d._banner.isVisible()


def test_event_updates_state(make_dialog):
    d, _ = make_dialog("pending")
    d.update_from_event({"id": 7711, "status": "done"})
    assert "напечатан" in d._title.text().lower()


def test_event_for_other_job_ignored(make_dialog):
    d, _ = make_dialog("pending")
    initial_title = d._title.text()
    d.update_from_event({"id": 9999, "status": "done"})  # другой job
    assert d._title.text() == initial_title


def test_retry_calls_client(qtbot, make_dialog):
    d, client = make_dialog("failed")
    d.show()
    qtbot.waitExposed(d)

    from PySide6.QtWidgets import QPushButton
    retry_btn = next(
        b for b in d._banner.findChildren(QPushButton) if b.text() == "Повторить"
    )
    qtbot.mouseClick(retry_btn, Qt.LeftButton)
    qtbot.waitUntil(lambda: client.post.called, timeout=2000)

    args, kwargs = client.post.call_args
    assert args[0] == "/printing/jobs/7711/retry/"
    assert "Idempotency-Key" in kwargs["extra_headers"]
