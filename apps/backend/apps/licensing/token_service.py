"""Облако подписывает JWT с current state лицензии.

Формат JWT:
    {
      "iss": "restos-cloud",
      "sub": <restaurant_id>,             # str
      "restaurant_name": "Кафе Анвар",
      "plan": "business",
      "expires_at": "2026-08-10T00:00:00+00:00",  # ISO
      "is_blocked": false,
      "block_reason": "",
      "issued_at": <epoch>,
      "exp": <epoch>,                     # JWT-стандарт, TTL токена
    }

Подпись — HS256 от SECRET_KEY (общий вендорский секрет).
Локальный сервер ресторана:
    1. На старте/раз в N минут вызывает POST /license/issue_token/ с своим
       api_key в заголовке `X-Restaurant-Key`.
    2. Получает JWT, декодирует, верифицирует подпись и TTL.
    3. Сохраняет claims в локальный кэш (модель LicenseTokenCache — Этап 2).
    4. `_enforce_license` читает кэшированные claims вместо локальной License.

Если ресторан не может обратиться в облако > LICENSE_TOKEN_MAX_OFFLINE_DAYS
дней (по умолчанию 7) → POS переходит в read-only по `fetched_at`.
"""
from __future__ import annotations

import time

import jwt
from django.conf import settings

ALGO = "HS256"


def _ttl_seconds() -> int:
    """TTL JWT-токена. Дефолт 1 час — ресторан обновляет каждый цикл."""
    return int(getattr(settings, "LICENSE_TOKEN_TTL_SECONDS", 3600))


def issue_license_token(restaurant) -> tuple[str, int, dict]:
    """Возвращает (token, expires_at_epoch, claims_dict).

    Бросает ValueError если у ресторана нет License-записи в облаке.
    """
    lic = getattr(restaurant, "license", None)
    if lic is None:
        raise ValueError(
            f"Restaurant id={restaurant.id} не имеет License-записи в облаке"
        )
    now = int(time.time())
    exp = now + _ttl_seconds()
    claims = {
        "iss": "restos-cloud",
        "sub": str(int(restaurant.id)),
        "restaurant_name": restaurant.name,
        "plan": lic.plan,
        "license_started_at": lic.started_at.isoformat(),
        "license_expires_at": lic.expires_at.isoformat(),
        "is_blocked": bool(lic.is_blocked),
        "block_reason": lic.block_reason or "",
        "issued_at": now,
        "exp": exp,
    }
    token = jwt.encode(claims, settings.SECRET_KEY, algorithm=ALGO)
    return token, exp, claims


def decode_license_token(token: str) -> dict:
    """Декодирует и валидирует подпись/TTL. Бросает jwt.InvalidTokenError на ошибку.

    Используется ресторанным сервером после получения токена от облака —
    проверяет что подпись валидна (а значит токен не подменён) и не истёк.
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGO])
