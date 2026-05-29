"""Импорт меню из XLSX."""
import io

import pytest

pytestmark = pytest.mark.django_db


def _pin(api_client, cashier):
    return api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()["data"]["session_token"]


def _build_xlsx(rows: list[list]) -> bytes:
    """Создать XLSX в памяти с заданными строками (включая header)."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Menu"
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# -------- Service --------


def test_import_creates_categories_and_items(restaurant, db):
    from apps.menu.import_excel import import_menu_xlsx
    from apps.menu.models import Category, MenuItem

    xlsx = _build_xlsx([
        ["Категория", "Блюдо", "Цена", "Эмодзи", "Доступно"],
        ["Горячее", "Плов", 45.00, "🍚", "да"],
        ["Горячее", "Лагман", 50.00, "🍜", "да"],
        ["Напитки", "Чай", 8.00, "🍵", "да"],
    ])
    summary = import_menu_xlsx(xlsx, restaurant=restaurant)
    assert summary["created"] == 3
    assert summary["updated"] == 0
    assert summary["errors"] == []
    assert Category.objects.filter(restaurant=restaurant).count() >= 2
    assert MenuItem.objects.filter(restaurant=restaurant, name="Плов").exists()


def test_import_updates_existing_items(restaurant, db):
    from apps.menu.import_excel import import_menu_xlsx
    from apps.menu.models import Category, MenuItem
    from decimal import Decimal

    cat = Category.objects.create(restaurant=restaurant, name="Горячее")
    MenuItem.objects.create(
        restaurant=restaurant, category=cat, name="Плов",
        price=Decimal("40.00"),
    )
    xlsx = _build_xlsx([
        ["Категория", "Блюдо", "Цена"],
        ["Горячее", "Плов", 55.00],
    ])
    summary = import_menu_xlsx(xlsx, restaurant=restaurant)
    assert summary["created"] == 0
    assert summary["updated"] == 1
    plov = MenuItem.objects.get(restaurant=restaurant, name="Плов")
    assert plov.price == Decimal("55.00")


def test_import_skips_invalid_rows(restaurant, db):
    from apps.menu.import_excel import import_menu_xlsx

    xlsx = _build_xlsx([
        ["Категория", "Блюдо", "Цена"],
        ["Горячее", "", 45.00],  # пустое имя
        ["", "Плов", 45.00],  # пустая категория
        ["Горячее", "Плов", "abc"],  # невалидная цена
        ["Горячее", "Лагман", 50.00],  # OK
    ])
    summary = import_menu_xlsx(xlsx, restaurant=restaurant)
    assert summary["created"] == 1
    assert len(summary["errors"]) == 3


def test_import_missing_required_columns_raises(restaurant, db):
    from apps.menu.import_excel import import_menu_xlsx

    xlsx = _build_xlsx([
        ["Foo", "Bar", "Baz"],
        ["1", "2", "3"],
    ])
    with pytest.raises(ValueError):
        import_menu_xlsx(xlsx, restaurant=restaurant)


def test_import_writes_audit_log(restaurant, cashier, db):
    from apps.audit.models import AuditAction, AuditEntry
    from apps.menu.import_excel import import_menu_xlsx

    xlsx = _build_xlsx([
        ["Категория", "Блюдо", "Цена"],
        ["Горячее", "Плов", 45.00],
    ])
    import_menu_xlsx(xlsx, restaurant=restaurant, user=cashier)
    e = AuditEntry.objects.filter(
        action=AuditAction.SETTINGS_UPDATE
    ).filter(payload__action="menu_import_xlsx").first()
    assert e is not None


# -------- API endpoint --------


def test_import_endpoint(api_client, restaurant, cashier):
    from apps.menu.models import MenuItem

    xlsx = _build_xlsx([
        ["Категория", "Блюдо", "Цена"],
        ["Горячее", "Плов", 45.00],
        ["Напитки", "Чай", 8.00],
    ])
    pin = _pin(api_client, cashier)
    from django.core.files.uploadedfile import SimpleUploadedFile

    f = SimpleUploadedFile(
        "menu.xlsx", xlsx,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp = api_client.post(
        "/api/v1/menu/items/import_xlsx/",
        {"file": f},
        format="multipart",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200, resp.content
    data = resp.json()["data"]
    assert data["created"] == 2
    assert MenuItem.objects.filter(restaurant=restaurant).count() == 2


def test_import_endpoint_missing_file(api_client, restaurant, cashier):
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        "/api/v1/menu/items/import_xlsx/",
        {},
        format="multipart",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "FILE_REQUIRED"


def test_menu_template_endpoint(api_client, cashier):
    """GET /menu/items/template/ возвращает валидный XLSX-шаблон."""
    api_client.force_authenticate(user=cashier)
    resp = api_client.get("/api/v1/menu/items/template/")
    assert resp.status_code == 200
    assert "spreadsheet" in resp["Content-Type"]
    assert resp.content[:2] == b"PK"  # ZIP magic — XLSX это zip

    # Импортнём этот же шаблон — должен сработать end-to-end
    from django.core.files.uploadedfile import SimpleUploadedFile
    upload = SimpleUploadedFile(
        "menu_template.xlsx", resp.content,
        content_type=resp["Content-Type"],
    )
    resp2 = api_client.post(
        "/api/v1/menu/items/import_xlsx/",
        {"file": upload}, format="multipart",
    )
    assert resp2.status_code == 200, resp2.content
    body = resp2.json()["data"]
    # Демо-строки шаблона: 4 блюда (Плов, Лагман, Чай, Кола)
    assert body["created"] == 4
    assert body["errors"] == []
