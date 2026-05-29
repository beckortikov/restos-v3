from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from common.exceptions import BusinessError

from .models import CashShift, CashShiftOperation, ShiftStatus


def get_current_shift(restaurant) -> CashShift | None:
    """Текущая открытая смена ресторана (одна на ресторан в момент времени)."""
    return CashShift.objects.filter(
        restaurant=restaurant, status=ShiftStatus.OPEN
    ).first()


@transaction.atomic
def open_shift(*, restaurant, cashier, opening_balance: Decimal) -> CashShift:
    """Открыть смену. Ошибка SHIFT_ALREADY_OPEN если есть открытая."""
    if CashShift.objects.select_for_update().filter(
        restaurant=restaurant, status=ShiftStatus.OPEN
    ).exists():
        raise BusinessError(
            "SHIFT_ALREADY_OPEN",
            "Смена уже открыта. Сначала закройте текущую.",
            409,
        )

    last_no = (
        CashShift.objects.filter(restaurant=restaurant)
        .order_by("-number")
        .values_list("number", flat=True)
        .first()
    ) or 0

    shift = CashShift.objects.create(
        restaurant=restaurant,
        cashier=cashier,
        number=int(last_no) + 1,
        opening_balance=opening_balance,
        status=ShiftStatus.OPEN,
        opened_at=timezone.now(),
    )
    from apps.audit.services import audit_log
    audit_log(
        cashier, "shift_open", target=shift,
        payload={
            "number": shift.number,
            "opening_balance": str(opening_balance),
        },
    )
    return shift


@transaction.atomic
def close_shift(
    *, shift_id: int, restaurant, actual_balance: Decimal, note: str = ""
) -> CashShift:
    try:
        shift = CashShift.objects.select_for_update().get(
            id=shift_id, restaurant=restaurant
        )
    except CashShift.DoesNotExist as exc:
        raise BusinessError("SHIFT_NOT_FOUND", "Смена не найдена", 404) from exc

    if shift.status == ShiftStatus.CLOSED:
        raise BusinessError("SHIFT_ALREADY_CLOSED", "Смена уже закрыта", 409)

    expected = shift.expected_balance  # property — считает в SQL/Python

    shift.status = ShiftStatus.CLOSED
    shift.actual_balance = actual_balance
    shift.closing_balance = expected  # сохраняем расчётный остаток
    shift.closed_at = timezone.now()
    if note:
        shift.note = note
    shift.save(
        update_fields=[
            "status", "actual_balance", "closing_balance", "closed_at", "note",
        ]
    )
    from apps.audit.services import audit_log
    audit_log(
        shift.cashier, "shift_close", target=shift,
        payload={
            "number": shift.number,
            "actual_balance": str(actual_balance),
            "expected_balance": str(expected),
            "discrepancy": str(actual_balance - expected),
            "note": note or "",
        },
    )
    return shift


def build_shift_report(shift: CashShift) -> dict:
    """Полный отчёт по смене для frame 15-16:
    - kpi (выручка/чек/гости)
    - sales_by_payment (cash/card/transfer)
    - sales_by_category (qty + total)
    - sales_by_order_type (hall/takeaway/delivery)
    - sales_by_waiter (orders_count, total, avg_check)
    - cash_box (opening + revenue, expected, actual, discrepancy)
    """
    from apps.orders.models import Order, OrderItem, OrderStatus, OrderType, PaymentMethod

    done_qs = Order.objects.filter(shift=shift, status=OrderStatus.DONE)

    # KPI
    revenue = sum((o.total for o in done_qs), Decimal("0.00"))
    orders_count = done_qs.count()
    guests = sum((o.guests_count for o in done_qs), 0)
    avg_check = (revenue / orders_count) if orders_count else Decimal("0.00")
    avg_per_guest = (revenue / guests) if guests else Decimal("0.00")

    # By payment — Phase 4 multi-payment: суммируем через OrderPayment.amount.
    # Если у заказа нет OrderPayment-ов (legacy / pre-Phase4), fallback на
    # Order.payment_method + Order.total.
    from apps.orders.models import OrderPayment

    by_payment: dict[str, Decimal] = {pm: Decimal("0.00") for pm in PaymentMethod.values}
    op_qs = OrderPayment.objects.filter(order__in=done_qs)
    orders_with_payments = set(op_qs.values_list("order_id", flat=True))
    for op in op_qs:
        if op.method in by_payment:
            by_payment[op.method] += op.amount
    for o in done_qs:
        if o.id in orders_with_payments:
            continue
        if o.payment_method in by_payment:
            by_payment[o.payment_method] += o.total

    # By order_type
    by_type: dict[str, dict] = {
        ot: {"orders_count": 0, "total": Decimal("0.00")}
        for ot in OrderType.values
    }
    for o in done_qs:
        bucket = by_type.setdefault(
            o.order_type, {"orders_count": 0, "total": Decimal("0.00")}
        )
        bucket["orders_count"] += 1
        bucket["total"] += o.total

    # By category
    items_qs = OrderItem.objects.filter(
        order__in=done_qs, cancelled_at__isnull=True
    ).select_related("menu_item__category")
    by_cat: dict[int, dict] = {}
    for it in items_qs:
        cat = it.menu_item.category
        bucket = by_cat.setdefault(
            cat.id,
            {"id": cat.id, "name": cat.name, "qty": 0, "total": Decimal("0.00")},
        )
        bucket["qty"] += it.qty
        bucket["total"] += it.subtotal
    sales_by_category = sorted(
        by_cat.values(), key=lambda r: r["total"], reverse=True
    )

    # By waiter
    by_waiter: dict[int, dict] = {}
    for o in done_qs.select_related("waiter"):
        w = o.waiter
        bucket = by_waiter.setdefault(
            w.id,
            {
                "id": w.id,
                "name": w.full_name,
                "orders_count": 0,
                "total": Decimal("0.00"),
            },
        )
        bucket["orders_count"] += 1
        bucket["total"] += o.total
    waiter_rows: list[dict] = []
    for r in by_waiter.values():
        n = r["orders_count"]
        r["avg_check"] = (r["total"] / n) if n else Decimal("0.00")
        waiter_rows.append(r)
    waiter_rows.sort(key=lambda r: r["total"], reverse=True)

    # Дельты к предыдущей смене того же ресторана (CLOSED, не текущая).
    prev_shift = (
        CashShift.objects
        .filter(restaurant=shift.restaurant, status=ShiftStatus.CLOSED)
        .exclude(id=shift.id)
        .order_by("-closed_at", "-id")
        .first()
    )
    prev_kpi: dict = {}
    if prev_shift is not None:
        prev_done = Order.objects.filter(shift=prev_shift, status=OrderStatus.DONE)
        p_revenue = sum((o.total for o in prev_done), Decimal("0.00"))
        p_orders = prev_done.count()
        p_guests = sum((o.guests_count for o in prev_done), 0)
        p_avg = (p_revenue / p_orders) if p_orders else Decimal("0.00")
        prev_kpi = {
            "shift_number": prev_shift.number,
            "revenue": str(p_revenue),
            "orders_count": p_orders,
            "guests_count": p_guests,
            "average_check": str(p_avg.quantize(Decimal("0.01"))),
        }

    def _pct(curr, prev) -> str | None:
        try:
            curr_d = Decimal(str(curr))
            prev_d = Decimal(str(prev))
        except Exception:
            return None
        if prev_d == 0:
            return None
        return str(
            ((curr_d - prev_d) / prev_d * 100).quantize(Decimal("0.1"))
        )

    deltas: dict = {}
    if prev_kpi:
        deltas = {
            "revenue_pct": _pct(revenue, prev_kpi["revenue"]),
            "orders_pct": _pct(orders_count, prev_kpi["orders_count"]),
            "guests_pct": _pct(guests, prev_kpi["guests_count"]),
            "average_check_pct": _pct(avg_check, prev_kpi["average_check"]),
        }

    return {
        "shift": {
            "id": shift.id,
            "number": shift.number,
            "status": shift.status,
            "opened_at": shift.opened_at.isoformat() if shift.opened_at else None,
            "closed_at": shift.closed_at.isoformat() if shift.closed_at else None,
            "cashier_name": shift.cashier.full_name,
            "opening_balance": str(shift.opening_balance),
            "cash_in_total": str(shift.cash_in_total),
            "cash_out_total": str(shift.cash_out_total),
            "actual_balance": (
                str(shift.actual_balance) if shift.actual_balance is not None else None
            ),
            "expected_balance": str(shift.expected_balance),
            "discrepancy": (
                str(shift.discrepancy) if shift.discrepancy is not None else None
            ),
        },
        "cash_operations": [
            {
                "id": op.id,
                "kind": op.kind,
                "amount": str(op.amount),
                "reason": op.reason,
                "created_at": op.created_at.isoformat(),
            }
            for op in shift.operations.all().order_by("created_at")
        ],
        "kpi": {
            "revenue": str(revenue),
            "orders_count": orders_count,
            "guests_count": guests,
            "average_check": str(avg_check.quantize(Decimal("0.01"))),
            "average_per_guest": str(avg_per_guest.quantize(Decimal("0.01"))),
        },
        "previous_shift": prev_kpi,
        "deltas": deltas,
        "sales_by_payment": {
            pm: str(amount) for pm, amount in by_payment.items()
        },
        "sales_by_order_type": [
            {"type": ot, "orders_count": d["orders_count"], "total": str(d["total"])}
            for ot, d in by_type.items()
        ],
        "sales_by_category": [
            {"id": r["id"], "name": r["name"], "qty": r["qty"], "total": str(r["total"])}
            for r in sales_by_category
        ],
        "sales_by_waiter": [
            {
                "id": r["id"],
                "name": r["name"],
                "orders_count": r["orders_count"],
                "total": str(r["total"]),
                "avg_check": str(r["avg_check"].quantize(Decimal("0.01"))),
            }
            for r in waiter_rows
        ],
    }


def print_z_report(shift: CashShift):
    """Создаёт PrintJob (kind=z_report) с полным отчётом по смене.

    Печатает на cashier-принтере (через resolve_printer system_code='cashier').
    Если принтера нет — job создан с printer=None, виртуальный fallback запишет
    в PRINTER_OUTPUT_DIR. Audit-лог пишется тоже.
    """
    from apps.audit.services import audit_log
    from apps.printing.models import PrintJob, PrintJobKind
    from apps.printing.services import WORKER_EVENT, resolve_printer

    report = build_shift_report(shift)
    payload = {
        "restaurant": {
            "name": shift.restaurant.name,
            "address": shift.restaurant.address,
            "phone": shift.restaurant.phone,
            "currency": shift.restaurant.currency,
        },
        "shift": report["shift"],
        "kpi": report["kpi"],
        "sales_by_payment": report["sales_by_payment"],
        "sales_by_order_type": report["sales_by_order_type"],
        "sales_by_category": report["sales_by_category"],
    }
    printer = resolve_printer(shift.restaurant, "guest_receipt")
    job = PrintJob.objects.create(
        restaurant=shift.restaurant,
        printer=printer,
        order=None,
        kind=PrintJobKind.Z_REPORT,
        payload=payload,
        scheduled_at=timezone.now(),
    )
    WORKER_EVENT.set()
    audit_log(
        shift.cashier, "z_report_printed", target=shift,
        payload={"shift_number": shift.number, "job_id": job.id},
    )
    return job


def print_x_report(shift: CashShift, *, user=None):
    """X-отчёт — промежуточный снимок открытой смены.

    В отличие от Z-отчёта (печатается при закрытии смены), X-отчёт можно
    печатать многократно во время смены — для контроля выручки/кассы.
    Status смены не меняется.
    """
    from apps.audit.services import audit_log
    from apps.printing.models import PrintJob, PrintJobKind
    from apps.printing.services import WORKER_EVENT, resolve_printer

    if shift.status != ShiftStatus.OPEN:
        raise BusinessError(
            "INVALID_TRANSITION",
            "X-отчёт доступен только для открытой смены",
            422,
        )

    report = build_shift_report(shift)
    payload = {
        "restaurant": {
            "name": shift.restaurant.name,
            "address": shift.restaurant.address,
            "phone": shift.restaurant.phone,
            "currency": shift.restaurant.currency,
        },
        "shift": report["shift"],
        "kpi": report["kpi"],
        "sales_by_payment": report["sales_by_payment"],
        "sales_by_order_type": report["sales_by_order_type"],
        "sales_by_category": report["sales_by_category"],
        "is_x_report": True,
    }
    printer = resolve_printer(shift.restaurant, "guest_receipt")
    job = PrintJob.objects.create(
        restaurant=shift.restaurant,
        printer=printer,
        order=None,
        kind=PrintJobKind.X_REPORT,
        payload=payload,
        scheduled_at=timezone.now(),
    )
    WORKER_EVENT.set()
    audit_log(
        user or shift.cashier, "x_report_printed", target=shift,
        payload={"shift_number": shift.number, "job_id": job.id},
    )
    return job


@transaction.atomic
def add_cash_operation(
    *, shift: CashShift, kind: str, amount: Decimal, reason: str, user
) -> CashShiftOperation:
    if shift.status != ShiftStatus.OPEN:
        raise BusinessError(
            "INVALID_TRANSITION", "Операции возможны только в открытой смене", 422
        )
    if amount <= 0:
        raise BusinessError(
            "INVALID_TRANSITION", "Сумма должна быть положительной", 422
        )
    op = CashShiftOperation.objects.create(
        shift=shift, kind=kind, amount=amount, reason=reason, created_by=user
    )
    from apps.audit.services import audit_log
    audit_log(
        user, kind, target=op,
        payload={
            "shift_id": shift.id,
            "shift_number": shift.number,
            "amount": str(amount),
            "reason": reason or "",
        },
    )
    return op
