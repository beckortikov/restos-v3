import signal

from django.core.management.base import BaseCommand

from apps.printing.services import (
    WORKER_EVENT,
    next_wakeup_seconds,
    process_one_job,
)


class Command(BaseCommand):
    help = "Запускает воркер очереди печати (single-process, кроссплатформенный)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Обработать все готовые job и выйти (для cron/тестов).",
        )

    def handle(self, *args, **opts):
        stop = {"flag": False}

        def _handle_signal(signum, frame):
            self.stdout.write(self.style.WARNING(f"Получен сигнал {signum}, останавливаюсь…"))
            stop["flag"] = True
            WORKER_EVENT.set()

        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

        once = opts.get("once", False)
        self.stdout.write(self.style.SUCCESS(f"print_worker started (once={once})"))

        while not stop["flag"]:
            processed_anything = True
            while processed_anything and not stop["flag"]:
                processed_anything = process_one_job()
            if once:
                break
            wait_s = next_wakeup_seconds()
            WORKER_EVENT.wait(timeout=wait_s)
            WORKER_EVENT.clear()

        self.stdout.write("print_worker stopped")
