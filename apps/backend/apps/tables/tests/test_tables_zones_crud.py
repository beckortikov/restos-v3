"""CRUD-эндпоинты для Zone и Table — для админки в Settings → Зоны и столы."""
import pytest

pytestmark = pytest.mark.django_db


def _pin(api_client, user, pin: str = "1234"):
    return api_client.post(
        "/api/v1/auth/pin/", {"pin": pin}, format="json"
    ).json()["data"]["session_token"]


# -------- Zone CRUD --------


def test_zone_create_by_cashier(api_client, restaurant, cashier):
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        "/api/v1/tables/zones/",
        {"name": "Терраса", "sort_order": 2},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 201, resp.content
    body = resp.json()
    data = body.get("data") if "data" in body else body
    assert data["name"] == "Терраса"
    assert data["sort_order"] == 2
    # Проверим что записано на текущий ресторан
    from apps.tables.models import Zone
    z = Zone.objects.get(id=data["id"])
    assert z.restaurant_id == restaurant.id


def test_zone_update(api_client, restaurant, cashier):
    from apps.tables.models import Zone

    z = Zone.objects.create(restaurant=restaurant, name="Старое", sort_order=0)
    pin = _pin(api_client, cashier)
    resp = api_client.patch(
        f"/api/v1/tables/zones/{z.id}/",
        {"name": "Новое"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200, resp.content
    z.refresh_from_db()
    assert z.name == "Новое"


def test_zone_delete_empty_ok(api_client, restaurant, cashier):
    from apps.tables.models import Zone

    z = Zone.objects.create(restaurant=restaurant, name="Пустая")
    pin = _pin(api_client, cashier)
    resp = api_client.delete(
        f"/api/v1/tables/zones/{z.id}/",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 204
    assert not Zone.objects.filter(id=z.id).exists()


def test_zone_delete_with_tables_blocked(api_client, restaurant, cashier):
    from apps.tables.models import Table, Zone

    z = Zone.objects.create(restaurant=restaurant, name="Зал")
    Table.objects.create(
        restaurant=restaurant, zone=z, number=1,
        name="Стол 1", capacity=4,
    )
    pin = _pin(api_client, cashier)
    resp = api_client.delete(
        f"/api/v1/tables/zones/{z.id}/",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "ZONE_NOT_EMPTY"
    assert Zone.objects.filter(id=z.id).exists()


def test_zone_delete_with_only_archived_tables_soft_archives(
    api_client, restaurant, cashier,
):
    """Зона со столами, которые все архивированы → soft-archive зоны.
    PROTECT FK не даёт hard-delete, поэтому помечаем is_archived=True.
    Зона пропадает из list, но в БД остаётся для исторических резолвов."""
    from django.utils import timezone
    from apps.tables.models import Table, Zone

    z = Zone.objects.create(restaurant=restaurant, name="ЗалУдалить")
    Table.objects.create(
        restaurant=restaurant, zone=z, number=1, name="Стол 1",
        capacity=2, is_archived=True, archived_at=timezone.now(),
    )

    pin = _pin(api_client, cashier)
    resp = api_client.delete(
        f"/api/v1/tables/zones/{z.id}/",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 204
    z.refresh_from_db()
    assert z.is_archived is True
    assert z.archived_at is not None

    # Пропала из list-endpoint'а.
    list_resp = api_client.get(
        "/api/v1/tables/zones/",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    zone_ids = [item["id"] for item in list_resp.json()["data"]]
    assert z.id not in zone_ids


def test_zone_write_forbidden_for_cook(api_client, restaurant):
    """Повар не должен иметь доступа к настройке зон."""
    from apps.users.models import User, UserRole

    cook = User.objects.create_user(
        username="cook1", password="x", role=UserRole.COOK,
        full_name="Повар", restaurant=restaurant,
    )
    cook.set_pin("9999")
    cook.save(update_fields=["pin_hash"])
    pin = _pin(api_client, cook, pin="9999")
    resp = api_client.post(
        "/api/v1/tables/zones/",
        {"name": "Х"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 403


# -------- Table CRUD --------


def test_table_create_by_cashier(api_client, restaurant, cashier):
    from apps.tables.models import Zone

    z = Zone.objects.create(restaurant=restaurant, name="Зал")
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        "/api/v1/tables/",
        {
            "zone": z.id, "number": 5,
            "name": "Стол у окна", "capacity": 6,
        },
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 201, resp.content
    body = resp.json()
    data = body.get("data") if "data" in body else body
    assert data["name"] == "Стол у окна"
    assert data["capacity"] == 6
    assert data["number"] == 5


def test_table_update_capacity(api_client, restaurant, cashier):
    from apps.tables.models import Table, Zone

    z = Zone.objects.create(restaurant=restaurant, name="Зал")
    t = Table.objects.create(
        restaurant=restaurant, zone=z, number=1,
        name="Стол 1", capacity=2,
    )
    pin = _pin(api_client, cashier)
    resp = api_client.patch(
        f"/api/v1/tables/{t.id}/",
        {"capacity": 8},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200
    t.refresh_from_db()
    assert t.capacity == 8


def test_table_delete_free_ok(api_client, restaurant, cashier):
    from apps.tables.models import Table, Zone

    z = Zone.objects.create(restaurant=restaurant, name="Зал")
    t = Table.objects.create(
        restaurant=restaurant, zone=z, number=99,
        name="Удалить", capacity=2,
    )
    pin = _pin(api_client, cashier)
    resp = api_client.delete(
        f"/api/v1/tables/{t.id}/",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 204
    assert not Table.objects.filter(id=t.id).exists()


def test_table_delete_with_history_soft_archives(
    api_client, restaurant, cashier, waiter, menu_items,
):
    """Стол с историческими заказами нельзя hard-delete (Order.table=PROTECT),
    поэтому ViewSet делает soft-archive: is_archived=True, скрывается из
    list-endpoint'а, но сам объект остаётся в БД для отчётов."""
    from uuid import uuid4
    from apps.orders.services import create_order
    from apps.tables.models import Table, TableStatus, Zone

    z = Zone.objects.create(restaurant=restaurant, name="Зал")
    t = Table.objects.create(
        restaurant=restaurant, zone=z, number=77, name="История",
        capacity=2, status=TableStatus.FREE,
    )
    # Создаём заказ → завершаем → стол освобождается, остаётся в истории.
    order = create_order(
        restaurant=restaurant, table_id=t.id, waiter=waiter,
        guests_count=1,
        items_data=[{"menu_item_id": menu_items["plov"].id, "qty": 1}],
        comment="", idempotency_key=uuid4(),
    )
    order.status = "done"  # упрощённое закрытие
    order.save(update_fields=["status"])
    # Освобождаем стол вручную чтобы пройти проверку TABLE_BUSY.
    t.status = TableStatus.FREE
    t.current_order = None
    t.save(update_fields=["status", "current_order"])

    pin = _pin(api_client, cashier)
    resp = api_client.delete(
        f"/api/v1/tables/{t.id}/",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 204
    # Стол НЕ удалён физически — soft-archived.
    t.refresh_from_db()
    assert t.is_archived is True
    assert t.archived_at is not None
    # Из list-endpoint'а пропал.
    list_resp = api_client.get(
        "/api/v1/tables/", HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    table_ids = [item["id"] for item in list_resp.json()["data"]]
    assert t.id not in table_ids


def test_table_delete_occupied_blocked(
    api_client, restaurant, cashier, waiter,
):
    from apps.tables.models import Table, TableStatus, Zone

    z = Zone.objects.create(restaurant=restaurant, name="Зал")
    t = Table.objects.create(
        restaurant=restaurant, zone=z, number=1,
        name="Занят", capacity=4,
        status=TableStatus.OCCUPIED,
    )
    pin = _pin(api_client, cashier)
    resp = api_client.delete(
        f"/api/v1/tables/{t.id}/",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "TABLE_BUSY"


def test_table_cross_restaurant_zone_rejected(
    api_client, restaurant, cashier,
):
    """Нельзя привязать стол к зоне чужого ресторана."""
    from apps.tables.models import Zone
    from apps.users.models import Restaurant

    other = Restaurant.objects.create(name="Чужой", currency="TJS")
    other_zone = Zone.objects.create(restaurant=other, name="Чужая")

    pin = _pin(api_client, cashier)
    resp = api_client.post(
        "/api/v1/tables/",
        {
            "zone": other_zone.id, "number": 50,
            "name": "X", "capacity": 2,
        },
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 400


def test_table_cross_restaurant_waiter_rejected(
    api_client, restaurant, cashier,
):
    """Нельзя назначить столу официанта из другого ресторана."""
    from apps.tables.models import Zone
    from apps.users.models import Restaurant, User, UserRole

    z = Zone.objects.create(restaurant=restaurant, name="Зал")
    other = Restaurant.objects.create(name="Чужой 2", currency="TJS")
    other_waiter = User.objects.create(
        username="other_w", restaurant=other,
        role=UserRole.WAITER, is_active=True,
        full_name="Other Waiter",
    )

    pin = _pin(api_client, cashier)
    resp = api_client.post(
        "/api/v1/tables/",
        {
            "zone": z.id, "number": 51,
            "name": "X", "capacity": 2,
            "waiter": other_waiter.id,
        },
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 400


def test_table_write_forbidden_for_cook(api_client, restaurant):
    """Повар не должен иметь доступа к настройке столов."""
    from apps.tables.models import Zone
    from apps.users.models import User, UserRole

    z = Zone.objects.create(restaurant=restaurant, name="Зал")
    cook = User.objects.create_user(
        username="cook2", password="x", role=UserRole.COOK,
        full_name="Повар 2", restaurant=restaurant,
    )
    cook.set_pin("8888")
    cook.save(update_fields=["pin_hash"])
    pin = _pin(api_client, cook, pin="8888")
    resp = api_client.post(
        "/api/v1/tables/",
        {"zone": z.id, "number": 1, "name": "X", "capacity": 2},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 403


def test_table_unique_number_per_restaurant(
    api_client, restaurant, cashier,
):
    """Два стола с одним number в одном ресторане — нельзя."""
    from apps.tables.models import Table, Zone

    z = Zone.objects.create(restaurant=restaurant, name="Зал")
    Table.objects.create(
        restaurant=restaurant, zone=z, number=42,
        name="Уже есть", capacity=2,
    )
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        "/api/v1/tables/",
        {"zone": z.id, "number": 42, "name": "Дубль", "capacity": 2},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 400
