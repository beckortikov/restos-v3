"""Force-free table: освобождение «застрявшего» в occupied стола без заказа."""
import pytest

pytestmark = pytest.mark.django_db


def _pin(api_client, cashier):
    return api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()["data"]["session_token"]


@pytest.fixture
def zone(restaurant):
    from apps.tables.models import Zone

    return Zone.objects.create(restaurant=restaurant, name="Зал")


@pytest.fixture
def stuck_table(restaurant, zone):
    """Стол с status=occupied но без активного заказа (рассинхрон)."""
    from apps.tables.models import Table, TableStatus

    return Table.objects.create(
        restaurant=restaurant, zone=zone, number=99, name="Стол 99",
        capacity=2, status=TableStatus.OCCUPIED, guests_count=2,
    )


def test_force_free_releases_stuck_table(restaurant, cashier, stuck_table):
    from apps.tables.services import force_free_table

    table = force_free_table(
        table_id=stuck_table.id, restaurant=restaurant, user=cashier,
    )
    assert table.status == "free"
    assert table.current_order_id is None
    assert table.guests_count == 0


def test_force_free_rejected_when_active_order_exists(
    restaurant, cashier, waiter, stuck_table, menu_items, printer,
):
    """Если на столе есть активный заказ — нельзя force-free."""
    from uuid import uuid4

    from apps.orders.services import create_order
    from apps.tables.services import force_free_table
    from common.exceptions import BusinessError

    # Сначала вернём в free через сервис, чтобы создать заказ
    from apps.tables.models import TableStatus
    stuck_table.status = TableStatus.FREE
    stuck_table.save()

    create_order(
        restaurant=restaurant, table_id=stuck_table.id, waiter=waiter,
        guests_count=1,
        items_data=[{"menu_item_id": menu_items["plov"].id, "qty": 1}],
        idempotency_key=uuid4(),
    )
    with pytest.raises(BusinessError) as exc:
        force_free_table(
            table_id=stuck_table.id, restaurant=restaurant, user=cashier,
        )
    assert exc.value.code == "TABLE_HAS_ACTIVE_ORDER"


def test_force_free_endpoint(api_client, restaurant, cashier, stuck_table):
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        f"/api/v1/tables/{stuck_table.id}/force_free/",
        {}, format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200, resp.content
    assert resp.json()["data"]["status"] == "free"


def test_force_free_writes_audit_log(restaurant, cashier, stuck_table):
    from apps.audit.models import AuditAction, AuditEntry
    from apps.tables.services import force_free_table

    force_free_table(
        table_id=stuck_table.id, restaurant=restaurant, user=cashier,
    )
    e = AuditEntry.objects.filter(
        action=AuditAction.SETTINGS_UPDATE, target_id=stuck_table.id,
    ).first()
    assert e is not None
    assert e.payload["action"] == "force_free_table"


def test_force_free_returns_404_for_unknown_table(restaurant, cashier):
    from apps.tables.services import force_free_table
    from common.exceptions import BusinessError

    with pytest.raises(BusinessError) as exc:
        force_free_table(
            table_id=99999, restaurant=restaurant, user=cashier,
        )
    assert exc.value.code == "TABLE_NOT_FOUND"
