# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec для RestOS POS (Single-exe с embedded backend).

Single-exe бандлит:
- PySide6 GUI кассира
- Django backend (apps/backend) — поднимается через EmbeddedBackend
- Postgres binaries — через pgserver (он сам тащит portable bundle)
- pgserver — Python библиотека для embedded Postgres

При запуске EmbeddedBackend поднимет Postgres + Django, потом загрузится GUI.

Запуск локально:
    cd apps/pos
    .venv/bin/pyinstaller pos.spec --noconfirm --clean
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

ROOT = Path(SPECPATH).resolve()
REPO_ROOT = ROOT.parent.parent  # apps/pos → repo root
BACKEND_DIR = REPO_ROOT / "apps" / "backend"

# ── datas: ресурсы POS + код Django ───────────────────────────────────────
datas = []

# POS-ресурсы (иконки, токены, QSS)
for sub in ("resources",):
    src = ROOT / "pos" / sub
    if src.exists():
        datas.append((str(src), f"pos/{sub}"))

# Embedded backend — копируем весь Django проект в bundle/backend/
# EmbeddedBackend.sys.path.insert(0, sys._MEIPASS/backend) — поднимется оттуда.
if BACKEND_DIR.exists():
    # Каждый Django app: код + миграции + templates
    for sub in ("apps", "config", "common"):
        s = BACKEND_DIR / sub
        if s.exists():
            datas.append((str(s), f"backend/{sub}"))
    # manage.py чтобы можно было ./RestOS-POS.exe migrate если кто-то захочет
    mp = BACKEND_DIR / "manage.py"
    if mp.exists():
        datas.append((str(mp), "backend"))

# pgserver — нужны ВСЕ его data-файлы (binaries, share/, tzdata).
# include_py_files=False по умолчанию, но extensionless TZif файлы
# (share/timezone/Asia/Dushanbe и т.п.) тоже могут отсеяться. Явно включаем
# через includes=["**/*"] и исключаем только Python-исходники.
datas += collect_data_files(
    "pgserver",
    includes=["**/*"],
    excludes=["**/*.py", "**/*.pyc", "**/__pycache__/**"],
)

# Django + DRF + Unfold — их templates/static
for pkg in ("django", "rest_framework", "unfold"):
    try:
        datas += collect_data_files(pkg, includes=["**/*.html", "**/*.txt", "**/*.po", "**/*.mo", "**/*.json"])
    except Exception:
        pass

# ── hiddenimports: всё что Django может импортировать динамически ─────────
hiddenimports: list[str] = [
    # PySide6
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtNetwork",
    "PySide6.QtSvg",
    # POS deps
    "requests",
    "sseclient",
    "segno",
    # keyring backends
    "keyring.backends.Windows",
    "keyring.backends.SecretService",
    "keyring.backends.macOS",
    # Embedded backend Python deps
    "pgserver",
    "waitress",
    "psycopg",
    "psycopg.adapters",
    "psycopg_binary",
    "django",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "django_filters",
    "corsheaders",
    "unfold",
    "environ",
    "openpyxl",
    "bcrypt",
    "PIL",
]

# Все наши Django apps (apps.*) — submodule scan чтобы migrations попали тоже
try:
    import sys
    sys.path.insert(0, str(BACKEND_DIR))
    for app in ("apps", "config", "common"):
        try:
            hiddenimports += collect_submodules(app)
        except Exception:
            pass
    sys.path.remove(str(BACKEND_DIR))
except Exception:
    pass

a = Analysis(
    ["pos/__main__.py"],
    pathex=[str(ROOT), str(BACKEND_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "test", "unittest", "pytest"],
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
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
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
