"""Phase 8E — единые форматтеры чисел для UI.

`fmt_qty(val, unit="")` — адаптивный формат для количеств / порогов / yield:
- 5      → "5"
- 4.5    → "4.5"
- 4.55   → "4.55"
- 4.555  → "4.56" (округление до 2 знаков)
Если передан unit — добавляется через пробел.

`fmt_money(val)` — деньги: всегда 2 знака после запятой ("12.00", "0.50").
"""
from __future__ import annotations


def fmt_qty(val, unit: str = "") -> str:
    """До 2 знаков после запятой, без trailing нулей."""
    try:
        v = float(val if val is not None else 0)
    except (TypeError, ValueError):
        v = 0.0
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    if not s or s == "-":
        s = "0"
    return f"{s} {unit}".strip() if unit else s


def fmt_money(val) -> str:
    """Деньги: всегда 2 знака после запятой."""
    try:
        v = float(val if val is not None else 0)
    except (TypeError, ValueError):
        v = 0.0
    return f"{v:.2f}"
