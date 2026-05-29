import importlib
import ipaddress

import pytest

import pos.config as cfg
from pos.lib.net import detect_lan_ip
from pos.lib.qr import render_qr_svg


def test_detect_lan_ip_returns_ipv4_string():
    ip = detect_lan_ip()
    # Должна быть валидной IPv4-строкой (или 127.0.0.1 при отсутствии сети)
    addr = ipaddress.IPv4Address(ip)
    assert isinstance(addr, ipaddress.IPv4Address)


def test_render_qr_svg_returns_nonempty_svg_bytes():
    svg = render_qr_svg("http://192.168.1.10/")
    assert isinstance(svg, bytes)
    assert svg.lstrip().startswith(b"<svg")
    assert len(svg) > 100


def test_render_qr_svg_encodes_url_correction_h():
    # Уровень H — большая ёмкость заголовка; SVG отличается от L по числу
    # модулей. Тут просто проверяем что разные URL дают разный SVG.
    a = render_qr_svg("http://a/")
    b = render_qr_svg("http://b/")
    assert a != b


def test_get_pair_url_uses_env_override(monkeypatch):
    monkeypatch.setenv("RESTOS_PAIR_URL", "http://override.example/")
    importlib.reload(cfg)
    try:
        assert cfg.get_pair_url() == "http://override.example/"
    finally:
        monkeypatch.delenv("RESTOS_PAIR_URL", raising=False)
        importlib.reload(cfg)


def test_get_pair_url_falls_back_to_lan_ip(monkeypatch):
    monkeypatch.delenv("RESTOS_PAIR_URL", raising=False)
    importlib.reload(cfg)
    url = cfg.get_pair_url()
    assert url.startswith("http://")
    assert url.endswith("/")


@pytest.mark.usefixtures("qtbot")
def test_tablet_pairing_dialog_shows_url(qtbot):
    from pos.screens.tablet_pairing_screen import TabletPairingDialog

    dlg = TabletPairingDialog("http://10.0.0.7/")
    qtbot.addWidget(dlg)
    # URL отображается одним из QLabel'ов
    from PySide6.QtWidgets import QLabel

    labels = [w.text() for w in dlg.findChildren(QLabel)]
    assert "http://10.0.0.7/" in labels
    assert dlg.url == "http://10.0.0.7/"
