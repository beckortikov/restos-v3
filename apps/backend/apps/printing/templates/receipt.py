"""Шаблон чека — гостевой / пре-чек.

Ширина строки зависит от paper_size принтера:
- 58мм → 32 символа (Font A)
- 76мм → 42 символа
- 80мм → 48 символов

Caller передаёт `width` явно ИЛИ через data['printer_paper_size'] (выставляет
escpos_sender). Дефолт — 32 (для backwards compat в snapshot-тестах).
"""
from datetime import datetime, timedelta
from datetime import timezone as tz

DUSHANBE = tz(timedelta(hours=5))

WIDTH_BY_PAPER: dict[str, int] = {
    "58mm": 32,
    "76mm": 42,
    "80mm": 48,
}
DEFAULT_WIDTH = 32
WIDTH = DEFAULT_WIDTH  # backwards-compat для импорта в старых тестах

PM_RU = {
    "cash": "Наличные",
    "card": "Карта",
    "transfer": "Перевод",
}


def width_for(paper_size: str | None) -> int:
    return WIDTH_BY_PAPER.get(paper_size or "", DEFAULT_WIDTH)


def _hr(width: int = DEFAULT_WIDTH) -> str:
    return "─" * width


def _format_closed(iso: str) -> str:
    if not iso:
        return ""
    return datetime.fromisoformat(iso).astimezone(DUSHANBE).strftime("%d.%m.%Y %H:%M")


def _resolve_width(data: dict, override: int | None) -> int:
    if override is not None:
        return override
    return width_for(data.get("printer_paper_size"))


def _is_zero(s) -> bool:
    return s in (None, "", "0", "0.00", "0.0")


def render_text_preview(data: dict, width: int | None = None) -> str:
    """Текстовый превью чека шириной width символов.

    Если width не передан — берётся из data.get('printer_paper_size'),
    иначе DEFAULT_WIDTH (32 — 58мм).
    """
    w = _resolve_width(data, width)
    r = data["restaurant"]
    o = data["order"]
    items = data["items"]

    lines: list[str] = []
    lines.append(r["name"].center(w))
    if r.get("address"):
        lines.append(r["address"].center(w))
    if r.get("phone"):
        lines.append(f"тел. {r['phone']}".center(w))
    # Доп. строки шапки (ИНН, лицензия и т.д. — настраиваются в Settings)
    extra = r.get("receipt_header_extra") or ""
    for line in extra.splitlines():
        line = line.strip()
        if line:
            lines.append(line.center(w))
    # Маркер копии (для receipt_copies > 1): «КОПИЯ 2 из 2».
    copy = data.get("copy")
    if copy:
        lines.append(
            f"КОПИЯ {copy.get('index', 1)} из {copy.get('total', 1)}".center(w)
        )
    # Маркер дубликата (повторная печать из истории).
    if data.get("duplicate"):
        lines.append("*** ДУБЛИКАТ ***".center(w))
    lines.append(_hr(w))

    closed = _format_closed(o.get("closed_at", ""))
    lines.append(
        f"Чек № {o['id']}".ljust(max(0, w - len(closed))) + closed
    )
    lines.append(
        f"Стол: {o['table']}".ljust(max(0, w - 12)) + f"Гостей: {o['guests']}"
    )
    lines.append(f"Официант: {o['waiter']}")
    if o.get("cashier"):
        lines.append(f"Кассир:   {o['cashier']}")
    lines.append(_hr(w))

    for it in items:
        lines.append(it["name"])
        for m in it.get("modifiers") or []:
            delta = m.get("price_delta", "0")
            try:
                from decimal import Decimal as _D
                d = _D(str(delta))
            except Exception:
                d = None
            if d is None or d == 0:
                lines.append(f"  + {m['name']}")
            else:
                sign = "+" if d > 0 else "−"
                lines.append(f"  + {m['name']} ({sign}{abs(d)})")
        if it.get("note"):
            lines.append(f"  * {it['note']}")
        right = f"{it['qty']} x {it['price']} = {it['subtotal']}"
        lines.append(("  " + right).rjust(w))

    lines.append(_hr(w))

    cur = r.get("currency", "")
    subtotal = o.get("subtotal")
    if not _is_zero(subtotal):
        lines.append(f"Подитог: {subtotal} {cur}".rjust(w))
    discount_amount = o.get("discount_amount")
    if not _is_zero(discount_amount):
        name = o.get("discount_name") or "Скидка"
        lines.append(f"{name}: −{discount_amount} {cur}".rjust(w))
    service_amount = o.get("service_charge_amount")
    if not _is_zero(service_amount):
        pct = o.get("service_charge_pct", "")
        label = (
            f"Обслуживание ({pct}%)" if not _is_zero(pct)
            else "Обслуживание"
        )
        lines.append(f"{label}: +{service_amount} {cur}".rjust(w))
    tip_amount = o.get("tip_amount")
    if not _is_zero(tip_amount):
        lines.append(f"Чаевые: +{tip_amount} {cur}".rjust(w))

    total = f"ИТОГО: {o['total']} {cur}"
    lines.append(total.rjust(w))
    # Multi-payment breakdown (Phase 4): если payments=[{method, amount}, ...]
    # длиной > 1 — печатаем каждую строку отдельно. Для single — старая «Оплата: X».
    payments = o.get("payments") or []
    if len(payments) > 1:
        for p in payments:
            label = PM_RU.get(p.get("method", ""), p.get("method", ""))
            lines.append(f"  {label}: {p['amount']} {cur}".rjust(w))
    else:
        pm = PM_RU.get(o.get("payment_method", ""), o.get("payment_method", ""))
        lines.append(f"Оплата: {pm}".rjust(w))
    lines.append(_hr(w))
    footer = r.get("receipt_footer") or "Спасибо за визит!"
    for line in footer.splitlines():
        line = line.strip()
        if line:
            lines.append(line.center(w))
    lines.append("")
    return "\n".join(lines) + "\n"


def render_escpos(printer, data: dict, width: int | None = None) -> None:
    """Рендер чека на ESC/POS-принтер."""
    w = _resolve_width(data, width)
    r = data["restaurant"]
    o = data["order"]

    printer.set(align="center", bold=True, double_width=True, double_height=True)
    printer.text(f"{r['name']}\n")
    printer.set(align="center", bold=False, double_width=False, double_height=False)
    if r.get("address"):
        printer.text(f"{r['address']}\n")
    if r.get("phone"):
        printer.text(f"тел. {r['phone']}\n")
    extra = r.get("receipt_header_extra") or ""
    for line in extra.splitlines():
        line = line.strip()
        if line:
            printer.text(line + "\n")
    copy = data.get("copy")
    if copy:
        printer.text(
            f"КОПИЯ {copy.get('index', 1)} из {copy.get('total', 1)}\n"
        )
    if data.get("duplicate"):
        printer.set(bold=True)
        printer.text("*** ДУБЛИКАТ ***\n")
        printer.set(bold=False)
    printer.text(_hr(w) + "\n")

    printer.set(align="left")
    closed = _format_closed(o.get("closed_at", ""))
    printer.text(
        f"Чек № {o['id']}".ljust(max(0, w - len(closed))) + closed + "\n"
    )
    printer.text(
        f"Стол: {o['table']}".ljust(max(0, w - 12))
        + f"Гостей: {o['guests']}\n"
    )
    printer.text(f"Официант: {o['waiter']}\n")
    if o.get("cashier"):
        printer.text(f"Кассир:   {o['cashier']}\n")
    printer.text(_hr(w) + "\n")

    for it in data["items"]:
        printer.text(f"{it['name']}\n")
        for m in it.get("modifiers") or []:
            delta = m.get("price_delta", "0")
            try:
                from decimal import Decimal as _D
                d = _D(str(delta))
            except Exception:
                d = None
            if d is None or d == 0:
                printer.text(f"  + {m['name']}\n")
            else:
                sign = "+" if d > 0 else "−"
                printer.text(f"  + {m['name']} ({sign}{abs(d)})\n")
        if it.get("note"):
            printer.text(f"  * {it['note']}\n")
        right = f"{it['qty']} x {it['price']} = {it['subtotal']}"
        printer.text(("  " + right).rjust(w) + "\n")

    printer.text(_hr(w) + "\n")

    cur = r.get("currency", "")
    subtotal = o.get("subtotal")
    if not _is_zero(subtotal):
        printer.text(f"Подитог: {subtotal} {cur}".rjust(w) + "\n")
    discount_amount = o.get("discount_amount")
    if not _is_zero(discount_amount):
        name = o.get("discount_name") or "Скидка"
        printer.text(
            f"{name}: −{discount_amount} {cur}".rjust(w) + "\n"
        )
    service_amount = o.get("service_charge_amount")
    if not _is_zero(service_amount):
        pct = o.get("service_charge_pct", "")
        label = (
            f"Обслуживание ({pct}%)" if not _is_zero(pct)
            else "Обслуживание"
        )
        printer.text(
            f"{label}: +{service_amount} {cur}".rjust(w) + "\n"
        )
    tip_amount = o.get("tip_amount")
    if not _is_zero(tip_amount):
        printer.text(f"Чаевые: +{tip_amount} {cur}".rjust(w) + "\n")
    printer.set(bold=True)
    total = f"ИТОГО: {o['total']} {cur}"
    printer.text(total.rjust(w) + "\n")
    printer.set(bold=False)
    payments = o.get("payments") or []
    if len(payments) > 1:
        for p in payments:
            label = PM_RU.get(p.get("method", ""), p.get("method", ""))
            printer.text(f"  {label}: {p['amount']} {cur}".rjust(w) + "\n")
    else:
        pm = PM_RU.get(o.get("payment_method", ""), o.get("payment_method", ""))
        printer.text(f"Оплата: {pm}".rjust(w) + "\n")
    printer.text(_hr(w) + "\n")
    printer.set(align="center")
    footer = r.get("receipt_footer") or "Спасибо за визит!"
    for line in footer.splitlines():
        line = line.strip()
        if line:
            printer.text(line + "\n")
    printer.text("\n\n")
