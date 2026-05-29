# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec для RestOS POS (Windows .exe).

Запуск локально:
    cd apps/pos
    pyinstaller pos.spec --noconfirm --clean

Результат:
    apps/pos/dist/RestOS-POS/RestOS-POS.exe  (+ нужные DLL/PySide6 plugins)
"""
import os
import sys
from pathlib import Path

block_cipher = None

ROOT = Path(SPECPATH).resolve()
# Дополнительные ресурсы (иконки, fonts, токены, qss)
datas = []
for sub in ("resources",):
    src = ROOT / "pos" / sub
    if src.exists():
        datas.append((str(src), f"pos/{sub}"))

hiddenimports = [
    # PySide6 ядро
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtNetwork",
    "PySide6.QtSvg",
    # http/sse
    "requests",
    "sseclient",
    # keyring backends — на Windows нужен windows backend
    "keyring.backends.Windows",
    "keyring.backends.SecretService",
    "keyring.backends.macOS",
    # QR-генератор
    "segno",
    # opt-cache (если есть)
    "apsw",
]

a = Analysis(
    ["pos/__main__.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Не нужны в exe — экономим размер
        "tkinter",
        "test",
        "unittest",
        "pytest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RestOS-POS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,            # GUI-приложение, без консольного окна
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,                # TODO: добавить .ico когда будет
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="RestOS-POS",
)
