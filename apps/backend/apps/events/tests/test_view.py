"""SSE view: заголовки, начальные кадры (:ok + resync), фильтрация по роли,
JWT-аутентификация заголовком и `?token=` query param."""
from itertools import islice

import pytest

pytestmark = pytest.mark.django_db


def _jwt(api_client, waiter):
    return api_client.post(
        "/api/v1/auth/login/",
        {"username": "waiter1", "password": "waiter-pass"},
        format="json",
    ).json()["data"]["access"]


def _read_initial(resp, n_chunks: int = 3) -> str:
    """Читает первые n_chunks из streaming_content и закрывает соединение.
    Без islice/break зависнет на conn.notifies(timeout=...)."""
    chunks = []
    for chunk in islice(resp.streaming_content, n_chunks):
        chunks.append(chunk)
    resp.close()
    return b"".join(chunks).decode("utf-8")


def test_events_unauthorized(api_client):
    resp = api_client.get("/api/v1/events/")
    assert resp.status_code == 401


def test_events_with_jwt_header(api_client, waiter):
    access = _jwt(api_client, waiter)
    resp = api_client.get(
        "/api/v1/events/", HTTP_AUTHORIZATION=f"Bearer {access}"
    )
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/event-stream")
    assert resp["Cache-Control"] == "no-cache"
    assert resp["X-Accel-Buffering"] == "no"

    body = _read_initial(resp, n_chunks=2)
    assert ":ok" in body
    assert "event: resync" in body
    assert "data: {}" in body


def test_events_with_token_query_param(api_client, waiter):
    access = _jwt(api_client, waiter)
    resp = api_client.get(f"/api/v1/events/?token={access}")
    assert resp.status_code == 200
    body = _read_initial(resp, n_chunks=2)
    assert "event: resync" in body


def test_events_with_pin_token(api_client, cashier):
    pin = api_client.post("/api/v1/auth/pin/", {"pin": "1234"}, format="json").json()[
        "data"
    ]["session_token"]
    resp = api_client.get(
        "/api/v1/events/", HTTP_AUTHORIZATION=f"PIN {pin}"
    )
    assert resp.status_code == 200
    body = _read_initial(resp, n_chunks=2)
    assert "event: resync" in body


def test_filter_allows_cashier_to_see_print_job():
    from apps.events.views import _allowed

    class _U:
        role = "cashier"
        id = 1

    assert _allowed(
        {"type": "print_job.updated", "payload": {"id": 1}}, _U()
    ) is True


def test_filter_hides_print_job_from_waiter():
    from apps.events.views import _allowed

    class _U:
        role = "waiter"
        id = 1

    assert _allowed(
        {"type": "print_job.updated", "payload": {"id": 1}}, _U()
    ) is False


def test_filter_waiter_sees_only_own_orders():
    from apps.events.views import _allowed

    class _U:
        role = "waiter"
        id = 5

    assert _allowed(
        {"type": "order.updated", "payload": {"id": 1, "waiter_id": 5}}, _U()
    ) is True
    assert _allowed(
        {"type": "order.updated", "payload": {"id": 2, "waiter_id": 99}}, _U()
    ) is False
    # waiter_id=None — это создание/системное событие, пускаем
    assert _allowed(
        {"type": "order.created", "payload": {"id": 3, "waiter_id": None}}, _U()
    ) is True


def test_filter_cashier_sees_all_orders():
    from apps.events.views import _allowed

    class _U:
        role = "cashier"
        id = 1

    assert _allowed(
        {"type": "order.updated", "payload": {"id": 99, "waiter_id": 42}}, _U()
    ) is True
