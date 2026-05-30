"""Self-update сервис для POS (SA-7 + Inno Setup).

Поток:
  check_for_update(current) → {version, installer_url, notes} | None
  download_installer(url, target_path, progress_cb) → bool
  apply_update(installer_path) → запускает setup.exe в silent-mode и закрывает POS

Активация (license.json в %APPDATA%/RestOS) переживёт переустановку —
Inno Setup ставит в %ProgramFiles%, а license-store отдельно.
"""
from __future__ import annotations

import logging
import os
import platform
import re
import subprocess
import sys
import tempfile
from typing import Callable

import requests

log = logging.getLogger(__name__)

GITHUB_REPO = "beckortikov/restos-v3"
RELEASE_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

VERSION_RE = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


def _parse_version(s: str) -> tuple[int, int, int]:
    m = VERSION_RE.search(s or "")
    if not m:
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def check_for_update(current_version: str, *, timeout: int = 10) -> dict | None:
    """Запрос к GitHub API. Возвращает dict если есть newer release, иначе None.

    dict: {
        "version": "v0.2.0",
        "installer_url": "https://.../RestOS-POS-Setup-0.2.0.exe",
        "zip_url": "https://.../RestOS-POS-v0.2.0-win64.zip",
        "notes": "release body...",
        "published_at": "ISO",
    }
    """
    try:
        r = requests.get(
            RELEASE_LATEST,
            headers={"Accept": "application/vnd.github+json"},
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        log.warning("update check failed: %s", exc)
        return None

    latest_tag = data.get("tag_name", "")
    if _parse_version(latest_tag) <= _parse_version(current_version):
        return None

    installer_url = ""
    zip_url = ""
    for asset in data.get("assets", []):
        name = (asset.get("name") or "").lower()
        url = asset.get("browser_download_url") or ""
        if name.endswith(".exe") and "setup" in name:
            installer_url = url
        elif name.endswith(".zip") and "win64" in name:
            zip_url = url
    if not installer_url and not zip_url:
        return None

    return {
        "version": latest_tag,
        "installer_url": installer_url,
        "zip_url": zip_url,
        "notes": data.get("body", "") or "",
        "published_at": data.get("published_at", ""),
        "html_url": data.get("html_url", ""),
    }


def download_installer(
    url: str,
    target_path: str | None = None,
    progress_cb: Callable[[int, int], None] | None = None,
    *,
    timeout: int = 60,
) -> str:
    """Скачать setup.exe в temp. Возвращает путь к файлу.

    progress_cb(bytes_done, total) — для прогресс-бара.
    """
    if target_path is None:
        target_path = os.path.join(
            tempfile.gettempdir(),
            os.path.basename(url) or "RestOS-POS-Setup.exe",
        )
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        with open(target_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if progress_cb is not None:
                    try:
                        progress_cb(done, total)
                    except Exception:
                        pass
    log.info("downloaded installer to %s (%d bytes)", target_path, done)
    return target_path


def apply_update(installer_path: str) -> None:
    """Запустить инсталлятор в тихом режиме и завершить POS.

    Inno Setup флаги:
      /VERYSILENT     — без UI и прогресс-окна
      /NORESTART      — не перезагружать ОС
      /SUPPRESSMSGBOXES — без диалогов «replace files?» (всё «yes»)
      /CLOSEAPPLICATIONS — если POS открыт, закрыть автоматически
      /RESTARTAPPLICATIONS — после установки запустить заново
    """
    if platform.system() != "Windows":
        raise RuntimeError(
            "Авто-обновление работает только на Windows. На Linux/Mac "
            "пересоберите вручную из репозитория."
        )
    if not os.path.exists(installer_path):
        raise FileNotFoundError(installer_path)

    log.info("launching installer: %s", installer_path)
    # DETACHED_PROCESS — installer переживёт закрытие POS.
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    subprocess.Popen(
        [
            installer_path,
            "/VERYSILENT",
            "/NORESTART",
            "/SUPPRESSMSGBOXES",
            "/CLOSEAPPLICATIONS",
            "/RESTARTAPPLICATIONS",
        ],
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )
    # POS должен закрыться — installer попросит /CLOSEAPPLICATIONS, но проще сами
    sys.exit(0)
