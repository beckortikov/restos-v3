import pytest
from PySide6.QtCore import Qt


@pytest.fixture
def sidebar(qtbot):
    from pos.widgets.sidebar import Sidebar

    s = Sidebar(active="tables")
    qtbot.addWidget(s)
    return s


def test_default_active(sidebar):
    assert sidebar._buttons["tables"].isChecked()
    assert not sidebar._buttons["orders"].isChecked()
    assert not sidebar._buttons["logout"].isChecked()


def test_orders_button_enabled(sidebar):
    """Заказы — экран 3 в C-01, реализован → enabled."""
    assert sidebar._buttons["orders"].isEnabled()


def test_click_logout_emits(qtbot, sidebar):
    seen: list[str] = []
    sidebar.nav_clicked.connect(lambda n: seen.append(n))
    qtbot.mouseClick(sidebar._buttons["logout"], Qt.LeftButton)
    assert seen == ["logout"]


def test_set_active(sidebar):
    sidebar.set_active("orders")
    assert sidebar._buttons["orders"].isChecked()
    assert not sidebar._buttons["tables"].isChecked()


def test_fixed_width(sidebar):
    from pos.widgets.sidebar import SIDEBAR_WIDTH

    assert sidebar.width() == SIDEBAR_WIDTH
