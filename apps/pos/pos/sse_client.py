import json
import logging
import time

import requests
import sseclient
from PySide6.QtCore import QMutex, QMutexLocker, QThread, Signal

from pos.auth.session import SessionStore
from pos.config import API_BASE_URL, SSE_RECONNECT_DELAY_S

logger = logging.getLogger(__name__)


class SseClient(QThread):
    """Долгоживущий GET /api/v1/events/ в отдельном QThread.

    Эмитит Qt-сигналы по разным типам событий. На обрыв связи делает
    auto-reconnect через SSE_RECONNECT_DELAY_S секунд. Backend на каждое
    новое подключение шлёт `event: resync` — слушатель должен по нему
    сделать full-snapshot перезапрос (см. pos.state.State)."""

    table_updated = Signal(dict)
    order_event = Signal(str, dict)         # (event_name, payload)
    print_job_updated = Signal(dict)
    menu_invalidated = Signal()
    resync = Signal()
    network_error = Signal(str)
    auth_expired = Signal()

    def __init__(self, base_url: str = API_BASE_URL) -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.session_store = SessionStore()
        self._stop = False
        self._mutex = QMutex()
        self._response: requests.Response | None = None

    def stop(self) -> None:
        with QMutexLocker(self._mutex):
            self._stop = True
            r = self._response
        if r is None:
            return
        # Прерываем заблокированный read. Обычный r.close() в requests
        # не всегда прерывает iter_content на macOS, поэтому опускаемся
        # до сокета и делаем shutdown — это гарантированно вытащит read
        # с EOF/ошибкой.
        try:
            sock = r.raw._fp.fp.raw._sock  # type: ignore[attr-defined]
            import socket as _s
            sock.shutdown(_s.SHUT_RDWR)
        except Exception:
            pass
        try:
            r.close()
        except Exception:
            pass

    def _stopped(self) -> bool:
        with QMutexLocker(self._mutex):
            return self._stop

    def run(self) -> None:
        while not self._stopped():
            try:
                self._stream_once()
            except requests.RequestException as e:
                logger.info("SSE network error: %s", e)
                self.network_error.emit(str(e))
            except Exception as e:
                logger.exception("SSE unexpected error: %s", e)
                self.network_error.emit(str(e))
            if self._stopped():
                break
            time.sleep(SSE_RECONNECT_DELAY_S)

    def _stream_once(self) -> None:
        token = self.session_store.token
        if not token:
            self.auth_expired.emit()
            time.sleep(SSE_RECONNECT_DELAY_S)
            return

        headers = {
            "Authorization": f"PIN {token}",
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
        }
        url = f"{self.base_url}/api/v1/events/"
        # read-timeout 30с — длиннее heartbeat (15с), но даёт прерываемость:
        # если backend завис, мы переподключимся, а stop() гарантирует выход
        # за время не больше read-timeout.
        r = requests.get(url, headers=headers, stream=True, timeout=(10, 30))

        with QMutexLocker(self._mutex):
            self._response = r

        try:
            if r.status_code == 401:
                self.auth_expired.emit()
                return
            r.raise_for_status()
            client = sseclient.SSEClient(r)
            for ev in client.events():
                if self._stopped():
                    return
                self._dispatch(ev.event, ev.data)
        finally:
            with QMutexLocker(self._mutex):
                self._response = None
            try:
                r.close()
            except Exception:
                pass

    def _dispatch(self, event: str, raw: str) -> None:
        if not raw:
            return
        try:
            payload = json.loads(raw) if raw else {}
        except ValueError:
            return

        if event == "table.updated":
            self.table_updated.emit(payload)
        elif event in {"order.created", "order.updated"}:
            self.order_event.emit(event, payload)
        elif event == "print_job.updated":
            self.print_job_updated.emit(payload)
        elif event == "menu.invalidated":
            self.menu_invalidated.emit()
        elif event == "resync":
            self.resync.emit()
