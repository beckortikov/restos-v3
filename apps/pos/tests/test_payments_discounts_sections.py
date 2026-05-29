"""PaymentsSection (frame 21) + DiscountsSection (frame 22) — POS frontend."""
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt


@pytest.fixture
def mock_client():
    c = MagicMock()
    c.get.return_value = []
    return c


# -------- PaymentsSection --------


@pytest.fixture
def payments_section(qtbot, mock_client):
    from pos.screens.settings_sections.payments_section import PaymentsSection

    s = PaymentsSection(client=mock_client)
    qtbot.addWidget(s)
    s.show()
    yield s


def test_payments_empty_state(qtbot, payments_section, mock_client):
    mock_client.get.return_value = []
    payments_section.reload()
    qtbot.waitUntil(
        lambda: payments_section._empty_label.isVisible(), timeout=2000
    )


def test_payments_render_cards(qtbot, payments_section, mock_client):
    mock_client.get.return_value = [
        {"id": 1, "kind": "cash", "name": "Наличные",
         "description": "—", "commission_pct": "0.00",
         "is_active": True, "sort_order": 0},
        {"id": 2, "kind": "card", "name": "Карта",
         "description": "Alif", "commission_pct": "1.50",
         "is_active": True, "sort_order": 1},
    ]
    payments_section.reload()
    qtbot.waitUntil(
        lambda: payments_section._list_layout.count() == 2, timeout=2000
    )


def test_payments_toggle_calls_api(qtbot, payments_section, mock_client):
    from pos.widgets.toggle_switch import ToggleSwitch

    mock_client.get.return_value = [
        {"id": 7, "kind": "cash", "name": "Наличные",
         "description": "", "commission_pct": "0",
         "is_active": True, "sort_order": 0},
    ]
    mock_client.request.return_value = {"id": 7, "is_active": False}
    payments_section.reload()
    qtbot.waitUntil(
        lambda: payments_section._list_layout.count() == 1, timeout=2000
    )
    toggle = payments_section.findChild(ToggleSwitch)
    qtbot.mouseClick(toggle, Qt.LeftButton)
    qtbot.waitUntil(lambda: mock_client.request.called, timeout=2000)
    args, kwargs = mock_client.request.call_args
    assert args[0] == "PATCH"
    assert args[1] == "/payment_providers/7/"
    assert "is_active" in kwargs["json"]


# -------- DiscountsSection --------


@pytest.fixture
def discounts_section(qtbot, mock_client):
    from pos.screens.settings_sections.discounts_section import DiscountsSection

    s = DiscountsSection(client=mock_client)
    qtbot.addWidget(s)
    s.show()
    yield s


def test_discounts_render_two_sections(qtbot, discounts_section, mock_client):
    mock_client.get.return_value = [
        {"id": 1, "type": "discount", "name": "Сотрудник",
         "description": "—", "kind": "percent", "value": "10.00",
         "is_active": True, "sort_order": 0},
        {"id": 2, "type": "discount", "name": "Клиент",
         "description": "—", "kind": "percent", "value": "15.00",
         "is_active": False, "sort_order": 1},
        {"id": 3, "type": "service", "name": "Сервис",
         "description": "—", "kind": "percent", "value": "12.00",
         "is_active": True, "sort_order": 0},
    ]
    discounts_section.reload()
    qtbot.waitUntil(lambda: len(discounts_section._items) == 3, timeout=2000)
    # 2 секции (label + cards) + service-card. content_layout содержит:
    # «Скидки» + 2 карточки + «Сервисный сбор» + 1 карточка = 5 элементов
    assert discounts_section._content_layout.count() == 5


def test_discounts_toggle_calls_api(qtbot, discounts_section, mock_client):
    from pos.widgets.toggle_switch import ToggleSwitch

    mock_client.get.return_value = [
        {"id": 5, "type": "discount", "name": "X",
         "description": "", "kind": "percent", "value": "10",
         "is_active": True, "sort_order": 0},
    ]
    mock_client.request.return_value = {"id": 5, "is_active": False}
    discounts_section.reload()
    qtbot.waitUntil(lambda: len(discounts_section._items) == 1, timeout=2000)

    toggles = discounts_section.findChildren(ToggleSwitch)
    assert len(toggles) >= 1
    qtbot.mouseClick(toggles[0], Qt.LeftButton)
    qtbot.waitUntil(lambda: mock_client.request.called, timeout=2000)
    args, _ = mock_client.request.call_args
    assert args[0] == "PATCH"
    assert "/discounts/5/" in args[1]


def test_discounts_empty_state(qtbot, discounts_section, mock_client):
    mock_client.get.return_value = []
    discounts_section.reload()
    # waitUntil по факту перерисовки — content_layout получит 4 widget'а:
    # «Скидки» label + empty + «Сервисный сбор» label + empty.
    qtbot.waitUntil(
        lambda: discounts_section._content_layout.count() == 4, timeout=2000
    )


# -------- Settings wiring --------


def test_settings_screen_includes_payment_and_discounts(qtbot):
    """payment и discounts больше не stub'ы, а реальные секции."""
    from pos.screens.settings_screen import SettingsScreen
    from pos.screens.settings_sections.discounts_section import DiscountsSection
    from pos.screens.settings_sections.payments_section import PaymentsSection

    state = MagicMock()
    state.client = MagicMock()
    state.client.get.return_value = []
    s = SettingsScreen(state)
    qtbot.addWidget(s)
    assert isinstance(s._section_widgets.get("payment"), PaymentsSection)
    assert isinstance(s._section_widgets.get("discounts"), DiscountsSection)


# -------- Edit dialogs --------


def test_payment_edit_dialog_save_post(qtbot, mock_client):
    from PySide6.QtWidgets import QPushButton
    from pos.screens.settings_sections.payment_edit_dialog import PaymentEditDialog

    mock_client.request.return_value = {"id": 99, "name": "X"}
    d = PaymentEditDialog(client=mock_client, provider=None)
    qtbot.addWidget(d)
    d.name_edit.setText("Новый эквайер")
    d.commission_spin.setValue(2.5)

    btns = d.findChildren(QPushButton)
    save = next(b for b in btns if b.text() == "Сохранить")
    qtbot.mouseClick(save, Qt.LeftButton)

    args, kwargs = mock_client.request.call_args
    assert args[0] == "POST"
    assert args[1] == "/payment_providers/"
    body = kwargs["json"]
    assert body["name"] == "Новый эквайер"
    assert body["commission_pct"] == "2.50"


def test_discount_edit_dialog_validates_name(qtbot, mock_client):
    from PySide6.QtWidgets import QPushButton
    from pos.screens.settings_sections.discount_edit_dialog import DiscountEditDialog

    d = DiscountEditDialog(client=mock_client, discount=None)
    qtbot.addWidget(d)
    btns = d.findChildren(QPushButton)
    save = next(b for b in btns if b.text() == "Сохранить")
    with patch(
        "pos.screens.settings_sections.discount_edit_dialog.QMessageBox.warning"
    ) as warn:
        qtbot.mouseClick(save, Qt.LeftButton)
        assert warn.called
    assert not mock_client.request.called
