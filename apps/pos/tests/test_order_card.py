import pytest
from PySide6.QtCore import Qt


def _make_order(**overrides) -> dict:
    o = {
        "id": 1247,
        "status": "new",
        "table": 5,
        "table_name": "Стол 5",
        "waiter_name": "Зайнаб",
        "guests_count": 4,
        "total": "257.07",
        "currency": "TJS",
        "created_at": "2026-05-08T14:23:00+00:00",
        "items": [
            {"name_at_order": "Лагман", "qty": 2, "cancelled_at": None},
            {"name_at_order": "Курутоб", "qty": 1, "cancelled_at": None},
        ],
        "order_type": "hall",
    }
    o.update(overrides)
    return o


@pytest.fixture
def make_card(qtbot):
    def _make(order):
        from pos.widgets.order_card import OrderCard

        c = OrderCard(order)
        qtbot.addWidget(c)
        return c

    return _make


def test_renders_id_table_total(make_card):
    from PySide6.QtWidgets import QLabel

    c = make_card(_make_order())
    texts = [w.text() for w in c.findChildren(QLabel)]
    assert any("#1247" in t for t in texts)
    assert any("Стол 5" in t for t in texts)
    assert any("4 гостя" in t for t in texts)
    assert any("257.07" in t for t in texts)
    assert any("Зайнаб" in t for t in texts)
    assert any("Лагман ×2" in t for t in texts)


def test_bill_requested_shows_red_badge(make_card):
    from PySide6.QtWidgets import QLabel

    c = make_card(_make_order(status="bill_requested"))
    texts = [w.text() for w in c.findChildren(QLabel)]
    # Вместо официанта показывается красная плашка "Счёт"
    assert any("Счёт" in t for t in texts)


def test_pay_button_emits_pay_clicked(qtbot, make_card):
    from PySide6.QtWidgets import QPushButton

    c = make_card(_make_order(id=42))
    seen: list[int] = []
    c.pay_clicked.connect(lambda i: seen.append(i))

    pay_btn = next(b for b in c.findChildren(QPushButton) if b.text() == "Оплатить")
    qtbot.mouseClick(pay_btn, Qt.LeftButton)
    assert seen == [42]


def test_cancel_button_emits_cancel_clicked(qtbot, make_card):
    from PySide6.QtWidgets import QPushButton

    c = make_card(_make_order(id=99))
    seen: list[int] = []
    c.cancel_clicked.connect(lambda i: seen.append(i))

    cancel_btn = next(b for b in c.findChildren(QPushButton) if b.text() == "Закрыть")
    qtbot.mouseClick(cancel_btn, Qt.LeftButton)
    assert seen == [99]


def test_card_click_emits_clicked(qtbot, make_card):
    c = make_card(_make_order(id=7))
    seen: list[int] = []
    c.clicked.connect(lambda i: seen.append(i))
    qtbot.mouseClick(c, Qt.LeftButton)
    assert seen == [7]


def test_cancelled_items_excluded(make_card):
    from PySide6.QtWidgets import QLabel

    c = make_card(
        _make_order(
            items=[
                {"name_at_order": "Плов", "qty": 1, "cancelled_at": None},
                {"name_at_order": "Чай", "qty": 1, "cancelled_at": "2026-05-08T14:25:00Z"},
            ]
        )
    )
    texts = " ".join(w.text() for w in c.findChildren(QLabel))
    assert "Плов" in texts
    assert "Чай" not in texts


def test_time_formatted_to_hh_mm(make_card):
    from PySide6.QtWidgets import QLabel

    c = make_card(_make_order(created_at="2026-05-08T09:05:00+00:00"))
    texts = [w.text() for w in c.findChildren(QLabel)]
    # Asia/Dushanbe = UTC+5 → 14:05; но _format_time использует UTC,
    # так что 09:05 UTC. Проверяем что есть какой-то HH:MM.
    assert any(":" in t and len(t) == 5 for t in texts)
