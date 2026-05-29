"""CashOpDialog: внесение/изъятие через POST /shifts/{id}/cash_op/."""
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt


@pytest.fixture
def client():
    return MagicMock()


@pytest.fixture
def dlg(qtbot, client):
    from pos.screens.cash_op_dialog import CashOpDialog

    d = CashOpDialog(client=client, shift_id=42)
    qtbot.addWidget(d)
    yield d


def test_default_radio_is_cash_out(dlg):
    """По умолчанию выбрано «Изъятие» — частая операция."""
    assert dlg._rb_out.isChecked()
    assert not dlg._rb_in.isChecked()
    assert dlg._kind() == "cash_out"


def test_save_disabled_until_amount_entered(dlg):
    assert not dlg._save_btn.isEnabled()
    dlg._amount_input.setText("250")
    assert dlg._save_btn.isEnabled()


def test_save_disabled_for_invalid_amount(dlg):
    dlg._amount_input.setText("0")
    assert not dlg._save_btn.isEnabled()
    dlg._amount_input.setText("abc")
    # текст очищается при clean — должно остаться пусто
    assert not dlg._save_btn.isEnabled()


def test_amount_input_filters_non_numeric(dlg):
    dlg._amount_input.setText("12abc.50xy")
    assert dlg._amount_input.text() == "12.50"


def test_amount_allows_only_one_dot(dlg):
    dlg._amount_input.setText("12.3.4")
    assert dlg._amount_input.text() == "12.34"


def test_save_posts_to_endpoint_with_correct_body(qtbot, dlg, client):
    client.post.return_value = {"data": {"id": 7, "kind": "cash_out", "amount": "250.00"}}
    dlg._amount_input.setText("250")
    dlg._reason_input.setPlainText("Закупка овощей")
    dlg._rb_out.setChecked(True)

    fired: list[dict] = []
    dlg.op_created.connect(lambda op: fired.append(op))

    qtbot.mouseClick(dlg._save_btn, Qt.LeftButton)

    client.post.assert_called_once()
    args, kwargs = client.post.call_args
    assert args[0] == "/shifts/42/cash_op/"
    assert kwargs["json"]["kind"] == "cash_out"
    assert kwargs["json"]["amount"] == "250"
    assert kwargs["json"]["reason"] == "Закупка овощей"
    assert len(fired) == 1
    assert fired[0]["id"] == 7


def test_save_with_cash_in_kind(qtbot, dlg, client):
    client.post.return_value = {"data": {"id": 8, "kind": "cash_in", "amount": "1000.00"}}
    dlg._rb_in.setChecked(True)
    dlg._amount_input.setText("1000")
    qtbot.mouseClick(dlg._save_btn, Qt.LeftButton)
    args, kwargs = client.post.call_args
    assert kwargs["json"]["kind"] == "cash_in"


def test_save_handles_api_error(qtbot, dlg, client, monkeypatch):
    from pos.http_client import ApiError

    client.post.side_effect = ApiError(
        "INVALID_TRANSITION", "Смена закрыта", 422,
    )
    dlg._amount_input.setText("100")

    # Подменим QMessageBox.warning чтобы не блокировать тест
    from pos.screens import cash_op_dialog as mod
    called: list = []
    monkeypatch.setattr(
        mod.QMessageBox, "warning",
        lambda *args, **kwargs: called.append(args),
    )

    qtbot.mouseClick(dlg._save_btn, Qt.LeftButton)
    assert called  # warning показан
    # Диалог не закрылся
    assert dlg.isVisible() or not dlg.result()  # accepted ещё не вызван
