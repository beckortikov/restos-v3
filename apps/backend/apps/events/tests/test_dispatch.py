"""Тестируем pg_notify-конец: publish() → второе соединение получает payload.

Используем transactional_db, иначе pg_notify не уйдёт (откатывается).
"""
import json

import psycopg
import pytest
from django.conf import settings


def _conn_kwargs():
    db = settings.DATABASES["default"]
    return {
        "dbname": db.get("NAME"),
        "user": db.get("USER") or None,
        "password": db.get("PASSWORD") or None,
        "host": db.get("HOST") or "127.0.0.1",
        "port": int(db.get("PORT")) if db.get("PORT") else 5432,
    }


@pytest.mark.django_db(transaction=True)
def test_publish_emits_pg_notify():
    from apps.events.dispatch import CHANNEL, publish

    listener = psycopg.connect(**_conn_kwargs(), autocommit=True)
    listener.execute(f"LISTEN {CHANNEL}")

    publish("table.updated", restaurant_id=1, payload={"id": 7, "status": "occupied"})

    received: list[dict] = []
    for n in listener.notifies(timeout=2.0):
        received.append(json.loads(n.payload))
        if received:
            break

    listener.execute(f"UNLISTEN {CHANNEL}")
    listener.close()

    assert received, "pg_notify не доставлен"
    msg = received[0]
    assert msg["type"] == "table.updated"
    assert msg["restaurant_id"] == 1
    assert msg["payload"]["id"] == 7
    assert msg["payload"]["status"] == "occupied"


@pytest.mark.django_db
def test_publish_with_none_restaurant_is_noop():
    from apps.events.dispatch import publish

    publish("x", restaurant_id=None, payload={})  # не должно бросать
