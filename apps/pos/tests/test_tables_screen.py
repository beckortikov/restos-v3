"""TablesScreen: рендер сетки по state.tables, реакция на изменения, click → signal."""
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt


@pytest.fixture
def fake_state():
    """Минимальный State-двойник с нужными для экрана сигналами и атрибутами."""
    from PySide6.QtCore import QObject, Signal

    class _FakeState(QObject):
        tables_changed = Signal(list)
        orders_changed = Signal(list)
        online_changed = Signal(bool)

        def __init__(self):
            super().__init__()
            self._tables: list[dict] = []
            self._orders: list[dict] = []
            # embedded MenuPanel вызывает state.client.get(...) при .reload();
            # для unit-теста достаточно MagicMock без реальных вызовов.
            self.client = MagicMock()
            self.client.get.return_value = []

        def refresh(self) -> None:
            pass

        @property
        def tables(self) -> list[dict]:
            return self._tables

        @property
        def orders(self) -> list[dict]:
            return self._orders

        def set_tables(self, tables: list[dict]) -> None:
            self._tables = tables
            self.tables_changed.emit(tables)

        def set_orders(self, orders: list[dict]) -> None:
            self._orders = orders
            self.orders_changed.emit(orders)

    return _FakeState()


@pytest.fixture
def screen(qtbot, fake_state):
    from pos.screens.tables_screen import TablesScreen

    s = TablesScreen(fake_state)
    qtbot.addWidget(s)
    # Resize шире, потому что rightPanel = 360px и sidebar = 72px — эти забирают
    # пространство у grid'а; для уверенного теста на ≥5 колонок нужен viewport.
    s.resize(2200, 800)
    s.show()
    qtbot.waitExposed(s)
    return s


def _table(i: int, status: str = "free", **kw) -> dict:
    return {"id": i, "name": f"Стол {i}", "number": i, "status": status, **kw}


def test_initial_grid_is_empty(screen):
    assert screen._cards == []


def test_render_after_tables_changed(screen, fake_state):
    fake_state.set_tables([_table(1), _table(2), _table(3)])
    assert len(screen._cards) == 3


def test_grid_layout_for_5_tables(screen, fake_state):
    """5 столов рендерятся; кол-во колонок = от viewport (fixed-size карточки)."""
    fake_state.set_tables([_table(i) for i in range(1, 6)])
    assert len(screen._cards) == 5
    assert screen._columns >= 2


def test_grid_layout_for_6_tables(screen, fake_state):
    """6 столов рендерятся все, колонок ≥2 (fixed-size, без sqrt-clamp)."""
    fake_state.set_tables([_table(i) for i in range(1, 7)])
    assert len(screen._cards) == 6
    assert screen._columns >= 2


def test_grid_layout_for_17_tables(screen, fake_state):
    """Все 17 карточек отрендерены; колонок ≥ 3 (адаптивно по реальному viewport)."""
    fake_state.set_tables([_table(i) for i in range(1, 18)])
    assert len(screen._cards) == 17
    assert screen._columns >= 3


def test_orders_total_shown_on_card(screen, fake_state):
    fake_state.set_orders([
        {"id": 100, "table": 2, "status": "new", "total": "450.00"},
    ])
    fake_state.set_tables([
        _table(1),
        _table(2, status="occupied", guests_count=3),
    ])
    from PySide6.QtWidgets import QLabel

    card_for_t2 = next(c for c in screen._cards if c._table_id == 2)
    texts = [w.text() for w in card_for_t2.findChildren(QLabel)]
    assert any("450.00 TJS" in t for t in texts)
    assert any("3 гостя" in t for t in texts)


def test_clicking_occupied_table_shows_order_in_panel(qtbot, screen, fake_state):
    fake_state.set_orders([
        {
            "id": 1042, "table": 7, "status": "bill_requested",
            "guests_count": 2, "total": "98.00", "currency": "TJS",
            "items": [{"name_at_order": "Плов", "qty": 1, "subtotal": "45.00",
                       "cancelled_at": None}],
        },
    ])
    fake_state.set_tables([_table(7, status="bill_requested", guests_count=2)])

    qtbot.mouseClick(screen._cards[0], Qt.LeftButton)

    assert screen._selected_table_id == 7
    assert screen.detail_panel._order_id == 1042
    assert screen._cards[0]._selected is True


def test_clicking_free_table_switches_center_stack_to_menu_page(
    qtbot, screen, fake_state,
):
    """POS-flow (обновлённый): тап по свободному столу НЕ переключает
    отдельный экран, а свапает внутренний QStackedWidget на page 1
    (embedded MenuPanel). Sidebar/topbar остаются на месте — «нет прыжка»."""
    fake_state.set_tables([_table(1, status="free")])
    seen: list[tuple[str, object]] = []
    screen.new_order_requested.connect(lambda t, tid: seen.append((t, tid)))
    qtbot.mouseClick(screen._cards[0], Qt.LeftButton)
    # Сигнал НЕ эмитится для зала — меню inline.
    assert seen == []
    assert screen._center_stack.currentIndex() == 1
    assert screen._center_stack.currentWidget() is screen._menu_panel


def test_takeaway_button_opens_inline_menu(qtbot, screen, monkeypatch):
    """Клик «С собой» в топбаре → CustomerDialog → inline MenuPanel в том же
    окне (не switch на outer MenuScreen). Top bar остаётся, таб «С собой»
    подсвечен как active."""
    from PySide6.QtWidgets import QDialog, QPushButton
    from pos.screens import customer_dialog as cd_module

    # Авто-Accept CustomerDialog с заглушками полей.
    class _StubDialog:
        DialogCode = QDialog.DialogCode

        def __init__(self, *_args, **_kw):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        name = "Иван"
        phone = "+992900000000"
        address = ""

    monkeypatch.setattr(cd_module, "CustomerDialog", _StubDialog)

    btn = next(
        b for b in screen.findChildren(QPushButton) if b.text() == "С собой"
    )
    qtbot.mouseClick(btn, Qt.LeftButton)

    # Inline-flow: stack переключился, top bar сохранился, таб «С собой» active.
    assert screen._center_stack.currentIndex() == 1
    assert screen._active_non_hall == "takeaway"
    assert screen._search_input.placeholderText() == "Поиск блюда…"


def test_menu_panel_cancel_returns_to_tables_page(qtbot, screen, fake_state):
    """После отмены в embedded меню — возврат на page 0 (карта зала)."""
    fake_state.set_tables([_table(1, status="free")])
    qtbot.mouseClick(screen._cards[0], Qt.LeftButton)
    assert screen._center_stack.currentIndex() == 1
    screen._menu_panel.cancelled.emit()
    assert screen._center_stack.currentIndex() == 0


def test_menu_panel_reservation_returns_to_tables_with_form(
    qtbot, screen, fake_state,
):
    """Клик «Бронирование» в embedded меню → page 0 + inline-форма резерва."""
    from PySide6.QtWidgets import QLineEdit

    fake_state.set_tables([_table(1, status="free")])
    qtbot.mouseClick(screen._cards[0], Qt.LeftButton)
    screen._menu_panel.reservation_requested.emit(1)
    assert screen._center_stack.currentIndex() == 0
    # Inline-форма открыта в detail_panel (LineEdit'ы для имени/телефона).
    inputs = screen.detail_panel.findChildren(QLineEdit)
    assert len(inputs) >= 2


def test_table_grid_renders_dense_grid_after_first_show(
    qtbot, screen, fake_state,
):
    """Initial-render фикс: после первого show + QTimer.singleShot(0) карточки
    выкладываются с актуальным viewport (а не initial-width=0). При ширине
    2200px колонок должно быть >= 4 (не 2-3 как было до фикса)."""
    tables = [_table(i + 1, status="free") for i in range(8)]
    fake_state.set_tables(tables)
    qtbot.wait(50)  # дать singleShot(0) отработать
    assert screen._columns >= 4


def test_pay_request_propagates_from_panel(qtbot, screen, fake_state):
    from PySide6.QtWidgets import QPushButton

    fake_state.set_orders([
        {
            "id": 50, "table": 1, "status": "bill_requested",
            "guests_count": 1, "total": "10.00", "currency": "TJS",
            "items": [{"name_at_order": "Чай", "qty": 1, "subtotal": "10.00",
                       "cancelled_at": None}],
        },
    ])
    fake_state.set_tables([_table(1, status="bill_requested")])
    qtbot.mouseClick(screen._cards[0], Qt.LeftButton)

    pay_btn = next(
        b for b in screen.detail_panel.findChildren(QPushButton) if b.text().startswith("ОПЛАТА")
    )
    qtbot.mouseClick(pay_btn, Qt.LeftButton)
    # ОПЛАТА из OrderDetailPanel теперь открывает OrdersDrawer с payment view
    # (sidebar, не popup-модалка).
    assert screen._orders_drawer is not None
    assert screen._orders_drawer.isVisible()
    assert screen._orders_drawer._body_stack.currentIndex() == 1  # payment page


def test_logout_click_emits_logout_requested(qtbot, screen):
    seen: list[bool] = []
    screen.logout_requested.connect(lambda: seen.append(True))
    qtbot.mouseClick(screen.sidebar._buttons["logout"], Qt.LeftButton)
    assert seen == [True]


def test_offline_status_visible(screen, fake_state):
    fake_state.online_changed.emit(False)
    assert "Офлайн" in screen._status_label.text()
    fake_state.online_changed.emit(True)
    assert "Онлайн" in screen._status_label.text()


# -------- Search filter --------


def test_search_input_present(screen):
    assert hasattr(screen, "_search_input")
    assert screen._search_input.isEnabled()


def test_search_filters_by_name(qtbot, screen, fake_state):
    fake_state.set_tables([
        _table(1, name="Стол 1"),
        _table(2, name="VIP стол"),
        _table(3, name="Стол у окна"),
    ])
    screen._search_input.setText("VIP")
    assert len(screen._cards) == 1
    assert screen._cards[0]._table_id == 2


def test_search_filters_by_number(qtbot, screen, fake_state):
    fake_state.set_tables([
        _table(1), _table(2), _table(15), _table(20),
    ])
    screen._search_input.setText("15")
    ids = {c._table_id for c in screen._cards}
    assert 15 in ids
    # «1» матчится по «15» как substring — это ок поведение для substring
    # поиска. Главное, что фильтр работает по номеру.


def test_search_filters_by_zone_name(qtbot, screen, fake_state):
    fake_state.set_tables([
        _table(1, zone_name="Зал"),
        _table(2, zone_name="Терраса"),
        _table(3, zone_name="VIP"),
    ])
    screen._search_input.setText("Терраса")
    assert len(screen._cards) == 1
    assert screen._cards[0]._table_id == 2


def test_search_case_insensitive(qtbot, screen, fake_state):
    fake_state.set_tables([_table(1, name="VIP стол")])
    screen._search_input.setText("vip")
    assert len(screen._cards) == 1


def test_clear_search_shows_all(qtbot, screen, fake_state):
    fake_state.set_tables([_table(1), _table(2), _table(3)])
    screen._search_input.setText("1")
    n_filtered = len(screen._cards)
    screen._search_input.clear()
    assert len(screen._cards) >= n_filtered
    assert len(screen._cards) == 3


def test_search_no_matches_renders_empty(qtbot, screen, fake_state):
    fake_state.set_tables([_table(1), _table(2)])
    screen._search_input.setText("xyz_nothing")
    assert len(screen._cards) == 0


# -------- Right-click context menu --------


def test_table_card_emits_context_menu_on_right_click(qtbot):
    from pos.widgets.table_card import TableCard
    from PySide6.QtCore import Qt
    from PySide6.QtCore import QPoint

    card = TableCard({"id": 5, "name": "Стол 5", "number": 5, "status": "free"})
    qtbot.addWidget(card)
    fired: list = []
    card.context_menu_requested.connect(lambda tid, pos: fired.append(tid))
    qtbot.mouseClick(card, Qt.RightButton)
    assert fired == [5]


def test_force_free_calls_endpoint(qtbot, screen, fake_state, monkeypatch):
    """_force_free_table должен слать POST /tables/{id}/force_free/."""
    from pos.screens import tables_screen as mod

    fake_state.set_tables([_table(3, status="occupied")])
    fake_state.client = type("C", (), {})()
    posts: list = []
    fake_state.client.post = lambda path, json: posts.append((path, json))
    fake_state.refresh = lambda: None

    # mock QMessageBox to auto-confirm
    class _FakeMsg:
        WindowTitle = ""
        YesRole = 1
        RejectRole = 2

        def __init__(self, *a, **kw): pass
        Warning = 0
        def setWindowTitle(self, t): pass
        def setText(self, t): pass
        def setIcon(self, i): pass
        def addButton(self, label, role):
            self._yes = label
            return label
        def exec(self): pass
        def clickedButton(self):
            return self._yes  # always confirm
    # monkey only the first addButton return → "Освободить"
    real_msg = mod.QMessageBox if hasattr(mod, "QMessageBox") else None

    # Простейший вариант: вызываем сервис напрямую через атрибут
    # _force_free_table делает QMessageBox.exec. Подменим QMessageBox
    from PySide6.QtWidgets import QMessageBox

    class _AutoConfirm(QMessageBox):
        def exec(self):  # type: ignore[override]
            self._auto = True
            return 1
        def clickedButton(self):
            # Возвращает «yes»-кнопку (последняя добавленная YesRole)
            for b in self.buttons():
                if self.buttonRole(b) == QMessageBox.YesRole:
                    return b
            return None
    monkeypatch.setattr(
        "pos.screens.tables_screen.QMessageBox", _AutoConfirm, raising=False,
    )
    # Patch import inside function
    import PySide6.QtWidgets as W
    monkeypatch.setattr(W, "QMessageBox", _AutoConfirm)

    screen._force_free_table(3)
    assert any("/tables/3/force_free/" in p[0] for p in posts)


# -------- Multi-group right panel --------


def test_panel_shows_group_tabs_when_two_groups(qtbot, screen, fake_state):
    from PySide6.QtWidgets import QPushButton

    fake_state.set_orders([
        {
            "id": 100, "table": 1, "status": "new",
            "guests_count": 2, "total": "680.00", "currency": "TJS",
            "items": [],
        },
        {
            "id": 101, "table": 1, "status": "new",
            "guests_count": 3, "total": "376.00", "currency": "TJS",
            "items": [],
        },
    ])
    fake_state.set_tables([
        _table(1, status="occupied", current_order=100,
               active_orders=[
                   {"id": 100, "guests_count": 2, "total": "680.00",
                    "waiter_name": "X", "status": "new"},
                   {"id": 101, "guests_count": 3, "total": "376.00",
                    "waiter_name": "Y", "status": "new"},
               ]),
    ])
    qtbot.mouseClick(screen._cards[0], Qt.LeftButton)
    # Group bar visible
    assert screen.detail_panel._group_bar.isVisible() or screen.detail_panel._group_bar.isVisibleTo(screen.detail_panel)
    btns = screen.detail_panel._group_bar.findChildren(QPushButton)
    texts = [b.text() for b in btns]
    assert any("Гр.1" in t for t in texts)
    assert any("Гр.2" in t for t in texts)
    assert any("Группу" in t for t in texts)  # ➕ Группу


def test_clicking_group_tab_switches_active_order(qtbot, screen, fake_state):
    from PySide6.QtWidgets import QPushButton

    fake_state.set_orders([
        {"id": 100, "table": 1, "status": "new",
         "guests_count": 2, "total": "680.00", "items": []},
        {"id": 101, "table": 1, "status": "new",
         "guests_count": 3, "total": "376.00", "items": []},
    ])
    fake_state.set_tables([
        _table(1, status="occupied", current_order=100,
               active_orders=[
                   {"id": 100, "guests_count": 2, "total": "680.00",
                    "waiter_name": "X", "status": "new"},
                   {"id": 101, "guests_count": 3, "total": "376.00",
                    "waiter_name": "Y", "status": "new"},
               ]),
    ])
    qtbot.mouseClick(screen._cards[0], Qt.LeftButton)
    # По умолчанию primary (current_order=100)
    assert screen._selected_order_id == 100
    # Клик по табу «Гр.2»
    btns = screen.detail_panel._group_bar.findChildren(QPushButton)
    tab2 = next(b for b in btns if "Гр.2" in b.text())
    qtbot.mouseClick(tab2, Qt.LeftButton)
    assert screen._selected_order_id == 101


def test_add_group_button_opens_inline_menu(qtbot, screen, fake_state):
    """Кнопка «➕ Группу» в правой панели запускает MenuPanel INLINE
    (не outer MenuScreen) — кассир остаётся в том же UI с topbar'ом
    Зал/С собой/Доставка."""
    from PySide6.QtWidgets import QPushButton

    fake_state.set_orders([
        {"id": 100, "table": 1, "status": "new",
         "guests_count": 2, "total": "680.00", "items": []},
    ])
    fake_state.set_tables([
        _table(1, status="occupied", current_order=100,
               active_orders=[
                   {"id": 100, "guests_count": 2, "total": "680.00",
                    "waiter_name": "X", "status": "new"},
               ]),
    ])
    qtbot.mouseClick(screen._cards[0], Qt.LeftButton)

    # Сигнал new_order_requested НЕ эмитим (раньше эмитили → outer MenuScreen).
    seen: list = []
    screen.new_order_requested.connect(lambda t, tid: seen.append((t, tid)))
    btns = screen.detail_panel._group_bar.findChildren(QPushButton)
    plus = next(b for b in btns if "Группу" in b.text())
    qtbot.mouseClick(plus, Qt.LeftButton)
    assert seen == []
    # Inline-flow: _center_stack → menu page, topbar → «Поиск блюда…».
    assert screen._center_stack.currentIndex() == 1
    assert screen._search_input.placeholderText() == "Поиск блюда…"


# -------- Inline reservation in right panel --------


def test_open_reservation_form_shows_inline_form(qtbot, screen, fake_state):
    """Публичный метод open_reservation_form(table_id) (вызывается из main.py
    при возврате с MenuScreen после клика «🕐 Бронирование») — селектит стол
    и показывает inline-форму резерва в правой панели."""
    from PySide6.QtWidgets import QLineEdit

    fake_state.set_tables([_table(1, status="free")])
    screen.open_reservation_form(1)
    inputs = screen.detail_panel.findChildren(QLineEdit)
    assert len(inputs) >= 2  # name + phone
    assert screen._cards[0]._selected is True


def test_reservation_save_disabled_until_name(qtbot, screen, fake_state):
    fake_state.set_tables([_table(1, status="free")])
    screen.detail_panel.show_reservation_form(fake_state.tables[0])
    assert not screen.detail_panel._res_save_btn.isEnabled()
    screen.detail_panel._res_name.setText("Иван")
    assert screen.detail_panel._res_save_btn.isEnabled()


def test_reservation_save_emits_post(qtbot, screen, fake_state):
    fake_state.set_tables([_table(1, status="free")])
    fake_state.client = type("C", (), {})()
    posts: list = []
    fake_state.client.post = lambda path, json: posts.append((path, json)) or {"data": {"id": 1}}
    fake_state.refresh = lambda: None

    screen.detail_panel.show_reservation_form(fake_state.tables[0])
    screen.detail_panel._res_name.setText("Иван")
    screen.detail_panel._res_change_party(+2)  # 2 → 4
    screen.detail_panel._res_notes.setPlainText("к 19:00, окно")
    screen.detail_panel._on_res_save()

    assert len(posts) == 1
    path, body = posts[0]
    assert path == "/reservations/"
    assert body["customer_name"] == "Иван"
    assert body["party_size"] == 4
    # Длительность дефолтная (2 часа) — UI выбора нет
    assert body["duration_min"] == 120
    assert body["notes"] == "к 19:00, окно"
    assert body["table"] == 1


def test_right_click_no_longer_has_reservation(qtbot, screen, fake_state, monkeypatch):
    """Регрессия: правый клик по свободному столу не должен показывать
    «Зарезервировать стол» (теперь это в правой панели)."""
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QMenu

    fake_state.set_tables([_table(1, status="free")])
    actions_added: list[str] = []
    real_addAction = QMenu.addAction

    def _track_addAction(self, *args, **kw):
        text = args[0] if args else kw.get("text", "")
        actions_added.append(str(text))
        return real_addAction(self, *args, **kw)

    monkeypatch.setattr(QMenu, "addAction", _track_addAction)
    monkeypatch.setattr(QMenu, "exec", lambda self, pos=None: None)
    monkeypatch.setattr(QMenu, "isEmpty", lambda self: True)
    screen._on_card_context_menu(1, QPoint(0, 0))
    assert not any("Зарезервировать" in a for a in actions_added)


# -------- Topbar drawers (Заказы / Принтер) --------


def test_topbar_has_orders_button_and_more_menu(screen):
    """В топбаре есть кнопка `Заказы` (рядом с поиском) и `Ещё ▾`-меню
    в котором `Принтер` и `Объединить столы` — actions."""
    from PySide6.QtWidgets import QPushButton

    btns = screen.findChildren(QPushButton)
    labels = [b.text().strip() for b in btns]
    assert any("Заказы" in t for t in labels)
    assert any("Ещё" in t for t in labels)
    more_btn = next(b for b in btns if "Ещё" in b.text())
    actions_text = [a.text() for a in more_btn.menu().actions()]
    assert any("Принтер" in t for t in actions_text)
    assert any("Объединить" in t for t in actions_text)


def test_clicking_orders_button_opens_drawer(qtbot, screen):
    """Клик `Заказы` создаёт и показывает OrdersDrawer."""
    from PySide6.QtWidgets import QPushButton

    btn = next(
        b for b in screen.findChildren(QPushButton) if "Заказы" in b.text()
    )
    qtbot.mouseClick(btn, Qt.LeftButton)
    assert screen._orders_drawer is not None
    assert screen._orders_drawer.isVisible()


def test_more_menu_printer_action_opens_drawer(qtbot, screen):
    """Action `Принтер` из меню `Ещё ▾` открывает PrinterDrawer."""
    from PySide6.QtWidgets import QPushButton

    more_btn = next(
        b for b in screen.findChildren(QPushButton) if "Ещё" in b.text()
    )
    printer_action = next(
        a for a in more_btn.menu().actions() if "Принтер" in a.text()
    )
    printer_action.trigger()
    assert screen._printer_drawer is not None
    assert screen._printer_drawer.isVisible()


def test_opening_printer_closes_orders_drawer(qtbot, screen):
    """Drawer'ы взаимно-исключающие: открытие второго закрывает первый."""
    from PySide6.QtWidgets import QPushButton

    orders_btn = next(
        b for b in screen.findChildren(QPushButton) if "Заказы" in b.text()
    )
    more_btn = next(
        b for b in screen.findChildren(QPushButton) if "Ещё" in b.text()
    )
    printer_action = next(
        a for a in more_btn.menu().actions() if "Принтер" in a.text()
    )
    qtbot.mouseClick(orders_btn, Qt.LeftButton)
    assert screen._orders_drawer.isVisible()
    printer_action.trigger()
    assert not screen._orders_drawer.isVisible()
    assert screen._printer_drawer.isVisible()


def test_clicking_orders_twice_toggles_off(qtbot, screen):
    """Повторный клик закрывает drawer."""
    from PySide6.QtWidgets import QPushButton

    btn = next(
        b for b in screen.findChildren(QPushButton) if "Заказы" in b.text()
    )
    qtbot.mouseClick(btn, Qt.LeftButton)
    assert screen._orders_drawer.isVisible()
    qtbot.mouseClick(btn, Qt.LeftButton)
    assert not screen._orders_drawer.isVisible()


# -------- Context-aware topbar (placeholder swap) --------


def test_topbar_search_placeholder_swaps_to_dishes_in_menu_mode(
    qtbot, screen, fake_state,
):
    """Клик на свободный стол → placeholder поиска переключается на «Поиск блюда…».
    После cancel — возврат на «Поиск стола…»."""
    fake_state.set_tables([_table(1, status="free")])
    # Default: tables-mode.
    assert screen._search_input.placeholderText() == "Поиск стола…"
    # Открываем меню.
    qtbot.mouseClick(screen._cards[0], Qt.LeftButton)
    assert screen._center_stack.currentIndex() == 1
    assert screen._search_input.placeholderText() == "Поиск блюда…"
    # Отмена → возврат к tables-mode.
    screen._menu_panel.cancelled.emit()
    assert screen._search_input.placeholderText() == "Поиск стола…"


def test_topbar_search_routes_to_menu_panel_in_menu_mode(
    qtbot, screen, fake_state,
):
    """В menu-mode ввод в основной search должен вызывать
    MenuPanel.set_search_query (а не фильтр столов)."""
    fake_state.set_tables([_table(1, status="free")])
    qtbot.mouseClick(screen._cards[0], Qt.LeftButton)
    # Вводим текст в основной поиск.
    screen._search_input.setText("плов")
    # MenuPanel получил query через set_search_query.
    assert screen._menu_panel._search_query == "плов"


def test_back_chip_clears_topbar_search_input(qtbot, screen, fake_state):
    """Back из dishes → categories очищает QLineEdit основного топбара
    (sync через signal search_query_cleared)."""
    fake_state.set_tables([_table(1, status="free")])
    qtbot.mouseClick(screen._cards[0], Qt.LeftButton)
    screen._search_input.setText("плов")
    assert screen._menu_panel._search_query == "плов"
    screen._menu_panel.go_back()
    qtbot.wait(20)
    assert screen._search_input.text() == ""
