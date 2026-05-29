import pytest
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def restaurant(db, settings):
    from apps.orders.models import Discount
    from apps.users.models import Restaurant

    resto = Restaurant.objects.create(
        name="Test Resto", currency="TJS", pin_lock_timeout_min=30
    )
    settings.MVP_RESTAURANT_ID = resto.id
    # Авто-сидер post_save включает сервисный сбор 12% — для большинства
    # тестов это нежелательно (они проверяют точный total). Тесты,
    # которым нужен service charge, активируют его явно.
    Discount.objects.filter(restaurant=resto, type="service").update(is_active=False)
    return resto


@pytest.fixture
def cashier(db, restaurant):
    from apps.users.models import User, UserRole

    user = User.objects.create_user(
        username="cashier1",
        password="cashier-pass",
        full_name="Анна Кассир",
        role=UserRole.CASHIER,
        restaurant=restaurant,
    )
    user.set_pin("1234")
    user.save(update_fields=["pin_hash"])
    return user


@pytest.fixture
def waiter(db, restaurant):
    from apps.users.models import User, UserRole

    return User.objects.create_user(
        username="waiter1",
        password="waiter-pass",
        full_name="Карим Официант",
        role=UserRole.WAITER,
        restaurant=restaurant,
    )
