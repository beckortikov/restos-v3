from uuid import uuid4

import pytest

pytestmark = pytest.mark.django_db


def _pin_token(api_client, cashier):
    return api_client.post("/api/v1/auth/pin/", {"pin": "1234"}, format="json").json()[
        "data"
    ]["session_token"]


def _jwt(api_client, waiter):
    return api_client.post(
        "/api/v1/auth/login/",
        {"username": "waiter1", "password": "waiter-pass"},
        format="json",
    ).json()["data"]["access"]


def test_printers_list_for_cashier(api_client, cashier, printer):
    token = _pin_token(api_client, cashier)
    resp = api_client.get(
        "/api/v1/printing/printers/", HTTP_AUTHORIZATION=f"PIN {token}"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["name"] == "Касса"


def test_printers_list_forbidden_for_waiter(api_client, waiter, printer):
    access = _jwt(api_client, waiter)
    resp = api_client.get(
        "/api/v1/printing/printers/", HTTP_AUTHORIZATION=f"Bearer {access}"
    )
    assert resp.status_code == 403


def test_print_job_retrieve(api_client, cashier, closed_order):
    token = _pin_token(api_client, cashier)
    _, job = closed_order
    resp = api_client.get(
        f"/api/v1/printing/jobs/{job.id}/", HTTP_AUTHORIZATION=f"PIN {token}"
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["id"] == job.id
    assert body["status"] == "pending"
    assert body["retries"] == 0


def test_print_job_retry_resets_status(api_client, cashier, closed_order):
    from apps.printing.models import PrintJobStatus

    token = _pin_token(api_client, cashier)
    _, job = closed_order
    job.status = PrintJobStatus.FAILED
    job.retries = 2
    job.error = "boom"
    job.save()

    resp = api_client.post(
        f"/api/v1/printing/jobs/{job.id}/retry/",
        {}, format="json",
        HTTP_AUTHORIZATION=f"PIN {token}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()["data"]
    assert body["status"] == "pending"
    assert body["error"] == ""

    job.refresh_from_db()
    assert job.status == PrintJobStatus.PENDING


def test_print_job_retry_idempotency_required(api_client, cashier, closed_order):
    token = _pin_token(api_client, cashier)
    _, job = closed_order
    resp = api_client.post(
        f"/api/v1/printing/jobs/{job.id}/retry/",
        {}, format="json",
        HTTP_AUTHORIZATION=f"PIN {token}",
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_print_job_retry_done_no_op(api_client, cashier, closed_order):
    from apps.printing.models import PrintJobStatus

    token = _pin_token(api_client, cashier)
    _, job = closed_order
    job.status = PrintJobStatus.DONE
    job.save()

    resp = api_client.post(
        f"/api/v1/printing/jobs/{job.id}/retry/",
        {}, format="json",
        HTTP_AUTHORIZATION=f"PIN {token}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert resp.status_code == 200
    job.refresh_from_db()
    assert job.status == PrintJobStatus.DONE


def test_print_job_cancel_pending_marks_dead(api_client, cashier, closed_order):
    """Кассир может отменить pending job — статус → DEAD, worker не возьмёт."""
    from apps.printing.models import PrintJobStatus

    token = _pin_token(api_client, cashier)
    _, job = closed_order
    assert job.status == PrintJobStatus.PENDING

    resp = api_client.post(
        f"/api/v1/printing/jobs/{job.id}/cancel/",
        {}, format="json",
        HTTP_AUTHORIZATION=f"PIN {token}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()["data"]
    assert body["status"] == "dead"
    job.refresh_from_db()
    assert job.status == PrintJobStatus.DEAD
    assert job.finished_at is not None
    assert "cancelled by user" in (job.error or "")


def test_print_job_cancel_failed_marks_dead(api_client, cashier, closed_order):
    """Cancel failed job: тоже DEAD, retry больше не будет."""
    from apps.printing.models import PrintJobStatus

    token = _pin_token(api_client, cashier)
    _, job = closed_order
    job.status = PrintJobStatus.FAILED
    job.error = "previous error"
    job.save()

    resp = api_client.post(
        f"/api/v1/printing/jobs/{job.id}/cancel/",
        {}, format="json",
        HTTP_AUTHORIZATION=f"PIN {token}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert resp.status_code == 200
    job.refresh_from_db()
    assert job.status == PrintJobStatus.DEAD
    assert "previous error" in job.error
    assert "cancelled by user" in job.error


def test_print_job_cancel_printing_returns_409(api_client, cashier, closed_order):
    """Активный PRINTING job нельзя отменить — worker уже отправляет."""
    from apps.printing.models import PrintJobStatus

    token = _pin_token(api_client, cashier)
    _, job = closed_order
    job.status = PrintJobStatus.PRINTING
    job.save()

    resp = api_client.post(
        f"/api/v1/printing/jobs/{job.id}/cancel/",
        {}, format="json",
        HTTP_AUTHORIZATION=f"PIN {token}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "JOB_IN_PROGRESS"
    job.refresh_from_db()
    assert job.status == PrintJobStatus.PRINTING


def test_print_job_cancel_done_idempotent(api_client, cashier, closed_order):
    """Cancel уже DONE job — idempotent 200, без изменений."""
    from apps.printing.models import PrintJobStatus

    token = _pin_token(api_client, cashier)
    _, job = closed_order
    job.status = PrintJobStatus.DONE
    job.save()

    resp = api_client.post(
        f"/api/v1/printing/jobs/{job.id}/cancel/",
        {}, format="json",
        HTTP_AUTHORIZATION=f"PIN {token}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert resp.status_code == 200
    job.refresh_from_db()
    assert job.status == PrintJobStatus.DONE
