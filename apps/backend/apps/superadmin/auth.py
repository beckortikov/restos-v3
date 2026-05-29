"""JWT-аутентификация для Super-Admin.

В отличие от PIN-сессий (которые привязаны к Restaurant), super-admin не
имеет ресторана и должен иметь возможность работать со всеми клиентами
платформы. JWT — самодостаточный токен, ресторан-агностичный.

Токен подписан `settings.SECRET_KEY`, TTL — `SUPERADMIN_JWT_TTL_HOURS`
(дефолт 12 часов). Внутри: {sub: user_id, is_superuser: True, exp: epoch}.
"""
from __future__ import annotations

import time

import jwt
from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from apps.users.models import User

ALGO = "HS256"


def _ttl_seconds() -> int:
    return int(getattr(settings, "SUPERADMIN_JWT_TTL_HOURS", 12)) * 3600


def issue_token(user: User) -> tuple[str, int]:
    """Возвращает (token, expires_at_epoch). Бросает ValueError если user не SA."""
    if not user.is_superuser:
        raise ValueError("Только пользователи is_superuser=True могут получать SA-токен")
    now = int(time.time())
    exp = now + _ttl_seconds()
    payload = {
        # sub должен быть строкой по PyJWT 2.x (RFC 7519 рекомендация).
        "sub": str(int(user.id)),
        "is_superuser": True,
        "iat": now,
        "exp": exp,
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGO)
    return token, exp


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGO])
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationFailed("SA-токен истёк") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationFailed("Невалидный SA-токен") from exc


class SuperAdminJWTAuthentication(BaseAuthentication):
    """Парсит `Authorization: SA <token>` и возвращает (User, payload)."""

    keyword = "SA"

    def authenticate(self, request):
        auth = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth.startswith(f"{self.keyword} "):
            return None
        token = auth[len(self.keyword) + 1:].strip()
        if not token:
            return None
        payload = decode_token(token)
        if not payload.get("is_superuser"):
            raise AuthenticationFailed("Токен не имеет SA-привилегий")
        try:
            user_id = int(payload["sub"])
        except (TypeError, ValueError) as exc:
            raise AuthenticationFailed("Невалидный subject в токене") from exc
        try:
            user = User.objects.get(id=user_id, is_superuser=True, is_active=True)
        except User.DoesNotExist as exc:
            raise AuthenticationFailed("SA-пользователь не найден / деактивирован") from exc
        return (user, payload)

    def authenticate_header(self, request):
        return f'{self.keyword} realm="superadmin"'
