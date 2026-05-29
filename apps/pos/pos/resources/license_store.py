"""SA-7 — local storage активационных данных POS.

Файл: %APPDATA%/RestOS/license.json на Windows,
      ~/.restos-pos/license.json на Linux/Mac.

Формат:
{
    "license_key": "ABC-DEF-GHI",
    "hardware_uuid": "4C4C4544-...",
    "activated_at": "ISO timestamp"
}
"""
from __future__ import annotations

import json
import os
import platform
from datetime import datetime
from pathlib import Path


def _store_dir() -> Path:
    if platform.system() == "Windows":
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "RestOS"
    return Path.home() / ".restos-pos"


def _store_file() -> Path:
    return _store_dir() / "license.json"


def load_license() -> dict | None:
    p = _store_file()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if not data.get("license_key") or not data.get("hardware_uuid"):
        return None
    return data


def save_license(license_key: str, hardware_uuid: str) -> None:
    d = _store_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = _store_file()
    payload = {
        "license_key": license_key,
        "hardware_uuid": hardware_uuid,
        "activated_at": datetime.utcnow().isoformat() + "Z",
    }
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    # Защита от случайной отдачи (но не криптография — клиентский файл всегда читаем юзером)
    try:
        p.chmod(0o600)
    except Exception:
        pass


def clear_license() -> None:
    p = _store_file()
    if p.exists():
        try:
            p.unlink()
        except Exception:
            pass


def get_machine_uuid() -> str | None:
    """Удобный шорткат: вернуть сохранённый HWID (или None если не активировано)."""
    data = load_license()
    return data.get("hardware_uuid") if data else None
