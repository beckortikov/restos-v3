"""Z-отчёт по смене — печать на cashier-принтере при закрытии смены.

Содержит:
- Заголовок (имя ресторана + «Z-ОТЧЁТ»)
- № смены, период (открытие → закрытие)
- KPI (выручка / заказы / гости / средний чек)
- Sales by payment (cash / card / transfer)
- Sales by category (top-N)
- Касса: opening + cash revenue → expected vs actual
- Подпись кассира + место для подписи

Ширина строки берётся из printer.paper_size (как в receipt-шаблоне).
"""
from datetime import datetime, timedelta
from datetime import timezone as tz

from .receipt import DEFAULT_WIDTH, WIDTH_BY_PAPER, _hr, _is_zero, width_for

DUSHANBE = tz(timedelta(hours=5))

PM_RU = {"cash": "Наличные", "card": "Карта", "transfer": "Перевод"}
TYPE_RU = {"hall": "В зале", "takeaway": "С собой", "delivery": "Доставка"}


def _resolve_width(data: dict, override: int | None) -> int:
    if override is not None:
        return override
    return width_for(data.get("printer_paper_size"))


def _fmt_dt(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).astimezone(DUSHANBE).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return iso[:16]


def _row(left: str, right: str, w: int) -> str:
    """left | right — ширина w, right выровнено вправо. Если переполнение —
    переносится правая часть на новую строку (rare)."""
    if len(left) + 1 + len(right) <= w:
        return left + " " * (w - len(left) - len(right)) + right
    return left + "\n" + right.rjust(w)


def render_text_preview(data: dict, width: int | None = None) -> str:
    w = _resolve_width(data, width)
    r = data["restaurant"]
    s = data["shift"]
    kpi = data.get("kpi", {})
    sbp = data.get("sales_by_payment", {})
    sbt = data.get("sales_by_order_type", [])
    sbc = data.get("sales_by_category", [])
    cur = r.get("currency", "")

    lines: list[str] = []
    lines.append(r["name"].center(w))
    if r.get("address"):
        lines.append(r["address"].center(w))
    lines.append(_hr(w))
    title = "X-ОТЧЁТ (промежуточный)" if data.get("is_x_report") else "Z-ОТЧЁТ"
    lines.append(title.center(w))
    lines.append(_hr(w))

    lines.append(_row(f"Смена №{s.get('number', '?')}", "", w))
    lines.append(f"Открытие: {_fmt_dt(s.get('opened_at'))}")
    closed = _fmt_dt(s.get("closed_at")) or "не закрыта"
    lines.append(f"Закрытие: {closed}")
    if s.get("cashier_name"):
        lines.append(f"Кассир:   {s['cashier_name']}")
    lines.append(_hr(w))

    # KPI
    lines.append("ИТОГИ".center(w))
    lines.append(_row("Выручка:", f"{kpi.get('revenue', '0.00')} {cur}", w))
    lines.append(_row("Заказов:", str(kpi.get("orders_count", 0)), w))
    lines.append(_row("Гостей:", str(kpi.get("guests_count", 0)), w))
    lines.append(
        _row("Ср. чек:", f"{kpi.get('average_check', '0.00')} {cur}", w)
    )
    if not _is_zero(kpi.get("average_per_guest")):
        lines.append(
            _row("На гостя:", f"{kpi.get('average_per_guest', '0.00')} {cur}", w)
        )
    lines.append(_hr(w))

    # Payments
    lines.append("ОПЛАТА".center(w))
    total_pay = 0.0
    for code, label in PM_RU.items():
        amt = sbp.get(code) or "0.00"
        if _is_zero(amt):
            continue
        lines.append(_row(label + ":", f"{amt} {cur}", w))
        try:
            total_pay += float(amt)
        except (TypeError, ValueError):
            pass
    lines.append(_row("Итого:", f"{total_pay:.2f} {cur}", w))
    lines.append(_hr(w))

    # Order types
    if sbt:
        lines.append("ПО ТИПУ ЗАКАЗА".center(w))
        for row in sbt:
            t = TYPE_RU.get(row.get("type", ""), row.get("type", ""))
            n = row.get("orders_count", 0)
            if n == 0:
                continue
            lines.append(
                _row(f"{t} ({n}):", f"{row.get('total', '0.00')} {cur}", w)
            )
        lines.append(_hr(w))

    # Categories (top-10)
    if sbc:
        lines.append("ПО КАТЕГОРИЯМ".center(w))
        for cat in sbc[:10]:
            qty = cat.get("qty", 0)
            label = f"{cat.get('name', '?')} ×{qty}"
            lines.append(_row(label, f"{cat.get('total', '0.00')} {cur}", w))
        lines.append(_hr(w))

    # Cash box
    lines.append("КАССА".center(w))
    lines.append(
        _row("Остаток на начало:", f"{s.get('opening_balance', '0.00')} {cur}", w)
    )
    cash_rev = sbp.get("cash") or "0.00"
    lines.append(_row("+ Наличная выручка:", f"{cash_rev} {cur}", w))
    cash_in = s.get("cash_in_total") or "0.00"
    cash_out = s.get("cash_out_total") or "0.00"
    if not _is_zero(cash_in):
        lines.append(_row("+ Внесения:", f"{cash_in} {cur}", w))
    if not _is_zero(cash_out):
        lines.append(_row("− Изъятия:", f"{cash_out} {cur}", w))
    lines.append(
        _row("Ожидаемо:", f"{s.get('expected_balance', '0.00')} {cur}", w)
    )
    if s.get("actual_balance"):
        lines.append(
            _row("Фактически:", f"{s['actual_balance']} {cur}", w)
        )
        if s.get("discrepancy") is not None:
            lines.append(_row("Расхождение:", f"{s['discrepancy']} {cur}", w))
    lines.append(_hr(w))

    lines.append("")
    lines.append("Подпись кассира: ____________".center(w))
    lines.append("")
    return "\n".join(lines) + "\n"


def render_escpos(printer, data: dict, width: int | None = None) -> None:
    w = _resolve_width(data, width)
    text = render_text_preview(data, width=w)

    # Заголовок крупным шрифтом, остальное — обычным
    lines = text.split("\n")
    header_done = False
    printer.set(align="center", bold=True, double_width=True, double_height=True)
    # Первая строка — имя ресторана, потом сразу включаем normal
    if lines:
        printer.text(lines[0] + "\n")
    printer.set(align="center", bold=False, double_width=False, double_height=False)
    title_centered = (
        "X-ОТЧЁТ (промежуточный)".center(w)
        if data.get("is_x_report") else "Z-ОТЧЁТ".center(w)
    )
    for line in lines[1:]:
        if line == title_centered:
            printer.set(align="center", bold=True, double_width=True, double_height=True)
            printer.text(line + "\n")
            printer.set(align="center", bold=False, double_width=False, double_height=False)
            continue
        printer.set(align="left")
        printer.text(line + "\n")
    printer.text("\n\n")
