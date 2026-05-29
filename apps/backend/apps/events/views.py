import json
import logging
import time

import psycopg
from django.conf import settings
from django.http import StreamingHttpResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import BaseRenderer
from rest_framework.views import APIView

from .dispatch import CHANNEL


class EventStreamRenderer(BaseRenderer):
    """SSE-«рендерер»: нужен только чтобы пройти DRF content negotiation —
    реальное тело даёт StreamingHttpResponse, render() не вызывается."""

    media_type = "text/event-stream"
    format = "sse"
    charset = "utf-8"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return b""

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 15.0
NOTIFY_POLL_TIMEOUT = 5.0


def _build_psycopg_connect_kwargs() -> dict:
    db = settings.DATABASES["default"]
    return {
        "dbname": db.get("NAME"),
        "user": db.get("USER") or None,
        "password": db.get("PASSWORD") or None,
        "host": db.get("HOST") or "127.0.0.1",
        "port": int(db.get("PORT")) if db.get("PORT") else 5432,
    }


def _allowed(msg: dict, user) -> bool:
    """Минимальная фильтрация по ролям. Точные данные клиент всё равно тянет
    через REST с правами; здесь убираем только шум."""
    t = msg.get("type", "")
    p = msg.get("payload", {}) or {}
    role = getattr(user, "role", None)

    if role == "waiter":
        if t == "print_job.updated":
            return False
        if t in {"order.created", "order.updated"}:
            wid = p.get("waiter_id")
            if wid not in (None, user.id):
                return False
    return True


def _format_event(event_id: int, msg: dict) -> str:
    return (
        f"id: {event_id}\n"
        f"event: {msg['type']}\n"
        f"data: {json.dumps(msg.get('payload', {}), ensure_ascii=False)}\n\n"
    )


def event_stream(user, restaurant_id: int):
    """Генератор text/event-stream. Открывает свой psycopg-коннект, LISTEN,
    стримит фильтрованные события и heartbeat'ы."""
    last_id = 0
    conn = None
    try:
        conn = psycopg.connect(**_build_psycopg_connect_kwargs(), autocommit=True)
        conn.execute(f"LISTEN {CHANNEL}")

        yield ":ok\n\n"
        # Синтетический resync — клиент сразу перезапрашивает базовое состояние.
        last_id += 1
        yield f"id: {last_id}\nevent: resync\ndata: {{}}\n\n"

        last_heartbeat = time.monotonic()
        while True:
            now = time.monotonic()
            wait = max(0.5, HEARTBEAT_INTERVAL - (now - last_heartbeat))
            wait = min(wait, NOTIFY_POLL_TIMEOUT)

            got_any = False
            for n in conn.notifies(timeout=wait):
                got_any = True
                try:
                    msg = json.loads(n.payload)
                except (TypeError, json.JSONDecodeError):
                    continue
                if int(msg.get("restaurant_id", -1)) != int(restaurant_id):
                    continue
                if not _allowed(msg, user):
                    continue
                last_id += 1
                yield _format_event(last_id, msg)

            if not got_any and (time.monotonic() - last_heartbeat) >= HEARTBEAT_INTERVAL:
                yield ":heartbeat\n\n"
                last_heartbeat = time.monotonic()
    except GeneratorExit:
        return
    except Exception as exc:
        logger.exception("SSE stream error: %s", exc)
        return
    finally:
        if conn is not None:
            try:
                conn.execute(f"UNLISTEN {CHANNEL}")
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass


class EventStreamView(APIView):
    permission_classes = [IsAuthenticated]
    renderer_classes = [EventStreamRenderer]

    def get(self, request):
        user = request.user
        if not getattr(user, "restaurant_id", None):
            from common.exceptions import BusinessError

            raise BusinessError(
                "PERMISSION_DENIED", "У пользователя нет ресторана", 403
            )

        response = StreamingHttpResponse(
            event_stream(user, user.restaurant_id),
            content_type="text/event-stream; charset=utf-8",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response
