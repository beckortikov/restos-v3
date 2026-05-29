import json
import logging

from django.db import connection

CHANNEL = "restos_events"

logger = logging.getLogger(__name__)


def publish(event_type: str, restaurant_id: int | None, payload: dict) -> None:
    """Шлёт событие в Postgres LISTEN/NOTIFY канал.

    pg_notify запоминает сообщения до COMMIT текущей транзакции — поэтому если
    save() произошёл внутри @transaction.atomic, событие уйдёт только после
    успешного коммита. При rollback события не будет — это правильное поведение."""
    if restaurant_id is None:
        return
    msg = json.dumps(
        {"type": event_type, "restaurant_id": int(restaurant_id), "payload": payload},
        default=str,
        ensure_ascii=False,
    )
    try:
        with connection.cursor() as c:
            c.execute("SELECT pg_notify(%s, %s)", [CHANNEL, msg])
    except Exception as exc:
        logger.warning("publish(%s) failed: %s", event_type, exc)
