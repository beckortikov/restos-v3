"""SseClient: приём событий, фильтрация, 401, авто-reconnect.

Поднимаем простой HTTP-сервер на 127.0.0.1:<random>, который отвечает на
GET /api/v1/events/ потоком text/event-stream, и направляем туда SseClient.
"""
import http.server
import socketserver
import threading
import time
from contextlib import contextmanager

import pytest


# Нестандартное поведение настраивается через классовые поля, чтобы
# каждый тест мог переопределить ответ на следующий коннект.
class _SseHandler(http.server.BaseHTTPRequestHandler):
    SCRIPT: list[bytes] = []
    AUTH_REQUIRED: bool = True
    CONNECTION_NUM: list[int] = [0]

    def log_message(self, *a, **kw):
        pass

    def do_GET(self):
        if self.path != "/api/v1/events/":
            self.send_error(404)
            return

        if self.AUTH_REQUIRED:
            auth = self.headers.get("Authorization", "")
            if "expired" in auth:
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":{"code":"AUTH_TOKEN_EXPIRED"}}')
                return
            if not auth.startswith("PIN "):
                self.send_response(401)
                self.end_headers()
                return

        self.CONNECTION_NUM[0] += 1
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        for chunk in self.SCRIPT:
            try:
                self.wfile.write(chunk)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
            time.sleep(0.02)


@contextmanager
def _run_server():
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _SseHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def _wait_for(predicate, timeout: float = 3.0, interval: float = 0.02):
    """Ждём истинности predicate, прокручивая Qt event-loop, чтобы кросс-потоковые
    сигналы из QThread доставлялись слотам в main thread."""
    from PySide6.QtCore import QCoreApplication

    deadline = time.monotonic() + timeout
    app = QCoreApplication.instance()
    while time.monotonic() < deadline:
        if app is not None:
            app.processEvents()
        if predicate():
            return True
        time.sleep(interval)
    if app is not None:
        app.processEvents()
    return predicate()


@pytest.fixture(scope="session")
def qapp_session():
    from PySide6.QtCore import QCoreApplication

    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


def _make_client(server, qapp_session, token: str = "valid-token") -> "SseClient":
    from pos.auth.session import SessionStore
    from pos.sse_client import SseClient

    SessionStore().token = token
    base = f"http://127.0.0.1:{server.server_address[1]}"
    return SseClient(base_url=base)


def test_resync_emitted_on_connect(qapp_session):
    _SseHandler.SCRIPT = [
        b":ok\n\n",
        b"id: 1\nevent: resync\ndata: {}\n\n",
    ]
    _SseHandler.CONNECTION_NUM = [0]

    with _run_server() as srv:
        client = _make_client(srv, qapp_session)
        got_resync: list[bool] = []
        client.resync.connect(lambda: got_resync.append(True))
        client.start()
        try:
            assert _wait_for(lambda: got_resync), "resync не пришёл"
        finally:
            client.stop()
            client.wait(2000)


def test_table_updated_dispatches_payload(qapp_session):
    _SseHandler.SCRIPT = [
        b":ok\n\n",
        b"id: 1\nevent: resync\ndata: {}\n\n",
        b'id: 2\nevent: table.updated\ndata: {"id":7,"status":"occupied"}\n\n',
    ]
    _SseHandler.CONNECTION_NUM = [0]

    with _run_server() as srv:
        client = _make_client(srv, qapp_session)
        got: list[dict] = []
        client.table_updated.connect(lambda p: got.append(p))
        client.start()
        try:
            assert _wait_for(lambda: got), "table.updated не пришёл"
            assert got[0]["id"] == 7
            assert got[0]["status"] == "occupied"
        finally:
            client.stop()
            client.wait(2000)


def test_order_event_dispatches_with_event_name(qapp_session):
    _SseHandler.SCRIPT = [
        b":ok\n\n",
        b"id: 1\nevent: resync\ndata: {}\n\n",
        b'id: 2\nevent: order.created\ndata: {"id":42,"status":"new"}\n\n',
        b'id: 3\nevent: order.updated\ndata: {"id":42,"status":"bill_requested"}\n\n',
    ]
    _SseHandler.CONNECTION_NUM = [0]

    with _run_server() as srv:
        client = _make_client(srv, qapp_session)
        got: list[tuple[str, dict]] = []
        client.order_event.connect(lambda name, p: got.append((name, p)))
        client.start()
        try:
            assert _wait_for(lambda: len(got) >= 2), f"got: {got}"
            assert got[0][0] == "order.created"
            assert got[1][0] == "order.updated"
            assert got[1][1]["status"] == "bill_requested"
        finally:
            client.stop()
            client.wait(2000)


def test_auth_expired_on_401(qapp_session, monkeypatch):
    _SseHandler.SCRIPT = []
    _SseHandler.CONNECTION_NUM = [0]

    monkeypatch.setattr("pos.sse_client.SSE_RECONNECT_DELAY_S", 0.05)

    with _run_server() as srv:
        client = _make_client(srv, qapp_session, token="expired-token")
        got: list[bool] = []
        client.auth_expired.connect(lambda: got.append(True))
        client.start()
        try:
            assert _wait_for(lambda: got), "auth_expired не пришёл"
        finally:
            client.stop()
            client.wait(2000)


def test_auto_reconnect_after_disconnect(qapp_session, monkeypatch):
    """Сервер закрывает коннект после первого resync. Клиент через 0.1с открывает заново
    и снова получает resync — сигнал должен прийти ≥2 раз."""
    _SseHandler.SCRIPT = [
        b":ok\n\n",
        b"id: 1\nevent: resync\ndata: {}\n\n",
        # сервер заканчивает SCRIPT и закрывает соединение
    ]
    _SseHandler.CONNECTION_NUM = [0]

    monkeypatch.setattr("pos.sse_client.SSE_RECONNECT_DELAY_S", 0.1)

    with _run_server() as srv:
        client = _make_client(srv, qapp_session)
        resync_count: list[int] = [0]
        client.resync.connect(lambda: resync_count.__setitem__(0, resync_count[0] + 1))
        client.start()
        try:
            assert _wait_for(lambda: resync_count[0] >= 2, timeout=5.0), \
                f"resync пришёл {resync_count[0]} раз(а), ожидали ≥2"
        finally:
            client.stop()
            client.wait(2000)


def test_heartbeat_does_not_dispatch(qapp_session):
    """Heartbeat-комментарий (':...') от сервера не должен порождать событий."""
    _SseHandler.SCRIPT = [
        b":ok\n\n",
        b"id: 1\nevent: resync\ndata: {}\n\n",
        b":heartbeat\n\n",
        b":heartbeat\n\n",
        b'id: 2\nevent: table.updated\ndata: {"id":1,"status":"free"}\n\n',
    ]
    _SseHandler.CONNECTION_NUM = [0]

    with _run_server() as srv:
        client = _make_client(srv, qapp_session)
        got_resync: list[bool] = []
        got_table: list[dict] = []
        client.resync.connect(lambda: got_resync.append(True))
        client.table_updated.connect(lambda p: got_table.append(p))
        client.start()
        try:
            assert _wait_for(lambda: got_table)
            assert len(got_resync) == 1
            assert got_table[0]["id"] == 1
        finally:
            client.stop()
            client.wait(2000)
