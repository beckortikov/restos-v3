"""TableMergeDialog: чекбокс-листинг свободных столов + список активных групп."""
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def client():
    return MagicMock()


@pytest.fixture
def tables():
    return [
        {"id": 1, "name": "Стол 5", "number": 5,
         "zone_name": "Зал", "capacity": 4, "status": "free"},
        {"id": 2, "name": "Стол 6", "number": 6,
         "zone_name": "Зал", "capacity": 4, "status": "free"},
        {"id": 3, "name": "Стол 7", "number": 7,
         "zone_name": "Зал", "capacity": 2, "status": "occupied"},
    ]


@pytest.fixture
def groups():
    return []


@pytest.fixture
def dlg(qtbot, client, tables, groups):
    from pos.screens.table_merge_dialog import TableMergeDialog

    d = TableMergeDialog(
        client=client, tables=tables, groups=groups,
    )
    qtbot.addWidget(d)
    yield d


def test_only_free_tables_listed(dlg):
    """Чекбоксы только для свободных. Стол 7 (occupied) не показывается."""
    assert set(dlg._checkboxes.keys()) == {1, 2}


def test_merge_btn_disabled_until_two_selected(dlg):
    assert not dlg._merge_btn.isEnabled()
    dlg._checkboxes[1].setChecked(True)
    assert not dlg._merge_btn.isEnabled()
    dlg._checkboxes[2].setChecked(True)
    assert dlg._merge_btn.isEnabled()


def test_merge_posts_correct_body(qtbot, dlg, client):
    from PySide6.QtCore import Qt

    dlg._checkboxes[1].setChecked(True)
    dlg._checkboxes[2].setChecked(True)
    dlg._name_input.setText("VIP")

    fired: list[bool] = []
    dlg.groups_changed.connect(lambda: fired.append(True))

    client.post.return_value = {"data": {"id": 99, "tables": [1, 2]}}
    qtbot.mouseClick(dlg._merge_btn, Qt.LeftButton)

    args, kwargs = client.post.call_args
    assert args[0] == "/tables/merge/"
    body = kwargs["json"]
    assert sorted(body["table_ids"]) == [1, 2]
    assert body["name"] == "VIP"
    assert fired == [True]


def test_groups_column_renders_unmerge_btn(qtbot, client, tables):
    from pos.screens.table_merge_dialog import TableMergeDialog
    from PySide6.QtWidgets import QPushButton

    groups = [
        {"id": 7, "name": "", "table_names": ["Стол 5", "Стол 6"], "tables": [1, 2]},
    ]
    d = TableMergeDialog(client=client, tables=tables, groups=groups)
    qtbot.addWidget(d)

    btns = d.findChildren(QPushButton)
    assert any(b.text() == "Разъединить" for b in btns)


def test_unmerge_calls_endpoint(qtbot, client, tables):
    from pos.screens.table_merge_dialog import TableMergeDialog
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton

    groups = [
        {"id": 99, "name": "", "table_names": ["Стол 5", "Стол 6"], "tables": [1, 2]},
    ]
    d = TableMergeDialog(client=client, tables=tables, groups=groups)
    qtbot.addWidget(d)

    fired: list[bool] = []
    d.groups_changed.connect(lambda: fired.append(True))

    client.post.return_value = {"data": {"id": 99, "closed_at": "..."}}
    btn = next(b for b in d.findChildren(QPushButton) if b.text() == "Разъединить")
    qtbot.mouseClick(btn, Qt.LeftButton)

    args, kwargs = client.post.call_args
    assert args[0] == "/tables/groups/99/unmerge/"
    assert fired == [True]


# -------- TableCard merged status --------


def test_table_card_renders_merged_status(qtbot):
    from pos.widgets.table_card import TableCard

    card = TableCard(
        {"id": 5, "name": "Стол 5", "number": 5, "status": "merged"},
    )
    qtbot.addWidget(card)
    # Проверяем что нет краша + статус сохранён
    assert card._status == "merged"


def test_primary_in_group_shows_combined_title(qtbot):
    from pos.widgets.table_card import TableCard
    from PySide6.QtWidgets import QLabel

    card = TableCard({
        "id": 5, "name": "Стол 5", "number": 5, "status": "free",
        "group": {
            "id": 99, "primary_table_id": 5,
            "table_names": ["Стол 5", "Стол 6"],
            "table_ids": [5, 6],
        },
    })
    qtbot.addWidget(card)

    titles = [
        l.text() for l in card.findChildren(QLabel) if l.text()
    ]
    # Заголовок «5+6»
    assert any("5+6" in t for t in titles)


def test_non_primary_in_group_shows_own_name(qtbot):
    from pos.widgets.table_card import TableCard
    from PySide6.QtWidgets import QLabel

    card = TableCard({
        "id": 6, "name": "Стол 6", "number": 6, "status": "merged",
        "group": {
            "id": 99, "primary_table_id": 5,
            "table_names": ["Стол 5", "Стол 6"],
            "table_ids": [5, 6],
        },
    })
    qtbot.addWidget(card)
    titles = [l.text() for l in card.findChildren(QLabel) if l.text()]
    # Сам стол 6, не primary — показываем «Стол 6»
    assert any("Стол 6" in t for t in titles)
    assert not any("5+6" in t for t in titles)


def test_merged_card_click_emits_noop(qtbot):
    from pos.widgets.table_card import TableCard
    from PySide6.QtCore import Qt

    card = TableCard(
        {"id": 6, "name": "Стол 6", "number": 6, "status": "merged"},
    )
    qtbot.addWidget(card)
    fired: list[tuple] = []
    card.clicked.connect(lambda tid, action: fired.append((tid, action)))
    qtbot.mouseClick(card, Qt.LeftButton)
    assert fired == [(6, "noop")]


# -------- Multi-group rendering --------


def test_table_card_renders_two_groups(qtbot):
    """Если active_orders >=2 — карточка показывает «Гр.1: ... / Гр.2: ...»"""
    from pos.widgets.table_card import TableCard
    from PySide6.QtWidgets import QPushButton

    card = TableCard({
        "id": 5, "name": "Стол 5", "number": 5, "status": "occupied",
        "active_orders": [
            {"id": 100, "guests_count": 2, "total": "680.00",
             "waiter_name": "X", "status": "new"},
            {"id": 101, "guests_count": 3, "total": "376.00",
             "waiter_name": "Y", "status": "new"},
        ],
    })
    qtbot.addWidget(card)
    btns = card.findChildren(QPushButton)
    texts = [b.text() for b in btns]
    assert any("Гр.1" in t for t in texts)
    assert any("Гр.2" in t for t in texts)
    assert any("680" in t for t in texts)
    assert any("376" in t for t in texts)


def test_table_card_single_group_does_not_render_groups(qtbot):
    """Если active_orders == 1 — обычный рендер, без «Гр.» строк."""
    from pos.widgets.table_card import TableCard
    from PySide6.QtWidgets import QPushButton

    card = TableCard({
        "id": 5, "name": "Стол 5", "number": 5, "status": "occupied",
        "guests_count": 2,
        "active_orders": [
            {"id": 100, "guests_count": 2, "total": "680.00",
             "waiter_name": "X", "status": "new"},
        ],
    })
    qtbot.addWidget(card)
    btns = card.findChildren(QPushButton)
    texts = [b.text() for b in btns]
    assert not any("Гр.1" in t for t in texts)


def test_group_clicked_signal_emits_table_and_order(qtbot):
    from pos.widgets.table_card import TableCard
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton

    card = TableCard({
        "id": 5, "name": "Стол 5", "number": 5, "status": "occupied",
        "active_orders": [
            {"id": 100, "guests_count": 2, "total": "1.00",
             "waiter_name": "X", "status": "new"},
            {"id": 101, "guests_count": 3, "total": "2.00",
             "waiter_name": "Y", "status": "new"},
        ],
    })
    qtbot.addWidget(card)

    fired: list = []
    card.group_clicked.connect(lambda tid, oid: fired.append((tid, oid)))

    btns = [b for b in card.findChildren(QPushButton) if "Гр." in b.text()]
    qtbot.mouseClick(btns[1], Qt.LeftButton)
    assert fired == [(5, 101)]
