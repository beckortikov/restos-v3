"""GeneralSection: receipt_copies SpinBox + PATCH endpoint."""
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def client():
    return MagicMock()


@pytest.fixture
def section(qtbot, client):
    from pos.screens.settings_sections.general_section import GeneralSection

    s = GeneralSection(client=client)
    qtbot.addWidget(s)
    yield s


def test_copies_spin_present(section):
    assert hasattr(section, "_copies_spin")
    assert section._copies_spin.minimum() == 1
    assert section._copies_spin.maximum() == 5


def test_save_calls_patch_endpoint(qtbot, section, client, monkeypatch):
    """PATCH /restaurant/ с правильным body. QMessageBox замокан чтобы не
    блокировать тест."""
    from pos.screens.settings_sections import general_section as mod

    monkeypatch.setattr(mod.QMessageBox, "information", lambda *a, **kw: None)
    monkeypatch.setattr(mod.QMessageBox, "warning", lambda *a, **kw: None)

    section._copies_spin.setValue(3)
    section._on_save_print_settings()

    args, kwargs = client.request.call_args
    assert args[0] == "PATCH"
    assert args[1] == "/restaurant/"
    assert kwargs["json"]["receipt_copies"] == 3


def test_render_sets_spin_from_data(section):
    section._data = {"restaurant": {"receipt_copies": 2}}
    section._render()
    assert section._copies_spin.value() == 2


def test_render_falls_back_to_one_when_missing(section):
    section._data = {"restaurant": {}}
    section._render()
    assert section._copies_spin.value() == 1


# -------- Kitchen toggle --------


def test_kitchen_toggle_present(section):
    assert hasattr(section, "_kitchen_chk")


def test_kitchen_toggle_default_checked_after_render(section):
    section._data = {"restaurant": {"kitchen_enabled": True}}
    section._render()
    assert section._kitchen_chk.isChecked()


def test_kitchen_toggle_unchecked_when_disabled(section):
    section._data = {"restaurant": {"kitchen_enabled": False}}
    section._render()
    assert not section._kitchen_chk.isChecked()


def test_save_kitchen_calls_patch(section, client, monkeypatch):
    from pos.screens.settings_sections import general_section as mod

    monkeypatch.setattr(mod.QMessageBox, "information", lambda *a, **kw: None)
    monkeypatch.setattr(mod.QMessageBox, "warning", lambda *a, **kw: None)

    section._kitchen_chk.setChecked(False)
    section._on_save_kitchen_settings()
    args, kwargs = client.request.call_args
    assert args[0] == "PATCH"
    assert args[1] == "/restaurant/"
    assert kwargs["json"]["kitchen_enabled"] is False


# -------- Manager override threshold --------


def test_override_input_present(section):
    assert hasattr(section, "_override_input")


def test_override_input_filled_from_data(section):
    section._data = {"restaurant": {"manager_override_threshold_tjs": "1500.00"}}
    section._render()
    assert section._override_input.text() == "1500.00"


def test_save_override_calls_patch(section, client, monkeypatch):
    from pos.screens.settings_sections import general_section as mod

    monkeypatch.setattr(mod.QMessageBox, "information", lambda *a, **kw: None)
    monkeypatch.setattr(mod.QMessageBox, "warning", lambda *a, **kw: None)

    section._override_input.setText("1500")
    section._on_save_override_settings()
    args, kwargs = client.request.call_args
    assert args[0] == "PATCH"
    assert kwargs["json"]["manager_override_threshold_tjs"] == "1500"


def test_save_override_rejects_negative(section, client, monkeypatch):
    from pos.screens.settings_sections import general_section as mod

    warnings_called: list = []
    monkeypatch.setattr(
        mod.QMessageBox, "warning",
        lambda *a, **kw: warnings_called.append(True),
    )
    section._override_input.setText("-100")
    section._on_save_override_settings()
    assert warnings_called  # Показал warning
    # PATCH не вызван
    assert not client.request.called


# -------- Receipt customization --------


def test_receipt_inputs_present(section):
    assert hasattr(section, "_header_extra_input")
    assert hasattr(section, "_footer_input")
    assert hasattr(section, "_cash_drawer_chk")


def test_receipt_filled_from_data(section):
    section._data = {"restaurant": {
        "receipt_header_extra": "ИНН 123",
        "receipt_footer": "Wi-Fi free",
        "auto_open_cash_drawer": True,
    }}
    section._render()
    assert "ИНН 123" in section._header_extra_input.toPlainText()
    assert "Wi-Fi" in section._footer_input.toPlainText()
    assert section._cash_drawer_chk.isChecked()


def test_save_receipt_calls_patch(section, client, monkeypatch):
    from pos.screens.settings_sections import general_section as mod

    monkeypatch.setattr(mod.QMessageBox, "information", lambda *a, **kw: None)
    monkeypatch.setattr(mod.QMessageBox, "warning", lambda *a, **kw: None)

    section._header_extra_input.setPlainText("ИНН 999")
    section._footer_input.setPlainText("Hello!")
    section._cash_drawer_chk.setChecked(True)
    section._on_save_receipt_settings()
    args, kwargs = client.request.call_args
    assert args[0] == "PATCH"
    body = kwargs["json"]
    assert body["receipt_header_extra"] == "ИНН 999"
    assert body["receipt_footer"] == "Hello!"
    assert body["auto_open_cash_drawer"] is True
