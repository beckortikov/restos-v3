"""Single-exe архитектура: POS exe сам поднимает Postgres + Django backend.

Идея (как в restos-v4):
    POS exe старт →
      [1] PgSupervisor: распаковать/запустить portable Postgres в %APPDATA%/RestOS/pgdata/
      [2] DjangoSupervisor: настроить Django, применить migrate, поднять WSGI на 127.0.0.1:8000
      [3] Wait for /api/v1/health/ to return 200
      [4] Запустить PySide6 GUI (MainWindow)
    POS exit →
      [5] Django graceful shutdown
      [6] pg_ctl stop

Используется `pgserver` — Python библиотека которая включает Postgres binaries
для Win/Mac/Linux + автоматически делает initdb, pg_ctl start/stop.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

# Папка данных в LOCALAPPDATA/RestOS (Windows) или ~/.restos-pos (Mac/Linux).
# Сюда кладётся pgdata/, license.json и т.д.
def _data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        return base / "RestOS"
    return Path.home() / ".restos-pos"


def _backend_root() -> Path:
    """Где лежит код Django.

    В development — apps/backend относительно репо.
    В PyInstaller bundle — `sys._MEIPASS/backend` (см. pos.spec datas).
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "backend"  # type: ignore[attr-defined]
    here = Path(__file__).resolve()
    # apps/pos/pos/services/embedded_backend.py → apps/backend
    return here.parents[3] / "backend"


# ──────────────────────── Postgres supervisor ─────────────────────────────


class PgSupervisor:
    """Управляет жизненным циклом локального Postgres (через pgserver)."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self._data_dir = data_dir or (_data_dir() / "pgdata")
        self._server = None  # pgserver.PostgresServer
        self._uri: str = ""

    @property
    def database_url(self) -> str:
        return self._uri

    def start(self) -> str:
        """Запустить (или подключиться к уже запущенному) Postgres."""
        try:
            import pgserver
        except ImportError as e:
            raise RuntimeError(
                "pgserver не установлен. Добавьте в pyproject.toml: pgserver",
            ) from e

        self._data_dir.mkdir(parents=True, exist_ok=True)
        log.info("→ Starting embedded Postgres in %s", self._data_dir)
        # get_server() = idempotent: initdb если первый раз, start если остановлен.
        # cleanup_mode=None — не останавливать на выходе python, мы сами через stop().
        self._server = pgserver.get_server(
            str(self._data_dir), cleanup_mode=None,
        )
        # pgserver возвращает URI типа postgresql://localhost:port/dbname
        self._uri = self._server.get_uri()
        log.info("  Postgres ready: %s", self._uri.split("@")[-1])
        return self._uri

    def stop(self) -> None:
        if self._server is None:
            return
        try:
            log.info("→ Stopping Postgres...")
            self._server.cleanup()
            log.info("  Postgres stopped.")
        except Exception as e:
            log.warning("  Postgres cleanup error: %s", e)
        finally:
            self._server = None


# ──────────────────────── Django supervisor ───────────────────────────────


class DjangoSupervisor:
    """Запускает Django как WSGI в фоновом thread'е.

    Использует `waitress` (cross-platform, pure-Python) — он уже в backend
    deps. На Linux/Mac можно тоже gunicorn, но waitress универсальнее.
    """

    def __init__(self, database_url: str, port: int = 8000) -> None:
        self.database_url = database_url
        self.port = port
        self._thread: threading.Thread | None = None
        self._server = None  # waitress server

    def _setup_django(self) -> None:
        """Настроить sys.path, env vars, Django apps."""
        backend = _backend_root()
        if not backend.exists():
            raise RuntimeError(
                f"Backend code not found at {backend}. "
                "Проверьте PyInstaller bundle.",
            )
        if str(backend) not in sys.path:
            sys.path.insert(0, str(backend))

        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.embedded")
        os.environ["DATABASE_URL"] = self.database_url
        # Минимальные secrets для embedded режима — генерим если нет
        if not os.environ.get("DJANGO_SECRET_KEY"):
            import secrets
            os.environ["DJANGO_SECRET_KEY"] = secrets.token_urlsafe(64)
        os.environ.setdefault("DJANGO_DEBUG", "False")
        os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost,*")

        import django
        django.setup()

    def _run_migrations(self) -> None:
        log.info("→ Applying Django migrations...")
        from django.core.management import call_command
        call_command("migrate", interactive=False, verbosity=1)
        log.info("  Migrations applied.")

    def _create_default_data(self) -> None:
        """Идемпотентно создать первый Restaurant + admin, если пусто."""
        log.info("→ Ensuring default Restaurant + admin user...")
        from django.contrib.auth import get_user_model
        try:
            from apps.users.models import Restaurant
        except Exception as e:
            log.warning("  default data init skipped: %s", e)
            return

        Restaurant.objects.get_or_create(
            id=1, defaults={"name": "Мой ресторан", "currency": "TJS"},
        )
        User = get_user_model()
        if not User.objects.filter(username="admin").exists():
            try:
                User.objects.create_superuser(username="admin", password="admin")
            except TypeError:
                # Кастомный User может не принимать стандартные args
                u = User(username="admin", is_staff=True, is_superuser=True)
                u.set_password("admin")
                u.save()
            log.info("  Created admin/admin user.")

    def start(self) -> None:
        """Запустить Django в фоновом thread'е."""
        self._setup_django()
        self._run_migrations()
        self._create_default_data()

        from waitress import create_server
        from django.core.wsgi import get_wsgi_application
        app = get_wsgi_application()
        self._server = create_server(
            app, host="127.0.0.1", port=self.port, threads=4,
        )
        log.info("→ Django listening on http://127.0.0.1:%d", self.port)
        self._thread = threading.Thread(
            target=self._server.run, daemon=True, name="Django-WSGI",
        )
        self._thread.start()

    def stop(self) -> None:
        if self._server is None:
            return
        try:
            log.info("→ Stopping Django WSGI...")
            self._server.close()
        except Exception as e:
            log.warning("  Django close error: %s", e)
        self._server = None

    def wait_for_health(self, timeout: int = 60) -> bool:
        """Polling /api/v1/health/ пока не вернёт 200 или не истечёт timeout."""
        import requests
        url = f"http://127.0.0.1:{self.port}/api/v1/health/"
        deadline = time.time() + timeout
        last_err = None
        while time.time() < deadline:
            try:
                r = requests.get(url, timeout=2)
                if r.status_code == 200:
                    log.info("  Backend health OK.")
                    return True
            except Exception as e:
                last_err = e
            time.sleep(0.5)
        log.error("  Backend health failed: %s", last_err)
        return False


# ──────────────────────── Combined orchestrator ───────────────────────────


class EmbeddedBackend:
    """Удобная обёртка для main.py — поднять всё одной командой.

    Использование:
        eb = EmbeddedBackend()
        eb.start()  # блокирует до готовности backend'а
        try:
            run_gui()
        finally:
            eb.stop()
    """

    def __init__(self, port: int = 8000) -> None:
        self.pg = PgSupervisor()
        self.django: DjangoSupervisor | None = None
        self.port = port

    def start(self, *, on_progress=None) -> None:
        def _p(msg: str) -> None:
            log.info(msg)
            if on_progress:
                try:
                    on_progress(msg)
                except Exception:
                    pass

        _p("Запускаем базу данных…")
        uri = self.pg.start()

        _p("Запускаем сервис заказов…")
        self.django = DjangoSupervisor(uri, port=self.port)
        self.django.start()

        _p("Проверяем готовность…")
        if not self.django.wait_for_health(timeout=60):
            raise RuntimeError(
                "Backend не отвечает на /api/v1/health/. "
                "Посмотрите логи в %APPDATA%/RestOS/embedded.log",
            )
        _p("Готово.")

    def stop(self) -> None:
        if self.django is not None:
            self.django.stop()
        self.pg.stop()
