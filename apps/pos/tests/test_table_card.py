import pytest
from PySide6.QtCore import Qt


@pytest.fixture
def make_card(qtbot):
    def _make(table: dict, total_text: str = ""):
        from pos.widgets.table_card import TableCard

        c = TableCard(table, total_text=total_text)
        qtbot.addWidget(c)
        return c

    return _make


def test_free_card_shows_свободен(make_card):
    c = make_card({"id": 1, "name": "Стол 1", "number": 1, "status": "free"})
    labels = [w.text() for w in c.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel)]
    assert "Стол 1" in labels
    assert "Свободен" in labels


def test_occupied_card_shows_guests_and_total(make_card):
    c = make_card(
        {"id": 2, "name": "Стол 2", "number": 2, "status": "occupied", "guests_count": 3},
        total_text="450.00 TJS",
    )
    from PySide6.QtWidgets import QLabel

    texts = [w.text() for w in c.findChildren(QLabel)]
    assert any("3 гостя" in t for t in texts)
    assert any("450.00 TJS" in t for t in texts)


def test_bill_requested_card(make_card):
    c = make_card(
        {"id": 3, "name": "Стол 3", "number": 3, "status": "bill_requested", "guests_count": 1},
        total_text="98.00 TJS",
    )
    from PySide6.QtWidgets import QLabel

    texts = [w.text() for w in c.findChildren(QLabel)]
    assert any("Счёт" in t for t in texts)
    assert any("1 гость" in t for t in texts)


def test_click_on_free_emits_noop(qtbot, make_card):
    c = make_card({"id": 1, "number": 1, "status": "free", "name": "Стол 1"})
    seen: list[tuple[int, str]] = []
    c.clicked.connect(lambda i, a: seen.append((i, a)))
    qtbot.mouseClick(c, Qt.LeftButton)
    assert seen == [(1, "noop")]


def test_click_on_occupied_emits_detail(qtbot, make_card):
    c = make_card({"id": 5, "number": 5, "status": "occupied", "name": "Стол 5"})
    seen: list[tuple[int, str]] = []
    c.clicked.connect(lambda i, a: seen.append((i, a)))
    qtbot.mouseClick(c, Qt.LeftButton)
    assert seen == [(5, "detail")]


def test_click_on_bill_requested_emits_pay(qtbot, make_card):
    c = make_card({"id": 7, "number": 7, "status": "bill_requested", "name": "Стол 7"})
    seen: list[tuple[int, str]] = []
    c.clicked.connect(lambda i, a: seen.append((i, a)))
    qtbot.mouseClick(c, Qt.LeftButton)
    assert seen == [(7, "pay")]


def test_guests_word_grammar(make_card):
    from pos.widgets.table_card import TableCard

    assert TableCard._guests_word(1) == "гость"
    assert TableCard._guests_word(2) == "гостя"
    assert TableCard._guests_word(5) == "гостей"
    assert TableCard._guests_word(11) == "гостей"
    assert TableCard._guests_word(21) == "гость"
    assert TableCard._guests_word(22) == "гостя"
