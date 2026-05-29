import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def zone(restaurant):
    from apps.tables.models import Zone

    return Zone.objects.create(restaurant=restaurant, name="Зал", sort_order=1)


@pytest.fixture
def table(restaurant, zone):
    from apps.tables.models import Table

    return Table.objects.create(
        restaurant=restaurant, zone=zone, number=5, name="Стол 5", capacity=4
    )


def _pin_token(api_client, cashier):
    return api_client.post("/api/v1/auth/pin/", {"pin": "1234"}, format="json").json()[
        "data"
    ]["session_token"]


def _jwt(api_client, waiter):
    return api_client.post(
        "/api/v1/auth/login/",
        {"username": "waiter1", "password": "waiter-pass"},
        format="json",
    ).json()["data"]["access"]


def test_zones_list_requires_auth(api_client, zone):
    resp = api_client.get("/api/v1/tables/zones/")
    assert resp.status_code == 401


def test_zones_list_for_cashier(api_client, cashier, zone):
    token = _pin_token(api_client, cashier)
    resp = api_client.get("/api/v1/tables/zones/", HTTP_AUTHORIZATION=f"PIN {token}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["name"] == "Зал"


def test_tables_list_for_waiter(api_client, waiter, table):
    access = _jwt(api_client, waiter)
    resp = api_client.get("/api/v1/tables/", HTTP_AUTHORIZATION=f"Bearer {access}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["status"] == "free"


def test_tables_filter_by_status(api_client, waiter, table):
    from apps.tables.models import Table, TableStatus

    other = Table.objects.create(
        restaurant=waiter.restaurant,
        zone=table.zone,
        number=6,
        name="Стол 6",
        status=TableStatus.OCCUPIED,
    )
    access = _jwt(api_client, waiter)
    resp = api_client.get(
        "/api/v1/tables/?status=occupied", HTTP_AUTHORIZATION=f"Bearer {access}"
    )
    assert resp.status_code == 200
    ids = [t["id"] for t in resp.json()["data"]]
    assert ids == [other.id]


def test_open_table_by_waiter(api_client, waiter, table):
    access = _jwt(api_client, waiter)
    resp = api_client.post(
        f"/api/v1/tables/{table.id}/open/",
        {"guests_count": 3},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()["data"]
    assert body["status"] == "occupied"
    assert body["guests_count"] == 3
    assert body["waiter"] == waiter.id


def test_open_table_by_cashier(api_client, cashier, table):
    """В POS-моноблоке кассир тоже может открывать столы."""
    token = _pin_token(api_client, cashier)
    resp = api_client.post(
        f"/api/v1/tables/{table.id}/open/",
        {"guests_count": 2},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {token}",
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["status"] == "occupied"
    assert body["waiter"] == cashier.id


def test_open_table_already_occupied(api_client, waiter, table):
    from apps.tables.services import open_table

    open_table(table_id=table.id, waiter=waiter, guests_count=2)

    access = _jwt(api_client, waiter)
    resp = api_client.post(
        f"/api/v1/tables/{table.id}/open/",
        {"guests_count": 1},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "TABLE_OCCUPIED"


def test_open_table_not_found(api_client, waiter):
    access = _jwt(api_client, waiter)
    resp = api_client.post(
        "/api/v1/tables/99999/open/",
        {"guests_count": 1},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "TABLE_NOT_FOUND"


def test_tables_isolated_by_restaurant(api_client, waiter, table):
    from apps.tables.models import Table, Zone
    from apps.users.models import Restaurant

    other_resto = Restaurant.objects.create(name="Other", currency="TJS")
    other_zone = Zone.objects.create(restaurant=other_resto, name="Other zone")
    Table.objects.create(
        restaurant=other_resto, zone=other_zone, number=1, name="Other-1"
    )

    access = _jwt(api_client, waiter)
    resp = api_client.get("/api/v1/tables/", HTTP_AUTHORIZATION=f"Bearer {access}")
    body = resp.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["id"] == table.id
