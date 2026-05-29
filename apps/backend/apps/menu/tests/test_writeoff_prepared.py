"""Phase 8C — writeoff_prepared_batch для заготовочных блюд."""
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def batch_item(restaurant, category):
    from apps.menu.models import MenuItem

    return MenuItem.objects.create(
        restaurant=restaurant, category=category, name="Плов",
        price=Decimal("45.00"), is_batch_cooking=True, prepared_qty=10,
    )


def test_writeoff_prepared_decrements_qty(batch_item, cashier):
    from apps.menu.services import writeoff_prepared_batch

    result = writeoff_prepared_batch(
        batch_item, qty=3, reason="Просрочились", user=cashier,
    )
    batch_item.refresh_from_db()
    assert batch_item.prepared_qty == 7
    assert result["new_total"] == 7
    assert result["qty_delta"] == -3


def test_writeoff_prepared_writes_log(batch_item, cashier):
    from apps.menu.models import BatchCookingLog
    from apps.menu.services import writeoff_prepared_batch

    writeoff_prepared_batch(batch_item, qty=2, reason="Испортились", user=cashier)
    log = BatchCookingLog.objects.filter(menu_item=batch_item).latest("created_at")
    assert log.qty_delta == -2
    assert log.kind == "correct"
    assert "Испортились" in log.note


def test_writeoff_prepared_rejects_zero_qty(batch_item):
    from apps.menu.services import writeoff_prepared_batch
    from common.exceptions import BusinessError

    with pytest.raises(BusinessError) as exc:
        writeoff_prepared_batch(batch_item, qty=0, reason="x")
    assert exc.value.code == "INVALID_VALUE"


def test_writeoff_prepared_rejects_empty_reason(batch_item):
    from apps.menu.services import writeoff_prepared_batch
    from common.exceptions import BusinessError

    with pytest.raises(BusinessError) as exc:
        writeoff_prepared_batch(batch_item, qty=1, reason="  ")
    assert exc.value.code == "INVALID_VALUE"


def test_writeoff_prepared_clamps_to_zero(batch_item, cashier):
    """Списание больше чем prepared_qty → clamp к 0, shortfall > 0."""
    from apps.menu.services import writeoff_prepared_batch

    result = writeoff_prepared_batch(
        batch_item, qty=15, reason="Всё", user=cashier,
    )
    batch_item.refresh_from_db()
    assert batch_item.prepared_qty == 0
    assert result["new_total"] == 0
    assert result["shortfall"] == 5


def test_writeoff_prepared_api(api_client, cashier, batch_item):
    api_client.force_authenticate(user=cashier)
    resp = api_client.post(
        f"/api/v1/menu/items/{batch_item.id}/writeoff_prepared/",
        {"qty": 4, "reason": "Просрочились"},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["meta"]["new_total"] == 6
    batch_item.refresh_from_db()
    assert batch_item.prepared_qty == 6
