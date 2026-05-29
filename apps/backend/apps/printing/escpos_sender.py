from pathlib import Path

from django.conf import settings

from .models import PrinterKind, PrintJobKind
from .templates import cancel_runner as cancel_runner_tpl
from .templates import ready_runner as ready_runner_tpl
from .templates import z_report as z_report_tpl
from .templates.receipt import render_escpos, render_text_preview


def _payload_with_paper(job) -> dict:
    """Добавляет в payload paper_size принтера, чтобы template подобрал ширину."""
    payload = dict(job.payload)
    if job.printer is not None:
        payload["printer_paper_size"] = job.printer.paper_size
    return payload


def _render_preview(job) -> str:
    """Выбор шаблона по job.kind."""
    payload = _payload_with_paper(job)
    if job.kind in (PrintJobKind.Z_REPORT, PrintJobKind.X_REPORT):
        return z_report_tpl.render_text_preview(payload)
    if job.kind == PrintJobKind.CANCEL_RUNNER:
        return cancel_runner_tpl.render_text_preview(payload)
    if job.kind == PrintJobKind.READY_RUNNER:
        return ready_runner_tpl.render_text_preview(payload)
    return render_text_preview(payload)


def _render_to_printer(printer, job) -> None:
    payload = _payload_with_paper(job)
    if job.kind in (PrintJobKind.Z_REPORT, PrintJobKind.X_REPORT):
        z_report_tpl.render_escpos(printer, payload)
    elif job.kind == PrintJobKind.CANCEL_RUNNER:
        cancel_runner_tpl.render_escpos(printer, payload)
    elif job.kind == PrintJobKind.READY_RUNNER:
        ready_runner_tpl.render_escpos(printer, payload)
    else:
        render_escpos(printer, payload)


def _write_to_disk(job) -> None:
    out_dir = Path(settings.PRINTER_OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{job.id}.txt").write_text(
        _render_preview(job), encoding="utf-8"
    )


def _is_virtual(job) -> bool:
    if getattr(settings, "PRINTER_VIRTUAL", False):
        return True
    if getattr(job.restaurant, "printer_virtual_mode", False):
        return True
    return job.printer is None or job.printer.kind == PrinterKind.VIRTUAL


def _open_printer(printer):
    from escpos.printer import Network, Serial, Usb

    if printer.kind == PrinterKind.TCP:
        host, port = printer.address.split(":")
        return Network(host, int(port), timeout=5)
    if printer.kind == PrinterKind.USB:
        vid, pid = printer.address.split(":")
        return Usb(int(vid, 16), int(pid, 16))
    if printer.kind == PrinterKind.SERIAL:
        dev, baud = printer.address.split(":")
        return Serial(dev, baudrate=int(baud))
    raise ValueError(f"Unknown printer kind {printer.kind}")


def send_to_printer(job) -> None:
    """Бросает исключение при ошибке — worker увидит и сделает retry."""
    if _is_virtual(job):
        _write_to_disk(job)
        return

    if job.printer is None:
        raise RuntimeError("Принтер не настроен")

    p = _open_printer(job.printer)
    try:
        p.charcode("CP866")
        _render_to_printer(p, job)
        p.cut()
        # Открыть денежный ящик после печати, если настроено и job — guest_receipt
        if (
            job.kind == PrintJobKind.GUEST_RECEIPT
            and job.restaurant.auto_open_cash_drawer
        ):
            try:
                p.cashdraw(2)  # ESC/POS DLE 0x02 — open cash drawer pin 2
            except Exception:
                pass
    finally:
        try:
            p.close()
        except Exception:
            pass
