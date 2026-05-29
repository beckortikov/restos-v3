"""Шаблон бегунка готовности — печать на станционный принтер.

Печатается когда повар переводит позицию в READY. Официант видит крупный
«ГОТОВО: Плов ×2», стол, чтобы быстро забрать блюдо к гостю.
"""
from .receipt import _hr, width_for


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
    lines.append("***  ГОТОВО  ***".center(w))
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
    if data.get("cooked_by"):
        lines.append(f"Повар: {data['cooked_by']}")
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

    # «ГОТОВО» — крупная плашка.
    printer.set(align="center", bold=True, double_width=True, double_height=True)
    printer.text("ГОТОВО\n")
    printer.set(align="center", bold=False, double_width=False, double_height=False)
    printer.text(_hr(w) + "\n")

    printer.set(align="left", bold=True)
    printer.text(f"{item.get('name', '?')} ×{item.get('qty', 1)}\n")
    printer.set(bold=False)
    if item.get("note"):
        printer.text(f"  ! {item['note']}\n")
    printer.text("\n")
    if o.get("table"):
        printer.text(f"Стол: {o['table']}\n")
    if o.get("waiter"):
        printer.text(f"Официант: {o['waiter']}\n")
    if data.get("cooked_by"):
        printer.text(f"Повар: {data['cooked_by']}\n")
    printer.text(_hr(w) + "\n\n")
