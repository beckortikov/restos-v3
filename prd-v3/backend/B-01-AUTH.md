# B-01 — Аутентификация

Две схемы аутентификации работают параллельно:

| Схема | Кто | Как |
|---|---|---|
| **JWT** (SimpleJWT) | Waiter PWA | `username` + `password` → access (8h) + refresh (30d) |
| **PIN-сессия** | Cashier PySide | `pin` (4–6 цифр) → `session_token` с TTL = `Restaurant.pin_lock_timeout_min` (default 30 мин). Продлевается при каждом запросе. |

## Модели

```python
# apps/users/models.py

class UserRole(models.TextChoices):
    CASHIER = "cashier", "Кассир"
    WAITER  = "waiter",  "Официант"

class User(AbstractBaseUser):
    restaurant   = models.ForeignKey("Restaurant", on_delete=models.CASCADE)
    username     = models.CharField(max_length=64, unique=True)
    full_name    = models.CharField(max_length=128)
    role         = models.CharField(max_length=16, choices=UserRole.choices)
    pin_hash     = models.CharField(max_length=128, blank=True)   # bcrypt
    password     = models.CharField(max_length=128, blank=True)   # стандартное Django-хэширование
    is_active    = models.BooleanField(default=True)
    failed_pin_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = "username"

    def check_pin(self, raw_pin: str) -> bool:
        return bcrypt.checkpw(raw_pin.encode(), self.pin_hash.encode())

    def set_pin(self, raw_pin: str) -> None:
        self.pin_hash = bcrypt.hashpw(raw_pin.encode(), bcrypt.gensalt()).decode()


class PinSession(models.Model):
    user        = models.ForeignKey(User, on_delete=models.CASCADE, related_name="pin_sessions")
    token       = models.CharField(max_length=64, unique=True, db_index=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    expires_at  = models.DateTimeField(db_index=True)

    def is_valid(self) -> bool:
        return self.expires_at > timezone.now()

    def extend(self, minutes: int):
        self.expires_at = timezone.now() + timedelta(minutes=minutes)
        self.save(update_fields=["expires_at"])
```

## PIN-аутентификатор DRF

```python
# apps/users/auth.py

class PinSessionAuthentication(BaseAuthentication):
    keyword = "PIN"

    def authenticate(self, request):
        header = get_authorization_header(request).split()
        if not header or header[0].lower() != b"pin":
            return None
        if len(header) != 2:
            raise AuthenticationFailed("Invalid PIN header")
        token = header[1].decode()
        try:
            session = PinSession.objects.select_related("user", "user__restaurant").get(token=token)
        except PinSession.DoesNotExist:
            raise AuthenticationFailed({"code": "AUTH_TOKEN_EXPIRED"})
        if not session.is_valid():
            raise AuthenticationFailed({"code": "AUTH_TOKEN_EXPIRED"})
        # auto-extend
        session.extend(session.user.restaurant.pin_lock_timeout_min)
        return (session.user, session)

    def authenticate_header(self, request):
        return 'PIN realm="restos"'
```

## Сервисы

```python
# apps/users/services.py

LOCK_THRESHOLD = 5
LOCK_DURATION_MIN = 15

def login_with_pin(restaurant_id: int, raw_pin: str) -> PinSession:
    user = User.objects.filter(restaurant_id=restaurant_id, role="cashier", is_active=True).first()
    # MVP: 1 кассир на ресторан; в будущем добавим выбор сотрудника

    if user.locked_until and user.locked_until > timezone.now():
        raise BusinessError("AUTH_INVALID_PIN", "Учётка временно заблокирована", 401)

    if not user or not user.check_pin(raw_pin):
        if user:
            user.failed_pin_attempts += 1
            if user.failed_pin_attempts >= LOCK_THRESHOLD:
                user.locked_until = timezone.now() + timedelta(minutes=LOCK_DURATION_MIN)
                user.failed_pin_attempts = 0
            user.save(update_fields=["failed_pin_attempts", "locked_until"])
        raise BusinessError("AUTH_INVALID_PIN", "Неверный PIN", 401)

    user.failed_pin_attempts = 0
    user.locked_until = None
    user.save(update_fields=["failed_pin_attempts", "locked_until"])

    token = secrets.token_urlsafe(32)
    expires = timezone.now() + timedelta(minutes=user.restaurant.pin_lock_timeout_min)
    return PinSession.objects.create(user=user, token=token, expires_at=expires)
```

## Views и URLs

```python
# apps/users/views.py

class PinLoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        pin = request.data.get("pin")
        restaurant_id = settings.MVP_RESTAURANT_ID    # single-tenant
        session = login_with_pin(restaurant_id, pin)
        return Response({
            "data": {
                "session_token": session.token,
                "user": UserSerializer(session.user).data,
                "expires_at": session.expires_at.isoformat(),
            }
        })


class PinLogoutView(APIView):
    def post(self, request):
        if isinstance(request.auth, PinSession):
            request.auth.delete()
        return Response({"data": {"ok": True}})


class MeView(APIView):
    def get(self, request):
        return Response({"data": {
            "user": UserSerializer(request.user).data,
            "restaurant": RestaurantSerializer(request.user.restaurant).data,
        }})
```

```python
# apps/users/urls.py
urlpatterns = [
    path("auth/login/",       TokenObtainPairView.as_view()),       # JWT для PWA
    path("auth/refresh/",     TokenRefreshView.as_view()),
    path("auth/pin/",         PinLoginView.as_view()),
    path("auth/pin/logout/",  PinLogoutView.as_view()),
    path("auth/me/",          MeView.as_view()),
]
```

## Permission-классы по эндпоинтам

| Эндпоинт | Permissions |
|---|---|
| `auth/*` | `AllowAny` |
| `tables/*` (read) | `IsAuthenticated` (cashier или waiter) |
| `tables/*/open/` | `IsWaiter` |
| `menu/*` | `IsAuthenticated` |
| `orders/` (POST) | `IsWaiter` |
| `orders/{id}/add_items/` | `IsWaiter` |
| `orders/{id}/cancel_item/` | `IsWaiter \| IsCashier` |
| `orders/{id}/request_bill/` | `IsWaiter` |
| `orders/{id}/close/` | `IsCashier` |
| `orders/{id}/cancel/` | `IsWaiter \| IsCashier` |
| `orders/`, `orders/{id}/` (GET) | `IsAuthenticated` (waiter видит только свои, cashier — все) |
| `events/` (GET, SSE) | `IsAuthenticated` (фильтрация payload по роли — см. B-06) |
| `printing/*` | `IsCashier` |

## Авто-блокировка кассира

Сервер не следит за активностью UI — клиент сам отслеживает бездействие и снова показывает PIN-экран. PinSession при этом продолжает жить (его TTL продлевается только при HTTP-запросах). При повторном вводе PIN сервер либо валидирует тот же session_token (если он ещё не истёк), либо выдаёт новый.
