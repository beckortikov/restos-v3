import logging

from PySide6.QtCore import QObject, Signal

from pos.http_client import ApiClient, ApiError
from pos.sse_client import SseClient

logger = logging.getLogger(__name__)


class State(QObject):
    """Singleton: REST-клиент + SSE-стрим + кэш текущих столов/заказов.

    UI-экраны подписываются на `tables_changed`/`orders_changed`/`online_changed`
    и не делают прямых HTTP-запросов под событиями — это работа State."""

    tables_changed = Signal(list)        # full snapshot list[dict]
    orders_changed = Signal(list)
    print_job_updated = Signal(dict)
    online_changed = Signal(bool)
    auth_expired = Signal()
    shift_changed = Signal(object)       # current_shift dict | None
    license_changed = Signal(dict)       # license status dict
    permissions_changed = Signal(list)   # current user permissions list

    def __init__(self) -> None:
        super().__init__()
        self.client = ApiClient()
        # Единая точка обработки 401 AUTH_TOKEN_EXPIRED от REST-запросов:
        # client.on_auth_expired → State.auth_expired сигнал → main чистит
        # keyring + переключает на PIN-login. Раньше сигнал шёл ТОЛЬКО из
        # SSE-клиента, REST-401 становился ApiError и каждый caller рисовал
        # свою модалку.
        self.client.on_auth_expired = self.auth_expired.emit
        self.sse: SseClient | None = None
        self.is_online: bool = True
        self._tables: dict[int, dict] = {}
        self._orders: dict[int, dict] = {}
        self._current_shift: dict | None = None
        # Кэш справочника причин отмены: {kind: list[dict]}.
        # Не хардкодим — грузится из /cancel_reasons/, админ редактирует через
        # «Настройки → Скидки и сервис».
        self._cancel_reasons: dict[str, list[dict]] = {}
        # License status snapshot — обновляется через refresh_license() и
        # автоматически каждые 10 минут (в main.py) + при возврате из 402.
        self._license: dict | None = None
        # Permissions текущего залогиненного юзера (заполняется при /auth/me/).
        self._permissions: list[str] = []
        self._user_role: str = ""

    def get_cancel_reasons(self, kind: str) -> list[dict]:
        """Возвращает кэшированный список причин для kind ∈ {item, order, refund}.

        Lazy-load: если кэш пуст для этого kind, тянет из API. На ошибке
        возвращает [] (UI деградирует до textarea без чипов)."""
        if kind in self._cancel_reasons:
            return self._cancel_reasons[kind]
        try:
            data = self.client.get(
                "/cancel_reasons/", params={"kind": kind, "is_active": "true"}
            )
            items = data if isinstance(data, list) else (data or {}).get("data", [])
            self._cancel_reasons[kind] = [
                r for r in items if r.get("is_active", True)
            ]
        except ApiError as e:
            logger.warning("get_cancel_reasons(%s) failed: %s", kind, e)
            self._cancel_reasons[kind] = []
        return self._cancel_reasons[kind]

    def invalidate_cancel_reasons(self) -> None:
        """Сбросить кэш — после редактирования в настройках."""
        self._cancel_reasons.clear()

    def get_discounts(self) -> list[dict]:
        """Вернуть активные скидки (type='discount') для применения в PaymentDialog.

        Не кэшируется агрессивно — список редко меняется, но кассир может
        включить/выключить скидку в настройках, и это должно отразиться
        мгновенно. Lazy fetch на каждый вызов диалога — нормально (запрос ≤ 1).
        """
        try:
            data = self.client.get(
                "/discounts/", params={"type": "discount", "is_active": "true"}
            )
            items = data if isinstance(data, list) else (data or {}).get("data", [])
            return [d for d in items if d.get("is_active", True)]
        except ApiError as e:
            logger.warning("get_discounts failed: %s", e)
            return []

    @property
    def license(self) -> dict | None:
        return self._license

    def refresh_license(self) -> dict | None:
        """Тянет /license/status/, обновляет state и emit'ит license_changed."""
        try:
            data = self.client.get("/license/status/")
            lic = data if isinstance(data, dict) and "status" in data else (
                (data or {}).get("data") if isinstance(data, dict) else None
            )
        except ApiError as e:
            logger.warning("refresh_license failed: %s", e)
            return self._license
        if lic is None:
            return self._license
        self._license = lic
        self.license_changed.emit(lic)
        return lic

    @property
    def permissions(self) -> list[str]:
        return list(self._permissions)

    @property
    def user_role(self) -> str:
        return self._user_role

    def has_perm(self, key: str) -> bool:
        """Manager — всегда True. Иначе — есть ли key в permissions."""
        if self._user_role == "manager":
            return True
        return key in self._permissions

    def refresh_me(self) -> dict | None:
        """Тянет /auth/me/ и обновляет permissions + role.

        Вызывается после логина и при изменении профиля юзера.
        """
        try:
            data = self.client.get("/auth/me/")
        except ApiError:
            return None
        if not isinstance(data, dict):
            return None
        body = data.get("data", data)
        user = body.get("user") or {}
        self._user_role = (user.get("role") or "").strip()
        self._permissions = list(user.get("permissions") or [])
        self.permissions_changed.emit(self._permissions)
        return body

    def heartbeat(self, app_version: str = "") -> None:
        """Шлёт POST /heartbeat/. Безопасно: при ошибке тихо игнорируем."""
        try:
            self.client.post("/heartbeat/", json={"app_version": app_version or ""})
        except ApiError as e:
            logger.debug("heartbeat failed: %s", e)

    @property
    def current_shift(self) -> dict | None:
        return self._current_shift

    def set_current_shift(self, shift: dict | None) -> None:
        self._current_shift = shift
        self.shift_changed.emit(shift)

    def refresh_shift(self) -> dict | None:
        """Тянет /shifts/current/ и обновляет _current_shift. Возвращает текущую смену или None."""
        try:
            data = self.client.get("/shifts/current/")
            shift = data if isinstance(data, dict) and data.get("id") else None
            self._current_shift = shift
            self.shift_changed.emit(shift)
            return shift
        except ApiError as e:
            logger.warning("refresh_shift failed: %s", e)
            return self._current_shift

    @property
    def tables(self) -> list[dict]:
        return list(self._tables.values())

    @property
    def orders(self) -> list[dict]:
        return list(self._orders.values())

    def start_stream(self) -> None:
        if self.sse is not None:
            return
        self.sse = SseClient()
        self.sse.resync.connect(self._on_resync)
        self.sse.table_updated.connect(self._on_table)
        self.sse.order_event.connect(self._on_order)
        self.sse.print_job_updated.connect(self._on_print_job)
        self.sse.network_error.connect(self._on_network_error)
        self.sse.auth_expired.connect(self.auth_expired.emit)
        self.sse.start()

    def stop_stream(self) -> None:
        if self.sse is None:
            return
        self.sse.stop()
        # Сначала аккуратно ждём 1.5с — обычно socket.shutdown в stop() прерывает
        # read мгновенно, и поток уходит за <100ms. Если по какой-то причине
        # завис (дедлок в requests/sseclient на macOS bug) — рубим terminate().
        # Это безопасно при выходе из приложения: ОС всё равно очистит сокеты.
        if not self.sse.wait(1500):
            self.sse.terminate()
            self.sse.wait(500)
        self.sse = None

    def _set_online(self, value: bool) -> None:
        if value != self.is_online:
            self.is_online = value
            self.online_changed.emit(value)

    def refresh(self) -> bool:
        """Синхронно тянет /tables/ + /orders/ через REST и эмитит сигналы.
        Используется сразу после login (чтобы UI не ждал буферизированного SSE-resync)
        и из _on_resync при коннекте SSE. Возвращает True если получилось."""
        try:
            tables = self.client.get("/tables/") or []
            self._tables = {t["id"]: t for t in tables}
            self.tables_changed.emit(self.tables)

            # django-filter не поддерживает `?status=a,b` без custom-фильтра,
            # поэтому тянем все и фильтруем на клиенте. Активных заказов в
            # ресторане десятки, не сотни — нагрузка пренебрежимая.
            orders = self.client.get("/orders/") or []
            active = [o for o in orders if o.get("status") in {"new", "bill_requested"}]
            self._orders = {o["id"]: o for o in active}
            self.orders_changed.emit(self.orders)
            self._set_online(True)
            return True
        except ApiError as e:
            logger.warning("refresh failed: %s", e)
            self._set_online(False)
            return False

    def _on_resync(self) -> None:
        self.refresh()

    def _on_table(self, row: dict) -> None:
        self._set_online(True)
        existing = self._tables.get(row["id"], {})
        self._tables[row["id"]] = {**existing, **row}
        self.tables_changed.emit(self.tables)

    def _on_order(self, event: str, row: dict) -> None:
        self._set_online(True)
        if row.get("status") in {"done", "cancelled"}:
            self._orders.pop(row["id"], None)
        else:
            existing = self._orders.get(row["id"], {})
            self._orders[row["id"]] = {**existing, **row}
        self.orders_changed.emit(self.orders)

    def _on_print_job(self, row: dict) -> None:
        self._set_online(True)
        self.print_job_updated.emit(row)

    def _on_network_error(self, msg: str) -> None:
        # SSE-обрыв ≠ offline. Backend может быть жив (REST работает),
        # но SSE-стрим оборвался (рестарт, прокси таймаут, etc).
        # Пробуем REST; если он тоже падает — тогда offline.
        logger.info("SSE network error: %s — пробую REST для проверки", msg)
        try:
            self.client.get("/auth/me/")
            self._set_online(True)
        except ApiError:
            self._set_online(False)


_state: State | None = None


def get_state() -> State:
    global _state
    if _state is None:
        _state = State()
    return _state
