"""Тесты ApiClient — поведение HTTP-обёртки без реальной сети."""
from unittest.mock import MagicMock

import pytest
import requests


def _make_response(status: int, body: dict | None = None, text: str = "") -> MagicMock:
    r = MagicMock(spec=requests.Response)
    r.status_code = status
    r.text = text or (str(body) if body else "")
    r.json.return_value = body if body is not None else {}
    return r


def test_pin_header_added(monkeypatch):
    from pos.auth.session import SessionStore
    from pos.http_client import ApiClient

    SessionStore().token = "abc"

    client = ApiClient(base_url="http://test")
    captured: dict = {}

    def fake_request(method, url, **kw):
        captured["headers"] = kw["headers"]
        return _make_response(200, {"data": {"ok": True}})

    monkeypatch.setattr(client.s, "request", fake_request)
    out = client.get("/auth/me/")
    assert out == {"ok": True}
    assert captured["headers"]["Authorization"] == "PIN abc"


def test_no_auth_header_for_login_even_with_stale_token(monkeypatch):
    """POST /auth/pin/ должен идти БЕЗ Authorization header даже если в
    keyring остался stale-токен от предыдущей сессии. Иначе backend вернёт
    401 AUTH_TOKEN_EXPIRED до проверки PIN."""
    from pos.auth.session import SessionStore
    from pos.http_client import ApiClient

    SessionStore().token = "stale-token-from-prev-session"
    try:
        client = ApiClient(base_url="http://test")
        captured: dict = {}

        def fake_request(method, url, **kw):
            captured["headers"] = kw["headers"]
            return _make_response(200, {"data": {"session_token": "new"}})

        monkeypatch.setattr(client.s, "request", fake_request)
        client.post("/auth/pin/", json={"pin": "1234"})
        # Header НЕ должен содержать stale-токен.
        assert "Authorization" not in captured["headers"]
    finally:
        SessionStore().clear()


def test_auth_expired_callback_fired_on_401(monkeypatch):
    """ApiClient вызывает on_auth_expired callback при 401 AUTH_TOKEN_EXPIRED.
    State подписывается → чистит keyring + переключает UI на PIN-login."""
    from pos.http_client import ApiClient

    client = ApiClient(base_url="http://test")
    fired: list[bool] = []
    client.on_auth_expired = lambda: fired.append(True)

    def fake_request(method, url, **kw):
        return _make_response(
            401, {"error": {"code": "AUTH_TOKEN_EXPIRED", "message": "expired"}},
        )

    monkeypatch.setattr(client.s, "request", fake_request)
    import pytest as _pytest
    from pos.http_client import ApiError
    with _pytest.raises(ApiError):
        client.get("/tables/")
    assert fired == [True]


def test_no_auth_header_when_no_token(monkeypatch):
    from pos.http_client import ApiClient

    client = ApiClient(base_url="http://test")
    captured: dict = {}

    def fake_request(method, url, **kw):
        captured["headers"] = kw["headers"]
        return _make_response(200, {"data": {}})

    monkeypatch.setattr(client.s, "request", fake_request)
    client.get("/menu/items/")
    assert "Authorization" not in captured["headers"]


def test_idempotent_key_generated(monkeypatch):
    from pos.http_client import ApiClient

    client = ApiClient(base_url="http://test")
    captured: list[dict] = []

    def fake_request(method, url, **kw):
        captured.append(kw["headers"].copy())
        return _make_response(200, {"data": {}})

    monkeypatch.setattr(client.s, "request", fake_request)
    client.post("/orders/", json={}, idempotent=True)
    client.post("/orders/", json={}, idempotent=True)

    assert "Idempotency-Key" in captured[0]
    assert "Idempotency-Key" in captured[1]
    assert captured[0]["Idempotency-Key"] != captured[1]["Idempotency-Key"]


def test_extra_headers_reuse_idempotency_key(monkeypatch):
    """UI на ретрае передаёт тот же ключ через extra_headers."""
    from pos.http_client import ApiClient

    client = ApiClient(base_url="http://test")
    captured: list[dict] = []

    def fake_request(method, url, **kw):
        captured.append(kw["headers"].copy())
        return _make_response(200, {"data": {}})

    monkeypatch.setattr(client.s, "request", fake_request)
    same_key = "fixed-key-uuid"
    client.post("/orders/1/close/", json={}, extra_headers={"Idempotency-Key": same_key})
    client.post("/orders/1/close/", json={}, extra_headers={"Idempotency-Key": same_key})

    assert captured[0]["Idempotency-Key"] == same_key
    assert captured[1]["Idempotency-Key"] == same_key


def test_4xx_raises_apierror_with_code(monkeypatch):
    from pos.http_client import ApiClient, ApiError

    client = ApiClient(base_url="http://test")
    body = {"error": {"code": "TABLE_OCCUPIED", "message": "Стол занят", "detail": {}}}
    monkeypatch.setattr(
        client.s, "request", lambda *a, **kw: _make_response(409, body)
    )

    with pytest.raises(ApiError) as exc:
        client.post("/orders/", json={"x": 1})
    assert exc.value.code == "TABLE_OCCUPIED"
    assert exc.value.http_status == 409
    assert exc.value.message == "Стол занят"


def test_network_retry(monkeypatch):
    from pos.http_client import ApiClient

    client = ApiClient(base_url="http://test")
    calls: list = []

    def fake_request(*a, **kw):
        calls.append(1)
        if len(calls) < 3:
            raise requests.ConnectionError("timeout")
        return _make_response(200, {"data": {"ok": True}})

    monkeypatch.setattr(client.s, "request", fake_request)
    monkeypatch.setattr("pos.http_client.time.sleep", lambda _: None)

    out = client.get("/tables/")
    assert out == {"ok": True}
    assert len(calls) == 3


def test_network_exhausted_raises_network(monkeypatch):
    from pos.http_client import ApiClient, ApiError

    client = ApiClient(base_url="http://test")

    def boom(*a, **kw):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(client.s, "request", boom)
    monkeypatch.setattr("pos.http_client.time.sleep", lambda _: None)

    with pytest.raises(ApiError) as exc:
        client.get("/tables/")
    assert exc.value.code == "NETWORK"
    assert exc.value.http_status == 0


def test_4xx_does_not_retry(monkeypatch):
    """5 ретраев заданы, но при 401 ApiError бросается сразу — никаких лишних запросов."""
    from pos.http_client import ApiClient, ApiError

    client = ApiClient(base_url="http://test")
    calls: list = []

    def fake_request(*a, **kw):
        calls.append(1)
        return _make_response(
            401,
            {"error": {"code": "AUTH_TOKEN_EXPIRED", "message": "expired"}},
        )

    monkeypatch.setattr(client.s, "request", fake_request)

    with pytest.raises(ApiError) as exc:
        client.get("/auth/me/", retries=5)
    assert exc.value.code == "AUTH_TOKEN_EXPIRED"
    assert exc.value.http_status == 401
    assert len(calls) == 1


def test_data_unwrapped_from_response(monkeypatch):
    from pos.http_client import ApiClient

    client = ApiClient(base_url="http://test")
    body = {"data": [{"id": 1}, {"id": 2}], "meta": {"total": 2}}
    monkeypatch.setattr(client.s, "request", lambda *a, **kw: _make_response(200, body))

    out = client.get("/tables/")
    assert out == [{"id": 1}, {"id": 2}]
