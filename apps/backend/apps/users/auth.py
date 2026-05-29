from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from .models import PinSession


class PinSessionAuthentication(BaseAuthentication):
    keyword = b"pin"

    def authenticate(self, request):
        header = get_authorization_header(request).split()
        if not header or header[0].lower() != self.keyword:
            return None
        if len(header) != 2:
            raise AuthenticationFailed({"code": "AUTH_TOKEN_EXPIRED", "message": "Invalid PIN header"})

        token = header[1].decode()
        try:
            session = PinSession.objects.select_related("user", "user__restaurant").get(token=token)
        except PinSession.DoesNotExist as exc:
            raise AuthenticationFailed(
                {"code": "AUTH_TOKEN_EXPIRED", "message": "PIN-сессия не найдена"}
            ) from exc

        if not session.is_valid():
            session.delete()
            raise AuthenticationFailed(
                {"code": "AUTH_TOKEN_EXPIRED", "message": "PIN-сессия истекла"}
            )

        if not session.user.is_active:
            raise AuthenticationFailed(
                {"code": "PERMISSION_DENIED", "message": "Учётка деактивирована"}
            )

        timeout = session.user.restaurant.pin_lock_timeout_min if session.user.restaurant else 30
        session.extend(timeout)
        return (session.user, session)

    def authenticate_header(self, request):
        return 'PIN realm="restos"'


class TokenQueryParamAuthentication(BaseAuthentication):
    """Fallback для SSE: браузерный EventSource не умеет ставить заголовки,
    поэтому token приходит в `?token=...`. Действует только на /events/.

    Сначала пробуем JWT, потом PIN-сессию."""

    ALLOWED_PATHS = ("/api/v1/events/",)

    def authenticate(self, request):
        path = getattr(request, "path", "")
        if not any(path.startswith(p) for p in self.ALLOWED_PATHS):
            return None
        token = request.GET.get("token")
        if not token:
            return None

        jwt = JWTAuthentication()
        try:
            validated = jwt.get_validated_token(token)
            user = jwt.get_user(validated)
            return (user, validated)
        except (InvalidToken, TokenError, AuthenticationFailed):
            pass

        try:
            session = PinSession.objects.select_related("user", "user__restaurant").get(
                token=token
            )
        except PinSession.DoesNotExist as exc:
            raise AuthenticationFailed(
                {"code": "AUTH_TOKEN_EXPIRED", "message": "Невалидный token"}
            ) from exc

        if not session.is_valid():
            session.delete()
            raise AuthenticationFailed(
                {"code": "AUTH_TOKEN_EXPIRED", "message": "PIN-сессия истекла"}
            )
        if not session.user.is_active:
            raise AuthenticationFailed(
                {"code": "PERMISSION_DENIED", "message": "Учётка деактивирована"}
            )
        return (session.user, session)
