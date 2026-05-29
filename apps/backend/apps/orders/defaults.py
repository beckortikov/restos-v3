"""Единый источник правды для дефолтных бизнес-строк.

Используется:
- миграцией `0006_seed_cancel_reasons` для существующих ресторанов;
- сигналом `post_save` для новых ресторанов;
- НЕ используется в runtime-логике отмены — там грузим всегда из БД.

Если меняешь список — пиши новую миграцию (для уже существующих ресторанов
изменения не подтянутся автоматически: их данные принадлежат им).
"""
DEFAULT_PAYMENT_PROVIDERS: list[dict] = [
    {
        "name": "Наличные",
        "kind": "cash",
        "description": "Приём наличных средств",
        "commission_pct": "0.00",
        "is_active": True,
        "sort_order": 0,
    },
    {
        "name": "Банковская карта",
        "kind": "card",
        "description": "Терминал эквайринга",
        "commission_pct": "1.50",
        "is_active": True,
        "sort_order": 1,
    },
    {
        "name": "QR-оплата",
        "kind": "qr",
        "description": "Сканирование QR-кода",
        "commission_pct": "0.80",
        "is_active": True,
        "sort_order": 2,
    },
    {
        "name": "Мобильный кошелёк",
        "kind": "wallet",
        "description": "TojPay, DC Pay",
        "commission_pct": "1.20",
        "is_active": False,
        "sort_order": 3,
    },
]

DEFAULT_DISCOUNTS: list[dict] = [
    {
        "type": "discount",
        "name": "Скидка сотрудника",
        "description": "Применяется вручную кассиром",
        "kind": "percent",
        "value": "10.00",
        "is_active": True,
        "sort_order": 0,
    },
    {
        "type": "discount",
        "name": "Постоянный клиент",
        "description": "По карте лояльности",
        "kind": "percent",
        "value": "15.00",
        "is_active": True,
        "sort_order": 1,
    },
    {
        "type": "discount",
        "name": "Акция дня",
        "description": "Автоматическая скидка по расписанию",
        "kind": "percent",
        "value": "20.00",
        "is_active": False,
        "sort_order": 2,
    },
    {
        "type": "service",
        "name": "Сервисный сбор",
        "description": "Автоматически добавляется к каждому заказу",
        "kind": "percent",
        "value": "12.00",
        "is_active": True,
        "sort_order": 0,
    },
]

DEFAULT_CANCEL_REASONS: dict[str, list[str]] = {
    "item": [
        "Гость передумал",
        "Ошибка кассира",
        "Нет ингредиента",
        "Долго готовится",
        "Дубль позиции",
    ],
    "order": [
        "Гости ушли",
        "Ошибка кассира",
        "Технический сбой",
        "Долгое ожидание",
    ],
    "refund": [
        "Жалоба на качество",
        "Ошибка кассира",
        "Не та позиция",
        "Гость не доел",
    ],
}
