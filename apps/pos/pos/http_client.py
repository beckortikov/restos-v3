import time
import uuid
from typing import Any

import requests

from pos.auth.session import SessionStore
from pos.config import API_BASE_URL, HTTP_RETRIES, HTTP_TIMEOUT_S


class ApiError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        http_status: int,
        detail: dict | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.http_status = http_status
        self.detail = detail or {}
        super().__init__(f"[{code}] {message}")


class ApiClient:
    """Тонкая обёртка над requests.Session.

    1. Подставляет `Authorization: PIN <session_token>`.
    2. Auto-retry на сетевые ошибки: HTTP_RETRIES попыток, exp.backoff 0.5 / 1 / 2 с.
       Auth-/4xx-/5xx- ответы НЕ ретраятся, чтобы не плодить дубли мутаций.
    3. Распаковывает {"data": …} из тела или бросает ApiError из {"error": …}.
    4. Поддерживает idempotent=True (генерирует Idempotency-Key UUID на вызов)
       и extra_headers для переиспользования того же ключа на ретраях UI."""

    def __init__(self, base_url: str = API_BASE_URL) -> None:
        self.base = base_url.rstrip("/")
        self.s = requests.Session()
        self.session_store = SessionStore()
        # Callback вызывается при HTTP 401 AUTH_TOKEN_EXPIRED. State подписывает
        # на него свой `_handle_auth_expired` — единая точка обработки
        # для REST + SSE. Без callback клиент просто бросит ApiError.
        self.on_auth_expired: callable | None = None

    def _headers(
        self,
        idempotent: bool,
        extra_headers: dict | None,
        *,
        skip_auth: bool = False,
    ) -> dict:
        h: dict[str, str] = {"Accept": "application/json"}
        if not skip_auth:
            token = self.session_store.token
            if token:
                h["Authorization"] = f"PIN {token}"
        # SA-7 — машинный UUID для server-side проверки machine binding
        try:
            from pos.resources.license_store import get_machine_uuid
            mid = get_machine_uuid()
            if mid:
                h["X-Machine-UUID"] = mid
        except Exception:
            pass
        if idempotent:
            h["Idempotency-Key"] = str(uuid.uuid4())
        if extra_headers:
            h.update(extra_headers)
        return h

    # Эндпоинты, которым НЕ нужно слать Authorization PIN header (даже если
    # в keyring остался stale-токен). Backend на этих endpoint'ах сначала
    # пытается аутентифицировать переданный токен и возвращает 401
    # AUTH_TOKEN_EXPIRED, не доходя до собственной логики (PIN-login,
    # /me/-check для разлогиненного пользователя и т.п.).
    _NO_AUTH_PATHS = ("/auth/pin/", "/auth/login/", "/auth/refresh/")

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict | None = None,
        idempotent: bool = False,
        extra_headers: dict | None = None,
        retries: int = HTTP_RETRIES,
        timeout: float = HTTP_TIMEOUT_S,
    ) -> Any:
        url = f"{self.base}/api/v1{path}"
        last_exc: Exception | None = None
        skip_auth = any(path.startswith(p) for p in self._NO_AUTH_PATHS)

        for attempt in range(max(retries, 1)):
            try:
                r = self.s.request(
                    method,
                    url,
                    json=json,
                    params=params,
                    headers=self._headers(
                        idempotent, extra_headers, skip_auth=skip_auth,
                    ),
                    timeout=timeout,
                )
            except requests.RequestException as e:
                last_exc = e
                if attempt < retries - 1:
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                break

            try:
                payload = r.json()
            except ValueError:
                payload = {}

            if r.status_code >= 400:
                err = (payload or {}).get("error", {}) if isinstance(payload, dict) else {}
                code = err.get("code", "HTTP_ERROR")
                # 401 AUTH_TOKEN_EXPIRED — единая точка обработки. Сигналим
                # State (тот чистит keyring + переключает UI на PIN-login).
                # Дальше всё равно бросаем ApiError, чтобы caller не падал на
                # отсутствующих данных.
                if r.status_code == 401 and code == "AUTH_TOKEN_EXPIRED":
                    if self.on_auth_expired is not None:
                        try:
                            self.on_auth_expired()
                        except Exception:
                            pass
                raise ApiError(
                    code=code,
                    message=err.get("message", (r.text or "")[:200]),
                    http_status=r.status_code,
                    detail=err.get("detail", {}),
                )
            if isinstance(payload, dict) and "data" in payload:
                return payload["data"]
            return payload

        raise ApiError("NETWORK", str(last_exc), 0)

    def get(self, path: str, **kw: Any) -> Any:
        return self.request("GET", path, **kw)

    def post(self, path: str, **kw: Any) -> Any:
        return self.request("POST", path, **kw)

    def post_file(
        self,
        path: str,
        *,
        field: str,
        filename: str,
        content: bytes,
        content_type: str = "application/octet-stream",
        idempotent: bool = True,
        timeout: float = HTTP_TIMEOUT_S * 3,
    ) -> Any:
        """POST multipart/form-data с одним файлом. Без auto-retry (тяжело и небезопасно).

        Возвращает `data`-часть ответа или бросает `ApiError`.
        """
        url = f"{self.base}/api/v1{path}"
        headers = self._headers(idempotent, None)
        # requests сам выставит Content-Type с boundary — Accept оставляем
        try:
            r = self.s.post(
                url,
                files={field: (filename, content, content_type)},
                headers=headers,
                timeout=timeout,
            )
        except requests.RequestException as e:
            raise ApiError("NETWORK", str(e), 0) from e

        try:
            payload = r.json()
        except ValueError:
            payload = {}
        if r.status_code >= 400:
            err = (payload or {}).get("error", {}) if isinstance(payload, dict) else {}
            raise ApiError(
                code=err.get("code", "HTTP_ERROR"),
                message=err.get("message", (r.text or "")[:200]),
                http_status=r.status_code,
                detail=err.get("detail", {}),
            )
        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        return payload

    def get_raw(self, path: str, *, timeout: float = HTTP_TIMEOUT_S) -> bytes:
        """GET, возвращает сырые байты (для скачивания файлов: XLSX-шаблоны).

        Не парсит JSON — возвращает r.content. При HTTP>=400 — бросает ApiError.
        """
        url = f"{self.base}/api/v1{path}"
        headers = self._headers(False, None)
        try:
            r = self.s.get(url, headers=headers, timeout=timeout)
        except requests.RequestException as e:
            raise ApiError("NETWORK", str(e), 0) from e
        if r.status_code >= 400:
            try:
                payload = r.json()
                err = (payload or {}).get("error", {}) if isinstance(payload, dict) else {}
            except ValueError:
                err = {}
            raise ApiError(
                code=err.get("code", "HTTP_ERROR"),
                message=err.get("message", (r.text or "")[:200]),
                http_status=r.status_code,
                detail=err.get("detail", {}),
            )
        return r.content
