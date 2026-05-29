"""Бейджи DishCard: kind-эмодзи, weight-цена, low-stock chip."""


def test_kind_emoji_hidden(qtbot):
    """Эмодзи kind отключены — карточка не должна показывать иконку типа."""
    from pos.widgets.dish_card import DishCard

    card = DishCard(
        {
            "id": 1, "name": "Шашлык", "price": "25.00",
            "kind": "grill", "is_available": True,
        }
    )
    qtbot.addWidget(card)
    assert card._kind_lbl.text() == ""
    assert card._kind_lbl.isHidden()


def test_weight_price_shows_unit_size(qtbot):
    from pos.widgets.dish_card import DishCard

    card = DishCard({
        "id": 2, "name": "Курица гриль", "price": "12.00",
        "kind": "grill", "unit": "g", "unit_size": 100,
        "is_available": True,
    })
    qtbot.addWidget(card)
    assert "100" in card._price_lbl.text()
    assert "г" in card._price_lbl.text()


def test_piece_unit_no_extra_label(qtbot):
    from pos.widgets.dish_card import DishCard

    card = DishCard({
        "id": 3, "name": "Плов", "price": "45.00",
        "kind": "hot_kitchen", "unit": "piece",
        "is_available": True,
    })
    qtbot.addWidget(card)
    # Просто цена, без " / N"
    assert "/" not in card._price_lbl.text()


def test_batch_low_stock_orange_chip(qtbot):
    from pos.widgets.dish_card import DishCard

    card = DishCard({
        "id": 4, "name": "Плов утренний", "price": "45.00",
        "kind": "hot_kitchen",
        "is_batch_cooking": True, "prepared_qty": 3,
        "low_stock_threshold": 5, "is_low_stock": True,
        "is_available": True,
    })
    qtbot.addWidget(card)
    assert not card._lowstock_lbl.isHidden()
    assert "⚠" in card._lowstock_lbl.text()
    assert "3" in card._lowstock_lbl.text()


def test_batch_normal_green_counter(qtbot):
    from pos.widgets.dish_card import DishCard

    card = DishCard({
        "id": 5, "name": "Манты", "price": "30",
        "kind": "hot_kitchen",
        "is_batch_cooking": True, "prepared_qty": 12,
        "low_stock_threshold": 5, "is_low_stock": False,
        "is_available": True,
    })
    qtbot.addWidget(card)
    assert not card._lowstock_lbl.isHidden()
    assert "12" in card._lowstock_lbl.text()
    assert "⚠" not in card._lowstock_lbl.text()


def test_non_batch_no_lowstock_chip(qtbot):
    from pos.widgets.dish_card import DishCard

    card = DishCard({
        "id": 6, "name": "Чай", "price": "8",
        "kind": "drink", "is_batch_cooking": False,
        "is_available": True,
    })
    qtbot.addWidget(card)
    assert card._lowstock_lbl.isHidden()
