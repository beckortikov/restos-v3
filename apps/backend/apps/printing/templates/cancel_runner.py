"""Шаблон бегунка отмены — печать на станционный принтер кухни/бара.

Печатается когда уже принятая в работу позиция отменяется. Повар видит
крупную надпись «ОТМЕНА: Плов ×2», стол, причину.
"""
from .receipt import (  # noqa: F401  (re-exported)
    DEFAULT_WIDTH,
    _hr,
    _is_zero,
    width_for,
)


def _resolve_width(data: dict, override: int | None) -> int:
    if override is not None:
        return override
    return width_for(data.get("printer_paper_size"))


def render_text_preview(data: dict, width: int | None = None) -> str:
    w = _resolve_width(data, width)
    r = data.get("restaurant", {})
    o = data.get("order", {})
    item = data.get("item", {})

    lines: list[str] = []
    lines.append(r.get("name", "").center(w))
    lines.append(_hr(w))
    # Очень крупная плашка
    lines.append("***  ОТМЕНА  ***".center(w))
    lines.append(_hr(w))
    lines.append(
        f"{item.get('name', '?')} ×{item.get('qty', 1)}"
    )
    if item.get("note"):
        lines.append(f"  ! {item['note']}")
    lines.append("")
    if o.get("table"):
        lines.append(f"Стол: {o['table']}")
    if o.get("waiter"):
        lines.append(f"Официант: {o['waiter']}")
    if data.get("cancelled_by"):
        lines.append(f"Отменил: {data['cancelled_by']}")
    reason = (data.get("reason") or "").strip()
    if reason:
        lines.append(f"Причина: {reason}")
    lines.append(_hr(w))
    lines.append("")
    return "\n".join(lines) + "\n"


def render_escpos(printer, data: dict, width: int | None = None) -> None:
    w = _resolve_width(data, width)
    r = data.get("restaurant", {})
    o = data.get("order", {})
    item = data.get("item", {})

    printer.set(align="center", bold=True, double_width=True, double_height=True)
    printer.text(f"{r.get('name', '')}\n")
    printer.set(align="center", bold=False, double_width=False, double_height=False)
    printer.text(_hr(w) + "\n")

    # «ОТМЕНА» — двойная высота/ширина, жирный, красным если поддерживается.
    printer.set(align="center", bold=True, double_width=True, double_height=True)
    printer.text("ОТМЕНА\n")
    printer.set(align="center", bold=False, double_width=False, double_height=False)
    printer.text(_hr(w) + "\n")

    printer.set(align="left", bold=True, double_width=False, double_height=False)
    printer.text(f"{item.get('name', '?')} ×{item.get('qty', 1)}\n")
    printer.set(bold=False)
    if item.get("note"):
        printer.text(f"  ! {item['note']}\n")
    printer.text("\n")
    if o.get("table"):
        printer.text(f"Стол: {o['table']}\n")
    if o.get("waiter"):
        printer.text(f"Официант: {o['waiter']}\n")
    if data.get("cancelled_by"):
        printer.text(f"Отменил: {data['cancelled_by']}\n")
    reason = (data.get("reason") or "").strip()
    if reason:
        printer.text(f"Причина: {reason}\n")
    printer.text(_hr(w) + "\n\n")
