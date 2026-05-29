from django.conf import settings
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from common.exceptions import BusinessError
from common.permissions import IsCashier

from .models import PinSession, User
from .serializers import (
    RestaurantSerializer,
    UserAdminSerializer,
    UserSerializer,
)
from .services import authenticate_waiter_by_pin, login_with_pin


class WaiterTokenObtainSerializer(TokenObtainPairSerializer):
    default_error_messages = {
        "no_active_account": "Неверный логин или пароль",
    }

    def validate(self, attrs):
        data = super().validate(attrs)
        user = self.user
        return {
            "data": {
                "access": data["access"],
                "refresh": data["refresh"],
                "user": UserSerializer(user).data,
            }
        }


class WaiterTokenObtainPairView(TokenObtainPairView):
    serializer_class = WaiterTokenObtainSerializer

    def post(self, request, *args, **kwargs):
        try:
            return super().post(request, *args, **kwargs)
        except Exception as exc:
            from rest_framework.exceptions import AuthenticationFailed

            if isinstance(exc, AuthenticationFailed):
                raise BusinessError(
                    "AUTH_INVALID_CREDENTIALS", "Неверный логин или пароль", 401
                ) from exc
            raise


class WaiterTokenRefreshView(TokenRefreshView):
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        response.data = {"data": response.data}
        return response


class PinLoginView(APIView):
    authentication_classes: list = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        pin = (request.data.get("pin") or "").strip()
        restaurant_id = settings.MVP_RESTAURANT_ID
        session = login_with_pin(restaurant_id, pin)
        return Response(
            {
                "data": {
                    "session_token": session.token,
                    "user": UserSerializer(session.user).data,
                    "expires_at": session.expires_at.isoformat(),
                }
            }
        )


class WaiterPinLoginView(APIView):
    """PIN-вход для официанта на планшете → выдаёт JWT (access+refresh).

    Формат ответа совпадает с /auth/login/, поэтому axios-flow на waiter PWA
    (refresh, Bearer) не меняется.
    """

    authentication_classes: list = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        from rest_framework_simplejwt.tokens import RefreshToken

        pin = (request.data.get("pin") or "").strip()
        restaurant_id = settings.MVP_RESTAURANT_ID
        user = authenticate_waiter_by_pin(restaurant_id, pin)
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "data": {
                    "access": str(refresh.access_token),
                    "refresh": str(refresh),
                    "user": UserSerializer(user).data,
                }
            }
        )


class PinLogoutView(APIView):
    def post(self, request):
        if isinstance(request.auth, PinSession):
            request.auth.delete()
        return Response({"data": {"ok": True}})


class MeView(APIView):
    def get(self, request):
        user = request.user
        user_data = UserSerializer(user).data
        # Полный список permission-keys текущего юзера — для скрытия
        # недоступных пунктов в POS-UI.
        user_data["permissions"] = sorted(user.get_permissions_set())
        return Response(
            {
                "data": {
                    "user": user_data,
                    "restaurant": (
                        RestaurantSerializer(user.restaurant).data if user.restaurant else None
                    ),
                }
            }
        )


class UserAdminViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """CRUD пользователей ресторана — frame 20 «Настройки / Пользователи».

    Кассир может управлять кассирами и официантами своего ресторана.
    PIN устанавливается в теле create/update либо через action set_pin."""

    serializer_class = UserAdminSerializer
    pagination_class = None

    def get_permissions(self):
        """GET (list/retrieve) разрешаем всем аутентифицированным юзерам
        ресторана — waiter использует список для assignWaiter-диалога и
        отображения «кто ведёт стол». Write-операции — только cashier+."""
        if self.action in {"list", "retrieve"}:
            return [permissions.IsAuthenticated()]
        return [IsCashier()]

    def get_queryset(self):
        return User.objects.filter(restaurant=self.request.user.restaurant)

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        return Response(
            {"data": UserAdminSerializer(qs, many=True).data, "meta": {"total": qs.count()}}
        )

    def retrieve(self, request, *args, **kwargs):
        return Response({"data": UserAdminSerializer(self.get_object()).data})

    def perform_create(self, serializer):
        serializer.save(restaurant=self.request.user.restaurant)

    def create(self, request, *args, **kwargs):
        from apps.audit.services import log_request

        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        self.perform_create(ser)
        log_request(
            request, "user_create", target=ser.instance,
            payload={
                "username": ser.instance.username,
                "role": ser.instance.role,
            },
        )
        return Response({"data": ser.data}, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        from apps.audit.services import log_request

        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        ser = self.get_serializer(instance, data=request.data, partial=partial)
        ser.is_valid(raise_exception=True)
        ser.save()
        log_request(
            request, "user_update", target=instance,
            payload={k: v for k, v in request.data.items() if k != "pin"},
        )
        return Response({"data": ser.data})

    def destroy(self, request, *args, **kwargs):
        from apps.audit.services import log_request

        instance = self.get_object()
        # Не даём удалить самого себя (иначе можно потерять единственного кассира).
        if instance.id == request.user.id:
            raise BusinessError(
                "USER_SELF_DELETE", "Нельзя удалить самого себя", 400
            )
        log_request(
            request, "user_delete", target=instance,
            payload={"username": instance.username},
        )
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="set_pin")
    def set_pin(self, request, pk=None):
        """Установить новый PIN пользователю. Body: {"pin": "1234"}."""
        from apps.audit.services import log_request

        user = self.get_object()
        pin = (request.data.get("pin") or "").strip()
        if not pin or not pin.isdigit() or not (4 <= len(pin) <= 6):
            raise BusinessError(
                "PIN_INVALID", "PIN должен быть 4-6 цифр", 400
            )
        user.set_pin(pin)
        user.failed_pin_attempts = 0
        user.locked_until = None
        user.save(update_fields=["pin_hash", "failed_pin_attempts", "locked_until"])
        log_request(
            request, "pin_change", target=user,
            payload={"username": user.username},
        )
        return Response({"data": UserAdminSerializer(user).data})


class RestaurantSettingsView(APIView):
    """GET /restaurant/  → данные текущего ресторана пользователя.
    PATCH /restaurant/  → обновить часть полей (только для cashier-роли).

    Поля доступные для PATCH: name, address, phone, receipt_copies,
    pin_lock_timeout_min. Currency / timezone — фиксированы при создании.
    """

    permission_classes = [permissions.IsAuthenticated]

    EDITABLE_FIELDS = {
        "name", "address", "phone",
        "receipt_copies", "pin_lock_timeout_min",
        "kitchen_enabled",
        "manager_override_threshold_tjs",
        "receipt_header_extra", "receipt_footer", "auto_open_cash_drawer",
    }

    def get(self, request):
        if request.user.restaurant is None:
            raise BusinessError("RESTAURANT_NOT_FOUND", "Ресторан не задан", 404)
        return Response(
            {"data": RestaurantSerializer(request.user.restaurant).data}
        )

    def patch(self, request):
        from apps.audit.services import log_request

        if not (request.user.is_authenticated and request.user.role == "cashier"):
            raise BusinessError(
                "ROLE_NOT_ALLOWED", "Только кассир может менять настройки ресторана",
                403,
            )
        rest = request.user.restaurant
        if rest is None:
            raise BusinessError("RESTAURANT_NOT_FOUND", "Ресторан не задан", 404)

        changed = {}
        for k, v in request.data.items():
            if k not in self.EDITABLE_FIELDS:
                continue
            # Валидация числовых
            if k == "receipt_copies":
                try:
                    iv = int(v)
                except (TypeError, ValueError):
                    raise BusinessError(
                        "INVALID_TRANSITION",
                        "receipt_copies должен быть целым 1-5", 422,
                    )
                if not (1 <= iv <= 5):
                    raise BusinessError(
                        "INVALID_TRANSITION",
                        "receipt_copies должен быть 1-5", 422,
                    )
                v = iv
            if k in ("kitchen_enabled", "auto_open_cash_drawer"):
                if isinstance(v, bool):
                    pass
                elif isinstance(v, str):
                    v = v.lower() in ("true", "1", "yes", "on")
                else:
                    v = bool(v)
            if k == "pin_lock_timeout_min":
                try:
                    iv = int(v)
                except (TypeError, ValueError):
                    raise BusinessError(
                        "INVALID_TRANSITION",
                        "pin_lock_timeout_min должен быть целым", 422,
                    )
                if iv < 1:
                    raise BusinessError(
                        "INVALID_TRANSITION",
                        "pin_lock_timeout_min должен быть >= 1", 422,
                    )
                v = iv
            old = getattr(rest, k)
            if old != v:
                setattr(rest, k, v)
                changed[k] = {"old": str(old), "new": str(v)}
        if changed:
            rest.save(update_fields=list(changed.keys()))
            log_request(
                request, "settings_update", target=rest,
                payload={"changed": changed},
            )
        return Response(
            {"data": RestaurantSerializer(rest).data}
        )
