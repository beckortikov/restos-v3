"""Permissions / Manager role: has_perm_key, ROLE_DEFAULTS, manager-override."""
import pytest

pytestmark = pytest.mark.django_db


def _pin(api_client, pin: str):
    return api_client.post(
        "/api/v1/auth/pin/", {"pin": pin}, format="json"
    ).json()["data"]["session_token"]


# -------- ROLE_DEFAULT_PERMISSIONS --------


def test_cashier_default_permissions(cashier):
    perms = cashier.get_permissions_set()
    assert "orders.create" in perms
    assert "orders.cancel" in perms
    assert "shifts.open" in perms
    assert "settings.users" not in perms  # users — для менеджера
    assert "settings.audit" not in perms


def test_waiter_default_permissions(waiter):
    perms = waiter.get_permissions_set()
    assert "orders.create" in perms
    assert "menu.view" in perms
    assert "shifts.open" not in perms
    assert "orders.refund" not in perms


def test_manager_has_all_permissions(restaurant, db):
    from apps.users.models import ALL_PERMISSIONS, User, UserRole

    m = User.objects.create_user(
        username="mgr", password="x", full_name="Менеджер",
        role=UserRole.MANAGER, restaurant=restaurant,
    )
    perms = m.get_permissions_set()
    for key in ALL_PERMISSIONS:
        assert key in perms


def test_user_permissions_override_role_defaults(cashier):
    """Если User.permissions не пуст — используется как override полностью."""
    cashier.permissions = ["menu.view"]
    cashier.save()
    perms = cashier.get_permissions_set()
    assert perms == {"menu.view"}
    # Дефолтные права кассира больше не работают
    assert "orders.create" not in perms


def test_has_perm_key_manager_always_true(restaurant, db):
    from apps.users.models import User, UserRole

    m = User.objects.create_user(
        username="mgr2", password="x", full_name="M",
        role=UserRole.MANAGER, restaurant=restaurant,
        permissions=[],  # даже с пустым override
    )
    assert m.has_perm_key("any.unknown.key")


def test_has_perm_key_cashier(cashier):
    assert cashier.has_perm_key("orders.create")
    assert not cashier.has_perm_key("settings.users")


# -------- /auth/me/ exposes permissions --------


def test_me_endpoint_returns_permissions(api_client, cashier):
    pin = _pin(api_client, "1234")
    resp = api_client.get(
        "/api/v1/auth/me/", HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200
    user = resp.json()["data"]["user"]
    assert "permissions" in user
    assert "orders.create" in user["permissions"]


# -------- Manager override --------


@pytest.fixture
def manager_pin(restaurant, db):
    from apps.users.models import User, UserRole

    m = User.objects.create_user(
        username="manager1", password="mgr",
        full_name="Главный Менеджер", role=UserRole.MANAGER,
        restaurant=restaurant,
    )
    m.set_pin("9999")
    m.save(update_fields=["pin_hash"])
    return m


def test_manager_override_with_valid_pin(restaurant, cashier, manager_pin):
    from rest_framework.test import APIRequestFactory

    from apps.users.permissions import verify_manager_override

    factory = APIRequestFactory()
    req = factory.post("/api/v1/orders/1/cancel/")
    req.user = cashier
    req.META["HTTP_X_MANAGER_PIN"] = "9999"

    m = verify_manager_override(request=req, restaurant=restaurant)
    assert m is not None
    assert m.id == manager_pin.id


def test_manager_override_missing_pin_raises(restaurant, cashier):
    from rest_framework.test import APIRequestFactory

    from apps.users.permissions import verify_manager_override
    from common.exceptions import BusinessError

    factory = APIRequestFactory()
    req = factory.post("/api/v1/orders/1/cancel/")
    req.user = cashier

    with pytest.raises(BusinessError) as exc:
        verify_manager_override(request=req, restaurant=restaurant)
    assert exc.value.code == "MANAGER_OVERRIDE_REQUIRED"


def test_manager_override_invalid_pin_raises(restaurant, cashier, manager_pin):
    from rest_framework.test import APIRequestFactory

    from apps.users.permissions import verify_manager_override
    from common.exceptions import BusinessError

    factory = APIRequestFactory()
    req = factory.post("/api/v1/orders/1/cancel/")
    req.user = cashier
    req.META["HTTP_X_MANAGER_PIN"] = "0000"  # неверный

    with pytest.raises(BusinessError) as exc:
        verify_manager_override(request=req, restaurant=restaurant)
    assert exc.value.code == "MANAGER_OVERRIDE_INVALID_PIN"


def test_manager_override_non_manager_user_pin_raises(
    restaurant, cashier, manager_pin,
):
    """Если ввели PIN кассира (не менеджера), не имеющего manager.override."""
    from rest_framework.test import APIRequestFactory

    from apps.users.permissions import verify_manager_override
    from common.exceptions import BusinessError

    factory = APIRequestFactory()
    req = factory.post("/api/v1/orders/1/cancel/")
    req.user = cashier
    # PIN самого кассира (1234) — не менеджер
    req.META["HTTP_X_MANAGER_PIN"] = "1234"

    with pytest.raises(BusinessError) as exc:
        verify_manager_override(request=req, restaurant=restaurant)
    assert exc.value.code == "MANAGER_OVERRIDE_INVALID_USER"


def test_manager_override_writes_audit(restaurant, cashier, manager_pin):
    from apps.audit.models import AuditAction, AuditEntry
    from apps.users.permissions import verify_manager_override
    from rest_framework.test import APIRequestFactory

    factory = APIRequestFactory()
    req = factory.post("/api/v1/test/")
    req.user = cashier
    req.META["HTTP_X_MANAGER_PIN"] = "9999"

    verify_manager_override(request=req, restaurant=restaurant)
    e = AuditEntry.objects.filter(
        action=AuditAction.MANAGER_OVERRIDE
    ).first()
    assert e is not None
    assert e.user_id == manager_pin.id
    assert e.payload["approved_for_user"] == cashier.username


# -------- HasPerm DRF permission class --------


def test_has_perm_class_passes_when_user_has_permission(restaurant, cashier):
    from apps.users.permissions import HasPerm
    from rest_framework.test import APIRequestFactory

    factory = APIRequestFactory()
    req = factory.post("/api/v1/orders/")
    req.user = cashier

    PermClass = HasPerm("orders.create")
    perm = PermClass()
    assert perm.has_permission(req, None) is True


def test_has_perm_class_fails_when_missing(restaurant, cashier):
    from apps.users.permissions import HasPerm
    from rest_framework.test import APIRequestFactory

    factory = APIRequestFactory()
    req = factory.post("/api/v1/users/")
    req.user = cashier  # не имеет settings.users

    PermClass = HasPerm("settings.users")
    perm = PermClass()
    assert perm.has_permission(req, None) is False


# -------- PIN login allows manager --------


def test_manager_can_pin_login(api_client, restaurant, manager_pin):
    """Manager-роль теперь должна иметь возможность PIN-логина в POS."""
    resp = api_client.post(
        "/api/v1/auth/pin/", {"pin": "9999"}, format="json",
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()["data"]
    assert body["session_token"]
    assert body["user"]["role"] == "manager"


# -------- Custom override for cashier (manager.override perm) --------


def test_cashier_with_manager_override_perm_can_approve(
    restaurant, cashier, db,
):
    """Кассир с явным `manager.override` permission тоже может подтверждать."""
    from rest_framework.test import APIRequestFactory

    from apps.users.permissions import verify_manager_override

    cashier.permissions = ["manager.override"]
    cashier.save()
    cashier.set_pin("4321")
    cashier.save(update_fields=["pin_hash"])

    # Создадим другого кассира как actor
    from apps.users.models import User, UserRole
    other = User.objects.create_user(
        username="other", password="x", full_name="O",
        role=UserRole.CASHIER, restaurant=restaurant,
    )

    factory = APIRequestFactory()
    req = factory.post("/api/v1/orders/1/cancel/")
    req.user = other
    req.META["HTTP_X_MANAGER_PIN"] = "4321"

    m = verify_manager_override(request=req, restaurant=restaurant)
    assert m.id == cashier.id
