"""Phase 7E — smoke-тесты BatchCookDialog (+N порций)."""
from unittest.mock import MagicMock


def test_batch_cook_dialog_renders(qtbot):
    from pos.screens.settings_sections.batch_cook_dialog import BatchCookDialog

    client = MagicMock()
    item = {"id": 7, "name": "Плов", "prepared_qty": 5}
    dlg = BatchCookDialog(client, item)
    qtbot.addWidget(dlg)
    assert dlg.qty_spin.value() == 10  # default
    assert dlg.qty_spin.suffix() == " порций"


def test_batch_cook_dialog_submits_payload(qtbot):
    from pos.screens.settings_sections.batch_cook_dialog import BatchCookDialog

    client = MagicMock()
    client.post.return_value = {"data": {"id": 7, "prepared_qty": 25}}
    item = {"id": 7, "name": "Плов", "prepared_qty": 5}
    dlg = BatchCookDialog(client, item)
    qtbot.addWidget(dlg)
    dlg.qty_spin.setValue(20)
    dlg.note_edit.setText("Утренняя варка")
    dlg._submit()

    client.post.assert_called_once()
    args, kwargs = client.post.call_args
    assert args[0] == "/menu/items/7/batch_cook/"
    assert kwargs["json"] == {"qty": 20, "note": "Утренняя варка"}
    assert kwargs["idempotent"] is True


def test_batch_cook_dialog_keeps_open_on_error(qtbot, monkeypatch):
    from pos.http_client import ApiError
    from pos.screens.settings_sections.batch_cook_dialog import BatchCookDialog

    monkeypatch.setattr(
        "pos.screens.settings_sections.batch_cook_dialog.QMessageBox.warning",
        lambda *a, **k: None,
    )

    client = MagicMock()
    client.post.side_effect = ApiError("INSUFFICIENT_STOCK", "Не хватает риса", 400)
    item = {"id": 7, "name": "Плов", "prepared_qty": 5}
    dlg = BatchCookDialog(client, item)
    qtbot.addWidget(dlg)
    dlg.qty_spin.setValue(50)
    dlg._submit()
    # Dialog не закрылся — accept не вызывался
    assert dlg.isVisible() or not dlg.result()
