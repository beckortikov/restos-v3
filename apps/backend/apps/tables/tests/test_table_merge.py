"""Объединение столов: merge / unmerge."""
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def zone(restaurant):
    from apps.tables.models import Zone

    return Zone.objects.create(restaurant=restaurant, name="Зал", sort_order=1)


@pytest.fixture
def t5(restaurant, zone):
    from apps.tables.models import Table

    return Table.objects.create(
        restaurant=restaurant, zone=zone, number=5, name="Стол 5", capacity=4,
    )


@pytest.fixture
def t6(restaurant, zone):
    from apps.tables.models import Table

    return Table.objects.create(
        restaurant=restaurant, zone=zone, number=6, name="Стол 6", capacity=4,
    )


@pytest.fixture
def t7(restaurant, zone):
    from apps.tables.models import Table

    return Table.objects.create(
        restaurant=restaurant, zone=zone, number=7, name="Стол 7", capacity=4,
    )


def _pin(api_client, cashier):
    return api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()["data"]["session_token"]


# -------- Service --------


def test_merge_two_free_tables(restaurant, cashier, t5, t6):
    from apps.tables.models import TableStatus
    from apps.tables.services import merge_tables

    group = merge_tables(
        restaurant=restaurant, table_ids=[t5.id, t6.id], user=cashier,
    )
    assert group.tables.count() == 2
    assert group.primary_table_id == t5.id  # min(id)

    t5.refresh_from_db()
    t6.refresh_from_db()
    assert t5.group_id == group.id
    assert t5.status == TableStatus.FREE  # primary остаётся FREE до open
    assert t6.group_id == group.id
    assert t6.status == TableStatus.MERGED


def test_merge_three_tables(restaurant, cashier, t5, t6, t7):
    from apps.tables.services import merge_tables

    group = merge_tables(
        restaurant=restaurant, table_ids=[t5.id, t6.id, t7.id], user=cashier,
    )
    assert group.tables.count() == 3
    assert group.primary_table_id == t5.id


def test_merge_rejects_single_table(restaurant, cashier, t5):
    from apps.tables.services import merge_tables
    from common.exceptions import BusinessError

    with pytest.raises(BusinessError) as exc:
        merge_tables(restaurant=restaurant, table_ids=[t5.id], user=cashier)
    assert exc.value.code == "INVALID_TRANSITION"


def test_merge_rejects_occupied_table(restaurant, cashier, waiter, t5, t6):
    from apps.tables.models import TableStatus
    from apps.tables.services import merge_tables, open_table
    from common.exceptions import BusinessError

    open_table(table_id=t5.id, waiter=waiter, guests_count=2)
    t5.refresh_from_db()
    assert t5.status == TableStatus.OCCUPIED

    with pytest.raises(BusinessError) as exc:
        merge_tables(
            restaurant=restaurant, table_ids=[t5.id, t6.id], user=cashier,
        )
    assert exc.value.code == "TABLE_OCCUPIED"


def test_merge_rejects_already_merged_table(restaurant, cashier, t5, t6, t7):
    from apps.tables.services import merge_tables
    from common.exceptions import BusinessError

    merge_tables(restaurant=restaurant, table_ids=[t5.id, t6.id], user=cashier)
    with pytest.raises(BusinessError) as exc:
        merge_tables(
            restaurant=restaurant, table_ids=[t5.id, t7.id], user=cashier,
        )
    assert exc.value.code in ("TABLE_ALREADY_MERGED", "TABLE_OCCUPIED")


def test_unmerge_releases_all_tables(restaurant, cashier, t5, t6):
    from apps.tables.models import TableStatus
    from apps.tables.services import merge_tables, unmerge_table_group

    group = merge_tables(
        restaurant=restaurant, table_ids=[t5.id, t6.id], user=cashier,
    )
    unmerge_table_group(
        restaurant=restaurant, group_id=group.id, user=cashier,
    )
    t5.refresh_from_db()
    t6.refresh_from_db()
    assert t5.group_id is None
    assert t5.status == TableStatus.FREE
    assert t6.group_id is None
    assert t6.status == TableStatus.FREE
    group.refresh_from_db()
    assert group.closed_at is not None


def test_unmerge_rejects_when_active_order_on_primary(
    restaurant, cashier, waiter, t5, t6, menu_items, printer,
):
    from uuid import uuid4

    from apps.orders.services import create_order
    from apps.tables.services import merge_tables, unmerge_table_group
    from common.exceptions import BusinessError

    group = merge_tables(
        restaurant=restaurant, table_ids=[t5.id, t6.id], user=cashier,
    )
    # Открываем заказ на primary
    order = create_order(
        restaurant=restaurant, table_id=group.primary_table_id, waiter=waiter,
        guests_count=4, items_data=[
            {"menu_item_id": menu_items["plov"].id, "qty": 1},
        ],
        idempotency_key=uuid4(),
    )
    # current_order привязан к primary через create_order
    assert order.table_id == group.primary_table_id

    with pytest.raises(BusinessError) as exc:
        unmerge_table_group(
            restaurant=restaurant, group_id=group.id, user=cashier,
        )
    assert exc.value.code == "TABLE_GROUP_HAS_ORDER"


def test_free_table_closes_group(
    restaurant, cashier, waiter, t5, t6, menu_items, printer,
):
    """После close_order primary столa free_table вызовется и группа закроется."""
    from uuid import uuid4

    from apps.orders.services import close_order, create_order
    from apps.tables.services import merge_tables

    group = merge_tables(
        restaurant=restaurant, table_ids=[t5.id, t6.id], user=cashier,
    )
    order = create_order(
        restaurant=restaurant, table_id=group.primary_table_id, waiter=waiter,
        guests_count=4, items_data=[
            {"menu_item_id": menu_items["plov"].id, "qty": 2},
        ],
        idempotency_key=uuid4(),
    )
    close_order(order_id=order.id, cashier=cashier, payment_method="cash")

    group.refresh_from_db()
    assert group.closed_at is not None
    t5.refresh_from_db()
    t6.refresh_from_db()
    assert t5.group_id is None
    assert t6.group_id is None
    assert t5.status == "free"
    assert t6.status == "free"


def test_merge_writes_audit_log(restaurant, cashier, t5, t6):
    from apps.audit.models import AuditAction, AuditEntry
    from apps.tables.services import merge_tables

    merge_tables(
        restaurant=restaurant, table_ids=[t5.id, t6.id], user=cashier,
    )
    e = AuditEntry.objects.filter(action=AuditAction.TABLES_MERGED).first()
    assert e is not None
    assert e.payload["primary_table_id"] == t5.id
    assert "Стол 5" in e.payload["table_names"]


def test_unmerge_writes_audit_log(restaurant, cashier, t5, t6):
    from apps.audit.models import AuditAction, AuditEntry
    from apps.tables.services import merge_tables, unmerge_table_group

    group = merge_tables(
        restaurant=restaurant, table_ids=[t5.id, t6.id], user=cashier,
    )
    unmerge_table_group(
        restaurant=restaurant, group_id=group.id, user=cashier,
    )
    e = AuditEntry.objects.filter(action=AuditAction.TABLES_UNMERGED).first()
    assert e is not None


# -------- API endpoints --------


def test_merge_endpoint(api_client, restaurant, cashier, t5, t6):
    from apps.tables.models import TableGroup

    pin = _pin(api_client, cashier)
    resp = api_client.post(
        "/api/v1/tables/merge/",
        {"table_ids": [t5.id, t6.id], "name": "VIP компания"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 201, resp.content
    data = resp.json()["data"]
    assert data["name"] == "VIP компания"
    assert len(data["tables"]) == 2
    assert TableGroup.objects.count() == 1


def test_unmerge_endpoint(api_client, restaurant, cashier, t5, t6):
    from apps.tables.services import merge_tables

    group = merge_tables(
        restaurant=restaurant, table_ids=[t5.id, t6.id], user=cashier,
    )
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        f"/api/v1/tables/groups/{group.id}/unmerge/",
        {},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200, resp.content
    group.refresh_from_db()
    assert group.closed_at is not None


def test_groups_list_active_only_by_default(
    api_client, restaurant, cashier, t5, t6, t7,
):
    from apps.tables.services import merge_tables, unmerge_table_group
    from apps.tables.models import Table, Zone

    g1 = merge_tables(
        restaurant=restaurant, table_ids=[t5.id, t6.id], user=cashier,
    )
    unmerge_table_group(
        restaurant=restaurant, group_id=g1.id, user=cashier,
    )

    # Make a fresh zone and tables for active group
    z = Zone.objects.create(restaurant=restaurant, name="Терраса")
    t8 = Table.objects.create(
        restaurant=restaurant, zone=z, number=8, name="Стол 8",
    )
    merge_tables(
        restaurant=restaurant, table_ids=[t7.id, t8.id], user=cashier,
    )

    pin = _pin(api_client, cashier)
    resp = api_client.get(
        "/api/v1/tables/groups/",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200
    # Active only — закрытая g1 не отдана
    assert resp.json()["meta"]["total"] == 1


def test_table_serializer_includes_group(
    api_client, restaurant, cashier, t5, t6,
):
    from apps.tables.services import merge_tables

    merge_tables(
        restaurant=restaurant, table_ids=[t5.id, t6.id], user=cashier,
    )
    pin = _pin(api_client, cashier)
    resp = api_client.get(
        "/api/v1/tables/", HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    data = resp.json()["data"]
    by_id = {t["id"]: t for t in data}
    assert by_id[t5.id]["group"] is not None
    assert "Стол 5" in by_id[t5.id]["group"]["table_names"]
    assert by_id[t6.id]["status"] == "merged"


def test_cross_restaurant_isolation(restaurant, cashier, t5, t6):
    """Чужие столы не должны быть видны при merge."""
    from apps.tables.services import merge_tables
    from apps.users.models import Restaurant, User
    from common.exceptions import BusinessError

    other_rest = Restaurant.objects.create(name="Чужой", currency="TJS")
    other_cashier = User.objects.create_user(
        username="other-cashier", password="x",
        full_name="Чужой", role="cashier", restaurant=other_rest,
    )

    # other_cashier пытается смержить столы чужого ресторана (restaurant)
    with pytest.raises(BusinessError) as exc:
        merge_tables(
            restaurant=other_rest, table_ids=[t5.id, t6.id], user=other_cashier,
        )
    assert exc.value.code == "TABLE_NOT_FOUND"
