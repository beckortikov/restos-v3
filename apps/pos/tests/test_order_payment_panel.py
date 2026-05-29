"""Smoke-тесты для OrderPaymentPanel — restos-style inline-оплата в drawer."""
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QPushButton


@pytest.fixture
def order():
    return {
        "id": 34,
        "order_type": "hall",
        "status": "bill_requested",
        "guests_count": 2,
        "waiter_name": "Иван",
        "subtotal": "53.00",
        "discount_amount": "0.00",
        "service_charge_amount": "5.30",
        "service_charge_pct": "10.00",
        "total": "58.30",
        "currency": "TJS",
        "items": [
            {"name_at_order": "Плов", "qty": 1, "subtotal": "45.00",
             "cancelled_at": None},
            {"name_at_order": "Чай", "qty": 1, "subtotal": "8.00",
             "cancelled_at": None},
        ],
    }


@pytest.fixture
def table():
    return {"id": 3, "name": "Стол 3", "number": 3}


@pytest.fixture
def panel(qtbot, order, table):
    from pos.widgets.order_payment_panel import OrderPaymentPanel

    p = OrderPaymentPanel(order=order, table=table, client=MagicMock())
    qtbot.addWidget(p)
    p.resize(480, 800)
    p.show()
    qtbot.waitExposed(p)
    return p


def test_renders_two_payment_methods(panel):
    """Должно быть ровно 2 метода: Наличные / Безналичные (без Перевод)."""
    labels = [
        b.text().strip()
        for b in panel.findChildren(QPushButton)
    ]
    assert any("Наличные" in t for t in labels)
    assert any("Безналичные" in t for t in labels)
    assert not any("Перевод" in t for t in labels)


def test_cta_disabled_until_method_selected(panel):
    """До клика на Наличные/Безналичные — CTA disabled."""
    assert not panel._cta_btn.isEnabled()


def test_clicking_cash_enables_cta_and_sets_method(qtbot, panel):
    cash_btn = panel._method_buttons["cash"]
    cash_btn.click()  # Qt.LeftButton
    assert panel._payment_method == "cash"
    assert panel._cta_btn.isEnabled()


def test_clicking_cashless_sets_card_method(qtbot, panel):
    """«Безналичные» в UI → backend получит payment_method='card'."""
    card_btn = panel._method_buttons["card"]
    card_btn.click()
    assert panel._payment_method == "card"


def test_cta_label_contains_total(panel):
    assert "58.30" in panel._cta_btn.text()
    assert "TJS" in panel._cta_btn.text()


def test_pre_bill_button_emits_signal(qtbot, panel):
    pre_btn = next(
        b for b in panel.findChildren(QPushButton) if "Пре-чек" in b.text()
    )
    seen: list[int] = []
    panel.pre_bill_requested.connect(seen.append)
    pre_btn.click()
    assert seen == [34]


def test_more_menu_has_three_actions(panel):
    """Меню «Дополнительно» содержит Скидка / Разделить счёт / Перенести."""
    more_btn = next(
        b for b in panel.findChildren(QPushButton) if "Дополнительно" in b.text()
    )
    actions = [a.text() for a in more_btn.menu().actions()]
    assert any("Скидка" in a for a in actions)
    assert any("Разделить" in a for a in actions)
    assert any("Перенести" in a for a in actions)


def test_cancel_link_emits_after_confirm(qtbot, panel, monkeypatch):
    """«Отменить заказ» → confirm → cancel_requested(order_id)."""
    from PySide6.QtWidgets import QMessageBox

    # Авто-Yes confirm.
    def _auto_yes(self):
        yes_btn = self.buttons()[0]  # first added is "Отменить заказ"
        self.setProperty("_auto_clicked", yes_btn)
        return None
    # Простой monkeypatch: подменим exec на возврат YES и clickedButton.
    seen: list[int] = []
    panel.cancel_requested.connect(seen.append)

    cancel_link = next(
        b for b in panel.findChildren(QPushButton) if "Отменить заказ" in b.text()
    )

    # Заменяем QMessageBox.exec чтобы автоматически кликать «Отменить заказ».
    orig_exec = QMessageBox.exec
    def _fake_exec(self):
        # clickedButton — первый добавленный (yes).
        self._fake_clicked = self.buttons()[0] if self.buttons() else None
        return 0
    monkeypatch.setattr(QMessageBox, "exec", _fake_exec)
    monkeypatch.setattr(
        QMessageBox, "clickedButton",
        lambda self: getattr(self, "_fake_clicked", None),
    )

    cancel_link.click()
    assert seen == [34]


def test_update_order_rerenders_total(qtbot, panel):
    """update_order(...) обновляет CTA-сумму."""
    new_order = dict(panel._order)
    new_order["total"] = "100.00"
    panel.update_order(new_order)
    assert "100.00" in panel._cta_btn.text()
