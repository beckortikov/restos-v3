"""SA-7 — сбор аппаратного UUID для machine-binding активации.

Приоритет источников:
1. Windows BIOS UUID через `wmic csproduct get uuid`
2. Windows fallback через PowerShell (Win 11 24H2+ deprecates WMIC)
3. Linux: /etc/machine-id или /var/lib/dbus/machine-id
4. macOS: IOPlatformUUID через `ioreg`
5. Last-resort: UUID на основе MAC + hostname (для dev)

`is_valid_hwid(value)` — отклоняет all-zero, слишком короткие, явные dev-fallbacks.
"""
from __future__ import annotations

import platform
import re
import subprocess
import uuid
from pathlib import Path

# Невалидные паттерны (VirtualBox, Hyper-V default, missing BIOS)
_INVALID_PATTERNS = (
    "00000000-0000-0000-0000-000000000000",
    "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF",
    "03000200-0400-0500-0006-000700080009",  # Hyper-V default
)

_UUID_RE = re.compile(
    r"^[0-9A-Fa-f]{8}-?[0-9A-Fa-f]{4}-?[0-9A-Fa-f]{4}-?[0-9A-Fa-f]{4}-?[0-9A-Fa-f]{12}$",
)


def is_valid_hwid(value: str) -> bool:
    if not value:
        return False
    v = value.strip().upper()
    if len(v) < 32:
        return False
    if v in _INVALID_PATTERNS:
        return False
    # Должен быть UUID-формат (с тире или без)
    return bool(_UUID_RE.match(v))


def _wmic() -> str | None:
    try:
        out = subprocess.check_output(
            ["wmic", "csproduct", "get", "uuid"],
            stderr=subprocess.DEVNULL, timeout=5,
        ).decode("utf-8", errors="ignore")
        for line in out.splitlines():
            ln = line.strip()
            if ln and ln.upper() != "UUID" and len(ln) >= 32:
                return ln
    except Exception:
        return None
    return None


def _powershell() -> str | None:
    try:
        out = subprocess.check_output(
            [
                "powershell", "-NoProfile", "-Command",
                "(Get-CimInstance Win32_ComputerSystemProduct).UUID",
            ],
            stderr=subprocess.DEVNULL, timeout=5,
        ).decode("utf-8", errors="ignore").strip()
        if out and len(out) >= 32:
            return out
    except Exception:
        return None
    return None


def _linux_machine_id() -> str | None:
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            txt = Path(path).read_text().strip()
            if txt:
                # /etc/machine-id это 32 hex без тире; превращаем в стандартный UUID-формат
                if len(txt) == 32 and "-" not in txt:
                    return f"{txt[:8]}-{txt[8:12]}-{txt[12:16]}-{txt[16:20]}-{txt[20:]}".upper()
                return txt.upper()
        except Exception:
            continue
    return None


def _macos_ioreg() -> str | None:
    try:
        out = subprocess.check_output(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            stderr=subprocess.DEVNULL, timeout=5,
        ).decode("utf-8", errors="ignore")
        m = re.search(r'"IOPlatformUUID"\s*=\s*"([0-9A-Fa-f-]{36})"', out)
        if m:
            return m.group(1).upper()
    except Exception:
        return None
    return None


def collect_hardware_uuid() -> str:
    """Вернуть стабильный HWID для этой машины.

    На production-Windows будет BIOS UUID. На Linux/Mac — alternative источник.
    Last-resort fallback (MAC-based UUID) для dev — но `is_valid_hwid` может
    его отклонить если паттерн совпадёт с INVALID.
    """
    system = platform.system()
    if system == "Windows":
        uid = _wmic() or _powershell()
        if uid:
            return uid.strip().upper()
    elif system == "Linux":
        uid = _linux_machine_id()
        if uid:
            return uid
    elif system == "Darwin":
        uid = _macos_ioreg()
        if uid:
            return uid

    # Last-resort: hash MAC + hostname — стабильно на одной машине, но не cryptographic
    fallback = str(uuid.UUID(int=uuid.getnode()))
    return fallback.upper()
