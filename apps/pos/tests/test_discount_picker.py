"""DiscountPickerDialog (Phase 4) + интеграция в PaymentDialog."""
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def order():
    return {
        "id": 42, "items": [
            {"id": 10, "name_at_order": "Плов", "qty": 2,
             "price_at_order": "45.00", "subtotal": "90.00",
             "cancelled_at": None},
        ],
        "subtotal": "90.00",
        "service_charge_pct": "0.00",
        "service_charge_amount": "0.00",
        "discount_amount": "0.00",
        "discount_kind": "",
        "applied_discount": None,
        "total": "90.00",
        "guests_count": 1,
    }


@pytest.fixture
def discounts():
    return [
        {"id": 1, "type": "discount", "name": "Сотрудник",
         "kind": "percent", "value": "10.00", "is_active": True},
        {"id": 2, "type": "discount", "name": "Постоянный",
         "kind": "percent", "value": "15.00", "is_active": True},
        {"id": 3, "type": "discount", "name": "Фикс 5",
         "kind": "fixed", "value": "5.00", "is_active": True},
        # Inactive — не должен попасть в список
        {"id": 4, "type": "discount", "name": "Off",
         "kind": "percent", "value": "50.00", "is_active": False},
    ]


# -------- DiscountPickerDialog --------


def test_picker_filters_inactive(qtbot, order, discounts, mock_client):
    from pos.screens.discount_picker_dialog import DiscountPickerDialog

    d = DiscountPickerDialog(
        order=order, discounts=discounts, client=mock_client,
    )
    qtbot.addWidget(d)
    # Должно быть 4 кнопки опций: «Без скидки» + 3 active discounts
    btns = d.findChildren(QPushButton)
    # Из всех QPushButton'ов только options + Закрыть. Считаем option-кнопки
    # по тексту: на них висят QLabel'ы (используем findChildren на каждой)
    from PySide6.QtWidgets import QLabel

    labels = [l.text() for l in d.findChildren(QLabel)]
    assert "Без скидки" in labels
    assert "Сотрудник" in labels
    assert "Постоянный" in labels
    assert "Фикс 5" in labels
    # Inactive не попал
    assert "Off" not in labels


def test_picker_filters_service_type(qtbot, order, mock_client):
    from PySide6.QtWidgets import QLabel
    from pos.screens.discount_picker_dialog import DiscountPickerDialog

    discs = [
        {"id": 1, "type": "discount", "name": "OK",
         "kind": "percent", "value": "10.00", "is_active": True},
        {"id": 2, "type": "service", "name": "СЕРВИС",
         "kind": "percent", "value": "12.00", "is_active": True},
    ]
    d = DiscountPickerDialog(order=order, discounts=discs, client=mock_client)
    qtbot.addWidget(d)
    labels = [l.text() for l in d.findChildren(QLabel)]
    assert "OK" in labels
    assert "СЕРВИС" not in labels  # service отфильтрован


def test_picker_apply_calls_api(qtbot, order, discounts, mock_client):
    from PySide6.QtWidgets import QLabel
    from pos.screens.discount_picker_dialog import DiscountPickerDialog

    mock_client.post.return_value = {"id": 42, "discount_amount": "9.00", "total": "81.00"}
    d = DiscountPickerDialog(
        order=order, discounts=discounts, client=mock_client,
    )
    qtbot.addWidget(d)
    fired: list[dict] = []
    d.discount_applied.connect(lambda o: fired.append(o))

    # Найти option-кнопку «Сотрудник»
    btns = d.findChildren(QPushButton)
    btn = next(
        b for b in btns
        if any("Сотрудник" == l.text() for l in b.findChildren(QLabel))
    )
    qtbot.mouseClick(btn, Qt.LeftButton)
    qtbot.waitUntil(lambda: mock_client.post.called, timeout=2000)

    args, kwargs = mock_client.post.call_args
    assert args[0] == "/orders/42/apply_discount/"
    assert kwargs["json"] == {"discount_id": 1}
    qtbot.waitUntil(lambda: bool(fired), timeout=2000)


def test_picker_no_discount_calls_remove(qtbot, order, discounts, mock_client):
    from PySide6.QtWidgets import QLabel
    from pos.screens.discount_picker_dialog import DiscountPickerDialog

    mock_client.post.return_value = {"id": 42, "discount_amount": "0.00", "total": "90.00"}
    d = DiscountPickerDialog(
        order=order, discounts=discounts, client=mock_client,
    )
    qtbot.addWidget(d)

    btns = d.findChildren(QPushButton)
    btn = next(
        b for b in btns
        if any(l.text() == "Без скидки" for l in b.findChildren(QLabel))
    )
    qtbot.mouseClick(btn, Qt.LeftButton)
    qtbot.waitUntil(lambda: mock_client.post.called, timeout=2000)

    args, kwargs = mock_client.post.call_args
    assert args[0] == "/orders/42/remove_discount/"


def test_picker_empty_state(qtbot, order, mock_client):
    from PySide6.QtWidgets import QLabel
    from pos.screens.discount_picker_dialog import DiscountPickerDialog

    d = DiscountPickerDialog(order=order, discounts=[], client=mock_client)
    qtbot.addWidget(d)
    labels = [l.text() for l in d.findChildren(QLabel)]
    assert any("Активных скидок нет" in t for t in labels)


def test_picker_value_format_percent(qtbot, order, mock_client):
    from PySide6.QtWidgets import QLabel
    from pos.screens.discount_picker_dialog import DiscountPickerDialog

    discs = [{
        "id": 1, "type": "discount", "name": "X",
        "kind": "percent", "value": "10.00", "is_active": True,
    }]
    d = DiscountPickerDialog(order=order, discounts=discs, client=mock_client)
    qtbot.addWidget(d)
    labels = [l.text() for l in d.findChildren(QLabel)]
    assert any("−10%" in t for t in labels)


def test_picker_value_format_fixed(qtbot, order, mock_client):
    from PySide6.QtWidgets import QLabel
    from pos.screens.discount_picker_dialog import DiscountPickerDialog

    discs = [{
        "id": 1, "type": "discount", "name": "X",
        "kind": "fixed", "value": "5.00", "is_active": True,
    }]
    d = DiscountPickerDialog(order=order, discounts=discs, client=mock_client)
    qtbot.addWidget(d)
    labels = [l.text() for l in d.findChildren(QLabel)]
    assert any("−5.00 TJS" in t for t in labels)


# -------- PaymentDialog discount integration --------


def test_payment_dialog_shows_discount_row(qtbot, mock_client):
    from PySide6.QtWidgets import QLabel
    from pos.screens.payment_dialog import PaymentDialog

    order = {
        "id": 50, "items": [],
        "subtotal": "100.00",
        "discount_amount": "10.00",
        "discount_name": "Сотрудник",
        "service_charge_amount": "0.00",
        "service_charge_pct": "0.00",
        "total": "90.00",
        "guests_count": 1,
    }
    dlg = PaymentDialog(order=order, table={"name": "Стол 1"}, client=mock_client)
    qtbot.addWidget(dlg)
    labels = [l.text() for l in dlg.findChildren(QLabel)]
    # Лейбл с именем скидки
    assert any("Скидка (Сотрудник)" in t for t in labels)
    # Сумма скидки
    assert any("−10.00" in t for t in labels)


def test_payment_dialog_open_discount_picker(qtbot, mock_client):
    """Клик по строке «Скидка» открывает picker."""
    from pos.screens.payment_dialog import PaymentDialog

    mock_client.get.return_value = []  # API discounts empty
    order = {
        "id": 50, "items": [],
        "subtotal": "100.00",
        "discount_amount": "0.00",
        "service_charge_amount": "0.00",
        "service_charge_pct": "0.00",
        "total": "100.00",
        "guests_count": 1,
    }
    dlg = PaymentDialog(order=order, table={"name": "Стол 1"}, client=mock_client)
    qtbot.addWidget(dlg)

    # Найти кликабельную «Скидка» строку (QPushButton flat)
    btns = dlg.findChildren(QPushButton)
    discount_row = None
    from PySide6.QtWidgets import QLabel
    for b in btns:
        for l in b.findChildren(QLabel):
            if l.text() == "Скидка":
                discount_row = b
                break
        if discount_row:
            break
    assert discount_row is not None

    # Patch DiscountPickerDialog.exec чтобы не открывать модалку
    with patch(
        "pos.screens.discount_picker_dialog.DiscountPickerDialog.exec",
        return_value=0,
    ) as mock_exec:
        qtbot.mouseClick(discount_row, Qt.LeftButton)
        assert mock_exec.called
