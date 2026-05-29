from django.conf import settings
from django.utils import timezone
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.models import Restaurant
from common.exceptions import BusinessError

from .models import License
from .token_service import issue_license_token


class LicenseStatusView(APIView):
    """GET /license/status/ — компактный статус лицензии для POS-баннера.

    Возвращается даже когда лицензия истекла (middleware пропускает этот endpoint),
    чтобы POS мог показать «лицензия истекла» вместо абстрактной 402-ошибки.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from .sync import (
            evaluate_cached_status,
            get_cached_license,
            is_restaurant_mode,
        )

        rest = getattr(request.user, "restaurant", None)
        if rest is None:
            return Response({"data": {"status": "no_restaurant"}})

        # На restaurant-инстансе читаем кэш токена из cloud.
        if is_restaurant_mode():
            cache = get_cached_license()
            code, msg = evaluate_cached_status()
            if cache is None:
                return Response({
                    "data": {
                        "status": "missing",
                        "message": msg,
                        "source": "cloud_cache",
                    }
                })
            return Response({
                "data": {
                    "status": code,  # ok / blocked / expired / stale
                    "plan": cache.plan,
                    "expires_at": (
                        cache.expires_at.isoformat()
                        if cache.expires_at else None
                    ),
                    "is_blocked": cache.is_blocked,
                    "block_reason": cache.block_reason,
                    "fetched_at": cache.fetched_at.isoformat(),
                    "is_writable": code == "ok",
                    "message": msg,
                    "source": "cloud_cache",
                }
            })

        # Cloud-инстанс: читаем мастер-License.
        lic = getattr(rest, "license", None)
        if lic is None:
            return Response({
                "data": {
                    "status": "missing",
                    "message": "Лицензия не выдана. Обратитесь к поставщику.",
                    "source": "master",
                }
            })
        return Response({
            "data": {
                "status": lic.status,
                "plan": lic.plan,
                "started_at": lic.started_at.isoformat(),
                "expires_at": lic.expires_at.isoformat(),
                "grace_until": lic.grace_until.isoformat(),
                "is_blocked": lic.is_blocked,
                "block_reason": lic.block_reason,
                "days_to_expiry": lic.days_to_expiry,
                "days_left": lic.days_left,
                "is_writable": lic.is_writable,
                "source": "master",
            }
        })


class HeartbeatView(APIView):
    """POST /heartbeat/  body={"app_version": "1.2.3"} — ping от POS.

    Обновляет `Restaurant.last_heartbeat_at` и `app_version`. Используется
    super-admin'ом чтобы видеть какие рестораны активны прямо сейчас.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        rest = getattr(request.user, "restaurant", None)
        if rest is None:
            return Response({"data": {"ok": False}}, status=200)
        rest.last_heartbeat_at = timezone.now()
        ver = (request.data.get("app_version") or "")[:32]
        if ver:
            rest.app_version = ver
        rest.save(update_fields=["last_heartbeat_at", "app_version"])
        return Response({"data": {"ok": True, "ts": rest.last_heartbeat_at.isoformat()}})


class LicenseActivateView(APIView):
    """SA-7 — POST /api/v1/license/activate/  Привязка лицензии к машине.

    Body: { "license_key": str, "hardware_uuid": str }

    Логика:
    - Найти License по license_key. Нет → 404 LICENSE_NOT_FOUND.
    - is_blocked → 403 LICENSE_BLOCKED.
    - Если License.hardware_uuid == "" → первая активация: сохраняем UUID + activated_at.
    - Если License.hardware_uuid == UUID из body → повторная активация (тот же ПК).
    - Иначе → 403 MACHINE_MISMATCH.

    Доступен без user-auth (юзер ещё не залогинен в POS).
    """

    authentication_classes: list = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        key = (request.data.get("license_key") or "").strip()
        hwid = (request.data.get("hardware_uuid") or "").strip()
        if not key:
            raise BusinessError("INVALID_VALUE", "Введите ключ активации", 400)
        if not hwid or len(hwid) < 32 or hwid.replace("-", "").replace("0", "") == "":
            raise BusinessError(
                "INVALID_VALUE",
                "Не удалось определить ID этой машины (HWID). "
                "Запустите POS как администратор и попробуйте ещё раз.",
                400,
            )
        try:
            lic = License.objects.select_related("restaurant").get(license_key=key)
        except License.DoesNotExist as exc:
            raise BusinessError(
                "LICENSE_NOT_FOUND", "Ключ не найден. Проверьте корректность.", 404,
            ) from exc

        if lic.is_blocked:
            raise BusinessError(
                "LICENSE_BLOCKED",
                f"Лицензия заблокирована: {lic.block_reason or 'обратитесь к поставщику'}",
                403,
            )

        if not lic.hardware_uuid:
            # Первая активация
            lic.hardware_uuid = hwid
            lic.activated_at = timezone.now()
            lic.save(update_fields=["hardware_uuid", "activated_at", "updated_at"])
            first = True
        elif lic.hardware_uuid == hwid:
            # Повторная активация на той же машине — OK
            first = False
        else:
            raise BusinessError(
                "MACHINE_MISMATCH",
                "Лицензия привязана к другой машине. Обратитесь к поставщику "
                "для перепривязки.",
                403,
            )

        # Audit-log (без user — анонимно от машины)
        try:
            from apps.audit.services import audit_log
            audit_log(
                None, "license_activate", target=lic,
                payload={
                    "license_key": key[:8] + "…",
                    "hardware_uuid": hwid,
                    "first_activation": first,
                },
            )
        except Exception:
            pass

        return Response({
            "data": {
                "ok": True,
                "first_activation": first,
                "restaurant_name": lic.restaurant.name,
                "plan": lic.plan,
                "expires_at": lic.expires_at.isoformat(),
            }
        })


class IssueLicenseTokenView(APIView):
    """POST /api/v1/license/issue_token/ — облако подписывает JWT с claims лицензии.

    Auth — заголовок `X-Restaurant-Key: <secret>`, который сервер ресторана
    хранит в env. Это НЕ user-auth (нет user-сессии), это machine-to-machine.

    Body (опционально): `{"app_version": "1.2.3"}` — попутно обновляем
    last_heartbeat_at + app_version.

    Доступен только когда SUPERADMIN_ENABLED=True (= это vendor cloud).
    На ресторанном локальном сервере endpoint вернёт 404 — иначе кассир
    мог бы сам выпустить себе токен на любой ресторан в локальной БД.
    """

    authentication_classes: list = []  # никаких user-сессий
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        # Гейт по флагу: вообще не выдаём токены на restaurant-инстансе.
        if not getattr(settings, "SUPERADMIN_ENABLED", False):
            raise BusinessError(
                "NOT_AVAILABLE",
                "Endpoint доступен только на vendor cloud",
                404,
            )

        api_key = request.META.get("HTTP_X_RESTAURANT_KEY", "").strip()
        if not api_key:
            raise BusinessError(
                "AUTH_REQUIRED",
                "Требуется заголовок X-Restaurant-Key",
                401,
            )

        try:
            restaurant = Restaurant.objects.select_related("license").get(api_key=api_key)
        except Restaurant.DoesNotExist as exc:
            raise BusinessError("AUTH_INVALID", "Неизвестный api_key", 401) from exc

        # Попутно фиксируем heartbeat — облако видит когда ресторанный сервер живой.
        now = timezone.now()
        restaurant.last_heartbeat_at = now
        ver = (request.data.get("app_version") or "")[:32]
        update_fields = ["last_heartbeat_at"]
        if ver:
            restaurant.app_version = ver
            update_fields.append("app_version")
        restaurant.save(update_fields=update_fields)

        try:
            token, exp, claims = issue_license_token(restaurant)
        except ValueError as exc:
            raise BusinessError(
                "NO_LICENSE",
                str(exc),
                422,
            ) from exc

        return Response({
            "data": {
                "token": token,
                "expires_at": exp,
                "claims": claims,
            }
        })
