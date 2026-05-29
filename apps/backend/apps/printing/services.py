import logging
import threading
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .escpos_sender import send_to_printer
from .models import Printer, PrintJob, PrintJobKind, PrintJobStatus

logger = logging.getLogger(__name__)


WORKER_EVENT = threading.Event()


def build_receipt_payload(order, split: dict | None = None) -> dict:
    """Замораживаем все нужные данные в JSON, чтобы retry не зависел от текущего состояния БД.

    split={"index": int, "count": int, "share": Decimal} — если задан, печатается
    как «Часть K из N: share TJS» (frame 6 «Разделить счёт»).
    """
    payload = {
        "restaurant": {
            "name": order.restaurant.name,
            "address": order.restaurant.address,
            "phone": order.restaurant.phone,
            "currency": order.restaurant.currency,
            "receipt_header_extra": order.restaurant.receipt_header_extra or "",
            "receipt_footer": order.restaurant.receipt_footer or "Спасибо за визит!",
        },
        "order": {
            "id": order.id,
            "table": order.table.name if order.table else "",
            "guests": order.guests_count,
            "waiter": order.waiter.full_name if order.waiter else "",
            "cashier": order.cashier.full_name if order.cashier else "",
            "closed_at": order.closed_at.isoformat() if order.closed_at else "",
            "payment_method": order.payment_method or "",
            "subtotal": str(order.subtotal),
            "service_charge_pct": str(order.service_charge_pct),
            "service_charge_amount": str(order.service_charge_amount),
            "discount_name": order.applied_discount.name if order.applied_discount else "",
            "discount_kind": order.discount_kind or "",
            "discount_value": str(order.discount_value),
            "discount_amount": str(order.discount_amount),
            "tip_amount": str(order.tip_amount or "0"),
            "total": str(order.total),
            "payments": [
                {"method": p.method, "amount": str(p.amount)}
                for p in order.payments.all().order_by("id")
            ],
        },
        "items": [
            {
                "name": it.name_at_order,
                "qty": it.qty,
                "price": str(it.price_at_order),
                "subtotal": str(it.subtotal),
                "note": it.note or "",
                "modifiers": [
                    {
                        "name": m.name_at_order,
                        "price_delta": str(m.price_delta_at_order),
                    }
                    for m in it.modifiers.all()
                ],
            }
            for it in order.items.all()
            if it.cancelled_at is None
        ],
    }
    if split is not None:
        payload["split"] = {
            "index": int(split.get("index", 1)),
            "count": int(split.get("count", 1)),
            "share": str(split.get("share", "0.00")),
        }
    return payload


def resolve_printer(restaurant, kind: str) -> "Printer | None":
    """Найти принтер для системного kind PrintJob через PrintStation.

    Логика:
    - guest_receipt / pre_bill / refund_receipt → station(system_code='cashier')
    - kitchen_order / bar_order → station(system_code='kitchen') как fallback
    - если у системной станции нет printer → default Printer ресторана
    - если default нет → первый active Printer
    - иначе None (кассир назначит вручную, retry).
    """
    from .models import PrintStation

    system_code = "cashier"
    if kind in {"kitchen_order", "bar_order"}:
        system_code = "kitchen"

    st = (
        PrintStation.objects
        .filter(restaurant=restaurant, system_code=system_code, is_active=True)
        .select_related("printer")
        .first()
    )
    if st and st.printer and st.printer.is_active:
        return st.printer

    return (
        Printer.objects.filter(
            restaurant=restaurant, is_active=True, is_default=True
        ).first()
        or Printer.objects.filter(restaurant=restaurant, is_active=True).first()
    )


def enqueue_kitchen_prints(order, *, only_unsent: bool = False) -> list[PrintJob]:
    """Печать заказа на кухню — по одному PrintJob на каждый PrintStation.

    Группирует активные позиции order.items по category.print_station.
    Если у категории нет станции — позиция в job не попадает (предполагается
    что это «готовое к выдаче» — например упакованные напитки).

    Если `only_unsent=True` — печатаем только позиции с `sent_to_kitchen_at IS NULL`
    (флоу «дозаказ → НА КУХНЮ»). После постановки в очередь — отмечаем
    `sent_to_kitchen_at = now()` у напечатанных позиций.

    Возвращает список созданных jobs (может быть пустой)."""
    from collections import defaultdict

    qs = order.items.filter(cancelled_at__isnull=True).select_related(
        "menu_item__category__print_station__printer"
    )
    if only_unsent:
        qs = qs.filter(sent_to_kitchen_at__isnull=True)

    by_station: dict[int, list] = defaultdict(list)
    sent_item_ids: list[int] = []
    for it in qs:
        # Маркируем как «прошёл через kitchen-broadcast» ВСЕ позиции,
        # даже те, у категории которых нет станции. Иначе кнопка «НА КУХНЮ»
        # на UI вечно показывает их как «новые» (хотя печатать нечего).
        sent_item_ids.append(it.id)
        cat = it.menu_item.category
        station = cat.print_station
        if station is None or not station.is_active:
            continue
        by_station[station.id].append((station, it))

    jobs: list[PrintJob] = []
    for sid, pairs in by_station.items():
        station = pairs[0][0]
        items = [pair[1] for pair in pairs]
        printer = (
            station.printer
            if station.printer and station.printer.is_active
            else None
        )
        if printer is None:
            # Fallback: kitchen system station printer
            printer = resolve_printer(order.restaurant, "kitchen_order")

        payload = {
            "restaurant": {
                "name": order.restaurant.name,
                "address": order.restaurant.address,
                "phone": order.restaurant.phone,
            },
            "station": station.name,
            "order": {
                "id": order.id,
                "table": order.table.name if order.table else "",
                "guests": order.guests_count,
                "waiter": order.waiter.full_name if order.waiter else "",
                "comment": order.comment or "",
            },
            "items": [
                {"name": it.name_at_order, "qty": it.qty, "note": it.note or ""}
                for it in items
            ],
        }
        job = PrintJob.objects.create(
            restaurant=order.restaurant,
            printer=printer,
            order=order,
            kind=PrintJobKind.KITCHEN_ORDER,
            payload=payload,
            scheduled_at=timezone.now(),
        )
        jobs.append(job)
    # Помечаем напечатанные позиции — чтобы повторный fire_kitchen не дублировал.
    if sent_item_ids:
        from apps.orders.models import OrderItem
        OrderItem.objects.filter(id__in=sent_item_ids).update(
            sent_to_kitchen_at=timezone.now(),
        )
    if jobs:
        WORKER_EVENT.set()
    return jobs


def enqueue_ready_runner(order_item, *, cooked_by=None) -> "PrintJob | None":
    """Печать «бегунка готовности» — официант видит, что блюдо готово к выдаче.

    Вызывается из kitchen-сервиса при переходе позиции в READY. Печатает
    на станционный принтер категории; fallback — kitchen system station;
    fallback — default printer. Если нет ни одного — пропускает (не падаем).
    """
    cat = order_item.menu_item.category if order_item.menu_item else None
    station = cat.print_station if cat else None
    printer = None
    if station is not None and station.is_active and station.printer:
        if station.printer.is_active:
            printer = station.printer
    if printer is None:
        printer = resolve_printer(order_item.order.restaurant, "kitchen_order")
    if printer is None:
        return None

    payload = {
        "restaurant": {"name": order_item.order.restaurant.name},
        "order": {
            "id": order_item.order.id,
            "table": (
                order_item.order.table.name if order_item.order.table else ""
            ),
            "waiter": (
                order_item.order.waiter.full_name if order_item.order.waiter else ""
            ),
        },
        "item": {
            "name": order_item.name_at_order,
            "qty": order_item.qty,
            "note": order_item.note or "",
        },
        "cooked_by": cooked_by.full_name if cooked_by else "",
    }
    job = PrintJob.objects.create(
        restaurant=order_item.order.restaurant,
        printer=printer,
        order=order_item.order,
        kind=PrintJobKind.READY_RUNNER,
        payload=payload,
        scheduled_at=timezone.now(),
    )
    WORKER_EVENT.set()
    return job


def enqueue_cancel_runner(order_item, *, cancelled_by, reason: str = "") -> "PrintJob | None":
    """Печать «бегунка отмены» на станционный принтер уже принятой в работу позиции.

    Вызывается из `cancel_item` ТОЛЬКО если позиция уже была COOKING/READY
    (т.е. кухня узнала о ней через kitchen_order). Если NEW — кухня не
    видела позицию, нет смысла её предупреждать об отмене.

    Печатает на станционный принтер категории; fallback — kitchen system station;
    fallback — default printer.
    """
    cat = order_item.menu_item.category
    station = cat.print_station
    printer = None
    if station is not None and station.is_active and station.printer:
        if station.printer.is_active:
            printer = station.printer
    if printer is None:
        printer = resolve_printer(order_item.order.restaurant, "kitchen_order")
    if printer is None:
        # Нет станционного принтера и нет fallback — пропускаем (не падаем).
        return None

    payload = {
        "restaurant": {
            "name": order_item.order.restaurant.name,
        },
        "order": {
            "id": order_item.order.id,
            "table": (
                order_item.order.table.name if order_item.order.table else ""
            ),
            "waiter": (
                order_item.order.waiter.full_name if order_item.order.waiter else ""
            ),
        },
        "item": {
            "name": order_item.name_at_order,
            "qty": order_item.qty,
            "note": order_item.note or "",
        },
        "cancelled_by": (
            cancelled_by.full_name if cancelled_by else ""
        ),
        "reason": reason or "",
    }
    job = PrintJob.objects.create(
        restaurant=order_item.order.restaurant,
        printer=printer,
        order=order_item.order,
        kind=PrintJobKind.CANCEL_RUNNER,
        payload=payload,
        scheduled_at=timezone.now(),
    )
    WORKER_EVENT.set()
    return job


def enqueue_receipt_print(order, kind: str = PrintJobKind.GUEST_RECEIPT) -> PrintJob:
    """Создать N PrintJob-ов (по `Restaurant.receipt_copies`) для одного заказа.

    Возвращает ПЕРВУЮ job (для обратной совместимости — старые caller'ы
    ожидают одиночный объект). Остальные копии (если N>1) тоже создаются и
    становятся в очередь с тем же payload.

    Никогда не падает: если принтера нет — printer=None, кассир назначит
    руками + retry.
    """
    printer = resolve_printer(order.restaurant, kind)
    payload = build_receipt_payload(order)
    copies = max(1, min(int(order.restaurant.receipt_copies or 1), 5))
    jobs = []
    now = timezone.now()
    for i in range(copies):
        # Метим копии в payload (для шапки «КОПИЯ 2 из 2»)
        copy_payload = dict(payload)
        if copies > 1:
            copy_payload["copy"] = {"index": i + 1, "total": copies}
        job = PrintJob.objects.create(
            restaurant=order.restaurant,
            printer=printer,
            order=order,
            kind=kind,
            payload=copy_payload,
            scheduled_at=now,
        )
        jobs.append(job)
    WORKER_EVENT.set()
    return jobs[0]


def process_one_job() -> bool:
    """Берёт одну готовую job под select_for_update(skip_locked) и пытается напечатать.
    Возвращает True, если что-то обработали (можно сразу попробовать ещё одну)."""
    now = timezone.now()
    with transaction.atomic():
        job = (
            PrintJob.objects.select_for_update(skip_locked=True)
            .filter(
                status__in=[PrintJobStatus.PENDING, PrintJobStatus.FAILED],
                scheduled_at__lte=now,
            )
            .order_by("scheduled_at")
            .first()
        )
        if job is None:
            return False
        job.status = PrintJobStatus.PRINTING
        job.started_at = now
        job.error = ""
        job.save(update_fields=["status", "started_at", "error"])

    try:
        send_to_printer(job)
    except Exception as exc:
        job.retries += 1
        if job.retries >= PrintJob.MAX_RETRIES:
            job.status = PrintJobStatus.DEAD
            job.finished_at = timezone.now()
        else:
            job.status = PrintJobStatus.FAILED
            delay = PrintJob.BACKOFF_SECONDS[job.retries - 1]
            job.scheduled_at = timezone.now() + timedelta(seconds=delay)
        job.error = repr(exc)[:5000]
        job.save(
            update_fields=["retries", "status", "scheduled_at", "finished_at", "error"]
        )
        logger.warning(
            "PrintJob %s failed (try %d/%d): %s",
            job.id, job.retries, PrintJob.MAX_RETRIES, exc,
        )
        return True

    job.status = PrintJobStatus.DONE
    job.finished_at = timezone.now()
    job.error = ""
    job.save(update_fields=["status", "finished_at", "error"])
    return True


def next_wakeup_seconds() -> float:
    """Сколько секунд ждать до ближайшей готовой job. По дефолту — 60с (poll-loop)."""
    now = timezone.now()
    job = (
        PrintJob.objects.filter(
            status__in=[PrintJobStatus.PENDING, PrintJobStatus.FAILED],
        )
        .order_by("scheduled_at")
        .only("scheduled_at")
        .first()
    )
    if job is None:
        return 60.0
    delta = (job.scheduled_at - now).total_seconds()
    return max(min(delta, 60.0), 0.5)
