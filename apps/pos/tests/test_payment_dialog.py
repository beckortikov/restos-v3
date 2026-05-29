"""PaymentDialog: рендер, выбор способа оплаты, успешный close → emit, ошибка → MessageBox."""
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt


def _order(**kw) -> dict:
    base = {
        "id": 1247,
        "guests_count": 4,
        "total": "116.00",
        "currency": "TJS",
        "items": [
            {"name_at_order": "Цезарь с курицей", "qty": 2, "subtotal": "90.00",
             "cancelled_at": None},
            {"name_at_order": "Лагман", "qty": 1, "subtotal": "21.00",
             "cancelled_at": None},
        ],
    }
    base.update(kw)
    return base


@pytest.fixture
def dialog(qtbot):
    from pos.screens.payment_dialog import PaymentDialog

    client = MagicMock()
    d = PaymentDialog(
        order=_order(),
        table={"id": 5, "name": "Стол 5", "number": 5},
        client=client,
    )
    qtbot.addWidget(d)
    d.show()
    yield d, client
    # cleanup any worker thread
    t = d._thread
    if t is not None and t.isRunning():
        t.quit()
        t.wait(2000)


def test_renders_order_summary(dialog):
    d, _ = dialog
    from PySide6.QtWidgets import QLabel

    texts = [w.text() for w in d.findChildren(QLabel)]
    assert any("№1247" in t for t in texts)
    assert any("Стол 5" in t for t in texts)
    assert any("4 гостя" in t for t in texts)
    assert any("Цезарь с курицей" in t for t in texts)
    assert any("116.00 TJS" in t for t in texts)


def test_pay_disabled_until_method_selected(dialog):
    d, _ = dialog
    assert not d._pay_btn.isEnabled()


def test_method_selection_enables_pay(qtbot, dialog):
    d, _ = dialog
    qtbot.mouseClick(d._method_buttons["cash"], Qt.LeftButton)
    assert d._payment_method == "cash"
    assert d._method_buttons["cash"].isChecked()
    assert d._pay_btn.isEnabled()


def test_method_switch(qtbot, dialog):
    d, _ = dialog
    qtbot.mouseClick(d._method_buttons["cash"], Qt.LeftButton)
    qtbot.mouseClick(d._method_buttons["card"], Qt.LeftButton)
    assert d._payment_method == "card"
    assert d._method_buttons["card"].isChecked()
    assert not d._method_buttons["cash"].isChecked()


def test_pay_calls_close_order_with_idempotency(qtbot, dialog):
    d, client = dialog
    client.post.return_value = {
        "order": {"id": 1247, "status": "done"},
        "print_job": {"id": 7711, "status": "pending"},
    }
    qtbot.mouseClick(d._method_buttons["cash"], Qt.LeftButton)

    paid_events: list[tuple[dict, dict]] = []
    d.order_paid.connect(lambda o, p: paid_events.append((o, p)))

    qtbot.mouseClick(d._pay_btn, Qt.LeftButton)
    qtbot.waitUntil(lambda: bool(paid_events), timeout=2000)

    args, kwargs = client.post.call_args
    assert args[0] == "/orders/1247/close/"
    assert kwargs["json"] == {"payment_method": "cash"}
    assert "Idempotency-Key" in kwargs["extra_headers"]

    assert paid_events[0][0]["status"] == "done"
    assert paid_events[0][1]["id"] == 7711


def test_idempotency_key_constant_per_dialog(qtbot, dialog):
    """Один и тот же ключ переиспользуется при ретрае (двойной клик не дублирует close)."""
    d, _ = dialog
    qtbot.mouseClick(d._method_buttons["cash"], Qt.LeftButton)
    initial_key = d._idem_key
    # повторный select_method не меняет ключ
    qtbot.mouseClick(d._method_buttons["card"], Qt.LeftButton)
    assert d._idem_key == initial_key


def test_pay_error_shows_message(qtbot, dialog, monkeypatch):
    from pos.http_client import ApiError

    d, client = dialog
    client.post.side_effect = ApiError("ORDER_ALREADY_CLOSED", "Уже закрыт", 409)

    msgs: list = []
    def fake_warning(parent, title, text, *a, **kw):
        msgs.append((title, text))
        return 0

    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "warning", fake_warning)

    qtbot.mouseClick(d._method_buttons["cash"], Qt.LeftButton)
    qtbot.mouseClick(d._pay_btn, Qt.LeftButton)
    qtbot.waitUntil(lambda: bool(msgs), timeout=2000)

    assert "Ошибка" in msgs[0][0]
    assert "ORDER_ALREADY_CLOSED" in msgs[0][1]
    # button re-enabled
    assert d._pay_btn.isEnabled()
