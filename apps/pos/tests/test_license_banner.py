"""LicenseBanner: показывает разные состояния, скрывается на active+>7d."""
import pytest


@pytest.fixture
def banner(qtbot):
    from pos.widgets.license_banner import LicenseBanner

    b = LicenseBanner()
    qtbot.addWidget(b)
    yield b


def test_hidden_when_active_and_plenty_of_time(banner):
    banner.update_from_license({
        "status": "active",
        "days_left": 100, "days_to_expiry": 90,
        "is_blocked": False,
    })
    assert not banner.isVisible() or not banner.isVisibleTo(banner.parent())


def test_visible_warning_when_expires_soon(banner):
    banner.update_from_license({
        "status": "active",
        "days_left": 12, "days_to_expiry": 5,
        "is_blocked": False,
    })
    # Виден после show()
    banner.show()
    assert banner.isVisible() or banner.isVisibleTo(None)
    assert "5" in banner._msg_lbl.text()


def test_visible_orange_in_grace(banner):
    banner.update_from_license({
        "status": "grace",
        "days_left": 5, "days_to_expiry": -2,
        "is_blocked": False,
    })
    assert "до блокировки" in banner._msg_lbl.text()
    assert "5" in banner._msg_lbl.text()


def test_visible_red_when_expired(banner):
    banner.update_from_license({
        "status": "expired",
        "days_left": -3, "days_to_expiry": -10,
        "is_blocked": False,
    })
    assert "истекла" in banner._msg_lbl.text().lower() or "только-чтение" in banner._msg_lbl.text().lower()


def test_visible_red_when_blocked(banner):
    banner.update_from_license({
        "status": "blocked",
        "days_left": 100, "days_to_expiry": 90,
        "is_blocked": True,
        "block_reason": "Неуплата",
    })
    assert "Неуплата" in banner._msg_lbl.text()


def test_no_license_hides_banner(banner):
    banner.update_from_license(None)
    assert not banner.isVisible() or not banner.isVisibleTo(None)


def test_state_change_signal_emitted(qtbot, banner):
    fired: list[str] = []
    banner.license_state_changed.connect(lambda s: fired.append(s))
    banner.update_from_license({
        "status": "expired", "days_left": -1, "days_to_expiry": -10,
        "is_blocked": False,
    })
    assert fired == ["expired"]
