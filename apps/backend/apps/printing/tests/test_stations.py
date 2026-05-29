"""PrintStation — динамические цеха печати + paper_size."""
from uuid import uuid4

import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def cashier_token(api_client, cashier):
    resp = api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()
    return resp["data"]["session_token"]


@pytest.fixture
def cash_printer(restaurant):
    from apps.printing.models import PaperSize, Printer, PrinterKind
    return Printer.objects.create(
        restaurant=restaurant, name="Касса термо",
        kind=PrinterKind.VIRTUAL, address="cash",
        paper_size=PaperSize.P_80MM,
        is_default=True, is_active=True,
    )


@pytest.fixture
def kitchen_printer(restaurant):
    from apps.printing.models import PaperSize, Printer, PrinterKind
    return Printer.objects.create(
        restaurant=restaurant, name="Кухня термо",
        kind=PrinterKind.VIRTUAL, address="kit",
        paper_size=PaperSize.P_58MM,
        is_default=False, is_active=True,
    )


# -------- Auto-seed --------


def test_new_restaurant_seeds_default_stations(db):
    from apps.printing.models import PrintStation
    from apps.users.models import Restaurant

    resto = Restaurant.objects.create(name="Stations seed", currency="TJS")
    seeded = list(
        PrintStation.objects.filter(restaurant=resto)
        .values_list("name", "system_code")
    )
    names = {n for n, _ in seeded}
    # Дефолтный набор
    assert {"Касса", "Кухня", "Горячий цех", "Холодный цех", "Бар", "Витрина"} <= names
    # Системные имеют system_code
    by_name = dict(seeded)
    assert by_name["Касса"] == "cashier"
    assert by_name["Кухня"] == "kitchen"
    assert by_name["Горячий цех"] == ""


# -------- Paper size --------


def test_printer_paper_size_default_80mm(restaurant):
    from apps.printing.models import Printer, PrinterKind
    p = Printer.objects.create(
        restaurant=restaurant, name="Test", kind=PrinterKind.VIRTUAL,
    )
    assert p.paper_size == "80mm"


def test_printer_paper_size_invalid_via_api(
    api_client, cashier_token, cash_printer
):
    resp = api_client.patch(
        f"/api/v1/printing/printers/{cash_printer.id}/",
        {"paper_size": "100mm"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 400


def test_printer_paper_size_update_via_api(
    api_client, cashier_token, cash_printer
):
    resp = api_client.patch(
        f"/api/v1/printing/printers/{cash_printer.id}/",
        {"paper_size": "58mm"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 200
    cash_printer.refresh_from_db()
    assert cash_printer.paper_size == "58mm"


# -------- resolve_printer via PrintStation --------


def test_resolve_uses_cashier_station_for_guest_receipt(
    restaurant, cash_printer, kitchen_printer
):
    from apps.printing.models import PrintStation
    from apps.printing.services import resolve_printer

    cashier_st = PrintStation.objects.get(
        restaurant=restaurant, system_code="cashier"
    )
    cashier_st.printer = cash_printer
    cashier_st.save()

    p = resolve_printer(restaurant, "guest_receipt")
    assert p.id == cash_printer.id


def test_resolve_uses_kitchen_station_for_kitchen_order(
    restaurant, cash_printer, kitchen_printer
):
    from apps.printing.models import PrintStation
    from apps.printing.services import resolve_printer

    kitchen_st = PrintStation.objects.get(
        restaurant=restaurant, system_code="kitchen"
    )
    kitchen_st.printer = kitchen_printer
    kitchen_st.save()

    p = resolve_printer(restaurant, "kitchen_order")
    assert p.id == kitchen_printer.id


def test_resolve_falls_back_to_default_printer(restaurant, cash_printer):
    """Если у системной станции нет printer → default Printer."""
    from apps.printing.services import resolve_printer

    p = resolve_printer(restaurant, "guest_receipt")
    assert p.id == cash_printer.id


# -------- enqueue_kitchen_prints --------


def test_kitchen_prints_grouped_by_station(
    restaurant, waiter, table, menu_items, kitchen_printer
):
    """Категория плова → горячий цех; чай → бар. Создаются 2 PrintJob."""
    from apps.menu.models import Category, MenuItem
    from apps.orders.services import create_order
    from apps.printing.models import PrintJob, PrintJobKind, PrintStation

    hot = PrintStation.objects.get(restaurant=restaurant, name="Горячий цех")
    bar = PrintStation.objects.get(restaurant=restaurant, name="Бар")
    hot.printer = kitchen_printer
    hot.save()
    bar.printer = kitchen_printer
    bar.save()

    # Привязать категорию menu_items["plov"] к горячему цеху
    plov_cat = menu_items["plov"].category
    plov_cat.print_station = hot
    plov_cat.save()
    # Чай в той же категории — переселим в новую категорию «Напитки» → бар
    drinks_cat = Category.objects.create(
        restaurant=restaurant, name="Напитки", sort_order=99,
        print_station=bar,
    )
    chai = menu_items["chai"]
    chai.category = drinks_cat
    chai.save()

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1,
        items_data=[
            {"menu_item_id": menu_items["plov"].id, "qty": 1},
            {"menu_item_id": chai.id, "qty": 1},
        ],
        comment="", idempotency_key=uuid4(),
    )
    # 2 kitchen prints — горячий + бар
    kitchen_jobs = PrintJob.objects.filter(
        order=order, kind=PrintJobKind.KITCHEN_ORDER
    )
    assert kitchen_jobs.count() == 2
    payloads = [j.payload for j in kitchen_jobs]
    stations = sorted(p.get("station") for p in payloads)
    assert stations == ["Бар", "Горячий цех"]


def test_kitchen_print_skipped_for_categories_without_station(
    restaurant, waiter, table, menu_items
):
    """Если у категории print_station=None — kitchen print не создаётся."""
    from apps.orders.services import create_order
    from apps.printing.models import PrintJob, PrintJobKind

    # Удостоверимся что print_station не задан
    for it in menu_items.values():
        cat = it.category
        cat.print_station = None
        cat.save()

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1,
        items_data=[{"menu_item_id": menu_items["plov"].id, "qty": 1}],
        comment="", idempotency_key=uuid4(),
    )
    kitchen_jobs = PrintJob.objects.filter(
        order=order, kind=PrintJobKind.KITCHEN_ORDER
    )
    assert kitchen_jobs.count() == 0


# -------- API CRUD --------


def test_list_stations(api_client, cashier, cashier_token):
    resp = api_client.get(
        "/api/v1/printing/stations/",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] >= 6  # сидер


def test_create_custom_station(api_client, cashier, cashier_token):
    resp = api_client.post(
        "/api/v1/printing/stations/",
        {"name": "Кондитерский цех", "is_active": True, "sort_order": 10},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["name"] == "Кондитерский цех"
    assert body["system_code"] == ""
    assert body["is_system"] is False


def test_destroy_system_station_blocked(
    api_client, cashier, cashier_token, restaurant
):
    from apps.printing.models import PrintStation

    cashier_st = PrintStation.objects.get(
        restaurant=restaurant, system_code="cashier"
    )
    resp = api_client.delete(
        f"/api/v1/printing/stations/{cashier_st.id}/",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 400


def test_destroy_custom_station(api_client, cashier, cashier_token, restaurant):
    from apps.printing.models import PrintStation

    custom = PrintStation.objects.create(
        restaurant=restaurant, name="Делитель", system_code="",
        sort_order=99,
    )
    resp = api_client.delete(
        f"/api/v1/printing/stations/{custom.id}/",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 204


def test_update_station_assigns_printer(
    api_client, cashier_token, restaurant, kitchen_printer
):
    from apps.printing.models import PrintStation

    bar = PrintStation.objects.get(restaurant=restaurant, name="Бар")
    resp = api_client.patch(
        f"/api/v1/printing/stations/{bar.id}/",
        {"printer": kitchen_printer.id},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 200
    bar.refresh_from_db()
    assert bar.printer_id == kitchen_printer.id


def test_cross_tenant_isolation(api_client, cashier, cashier_token):
    from apps.printing.models import PrintStation
    from apps.users.models import Restaurant

    other = Restaurant.objects.create(name="Other", currency="USD")
    other_st = PrintStation.objects.filter(restaurant=other).first()
    resp = api_client.get(
        "/api/v1/printing/stations/",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    ids = {s["id"] for s in resp.json()["data"]}
    assert other_st.id not in ids
