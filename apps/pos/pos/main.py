import logging
import sys

# Версия POS-клиента — отправляется в heartbeat для super-admin'а
APP_VERSION = "0.4.1"

# SA-7+ — на Windows скрыть console-окна subprocess'ов (postgres.exe, pg_ctl.exe).
# Применяется до любых import'ов, которые могут spawn'ить child процессы.
if sys.platform == "win32":
    try:
        from pos.services.embedded_backend import _patch_subprocess_hide_window
        _patch_subprocess_hide_window()
    except Exception:
        pass

from PySide6.QtCore import Qt
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from pos.auth.pin_login_screen import PinLoginScreen
from pos.config import API_BASE_URL
from pos.screens.active_orders_screen import ActiveOrdersScreen
from pos.screens.close_shift_screen import CloseShiftScreen
from pos.screens.customer_dialog import CustomerDialog
from pos.screens.menu_screen import MenuScreen
from pos.screens.open_shift_screen import OpenShiftScreen
from pos.screens.order_history_screen import OrderHistoryScreen
from pos.screens.payment_dialog import PaymentDialog
from pos.screens.receipt_status_dialog import ReceiptStatusDialog
from pos.screens.settings_screen import SettingsScreen
from pos.screens.reservations_screen import ReservationsScreen
from pos.screens.shift_history_screen import ShiftHistoryScreen
from pos.screens.shift_report_screen import ShiftReportScreen
from pos.screens.kitchen_screen import KitchenScreen
from pos.screens.tables_screen import TablesScreen
from pos.state import get_state


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("RestOS — Кассир")
        self.resize(1366, 800)

        # Контейнер: вертикальный layout, сверху license-banner (тонкая
        # полоса), снизу stack экранов. Banner скрыт когда лицензия active+>7d.
        from pos.widgets.license_banner import LicenseBanner

        central = QWidget()
        clayout = QVBoxLayout(central)
        clayout.setContentsMargins(0, 0, 0, 0)
        clayout.setSpacing(0)
        self.license_banner = LicenseBanner()
        clayout.addWidget(self.license_banner)
        self.stack = QStackedWidget()
        clayout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.state = get_state()
        self.state.online_changed.connect(self._set_online)
        self.state.auth_expired.connect(self._on_auth_expired)
        self.state.license_changed.connect(self.license_banner.update_from_license)
        # License polling: каждые 10 минут refresh статус + heartbeat.
        self._license_timer = QTimer(self)
        self._license_timer.setInterval(10 * 60 * 1000)
        self._license_timer.timeout.connect(self._poll_license)
        self._cashier_name: str = ""
        self._shift_no: int = 0
        self._shift_id: int | None = None

        # SA-7 — экран активации лицензии (показывается если не активировано)
        from pos.screens.license_activation_screen import LicenseActivationScreen
        self.activation_screen = LicenseActivationScreen(self.state.client)
        self.activation_screen.activated.connect(self._on_license_activated)
        self.stack.addWidget(self.activation_screen)

        self.login_screen = PinLoginScreen()
        self.login_screen.logged_in.connect(self._on_login)
        self.stack.addWidget(self.login_screen)

        self.shift_screen = OpenShiftScreen(client=self.state.client)
        self.shift_screen.shift_opened.connect(self._on_shift_opened)
        self.shift_screen.cancelled.connect(self._on_logout)
        self.stack.addWidget(self.shift_screen)

        self.tables_screen = TablesScreen(self.state)
        self.tables_screen.logout_requested.connect(self._on_logout)
        # TablesScreen → compact PaymentDialog (frame 8 layout — 520px).
        self.tables_screen.pay_requested.connect(
            lambda oid: self._on_pay_requested(oid, compact=True)
        )
        self.tables_screen.nav_requested.connect(self._on_nav)
        self.tables_screen.new_order_requested.connect(self._on_new_order)
        self.tables_screen.add_items_requested.connect(self._on_add_items)
        self.tables_screen.pre_bill_requested.connect(self._on_pre_bill)
        self.tables_screen.cancel_item_requested.connect(self._on_cancel_item)
        self.stack.addWidget(self.tables_screen)

        self.orders_screen = ActiveOrdersScreen(self.state)
        self.orders_screen.logout_requested.connect(self._on_logout)
        self.orders_screen.pay_requested.connect(self._on_pay_requested)
        self.orders_screen.order_clicked.connect(self._on_order_clicked)
        self.orders_screen.nav_requested.connect(self._on_nav)
        self.orders_screen.nav_to_history.connect(self._on_nav_to_history)
        self.stack.addWidget(self.orders_screen)

        self.menu_screen = MenuScreen(self.state)
        self.menu_screen.order_submitted.connect(self._on_menu_submitted)
        self.menu_screen.cancelled.connect(self._on_menu_cancelled)
        self.menu_screen.requested_logout.connect(self._on_logout)
        self.menu_screen.reservation_requested.connect(
            self._on_menu_reservation_requested,
        )
        self.stack.addWidget(self.menu_screen)

        self.report_screen = ShiftReportScreen(self.state)
        self.report_screen.back_requested.connect(self._on_report_back)
        self.report_screen.close_shift_requested.connect(self._on_report_close_shift)
        self.report_screen.logout_requested.connect(self._on_logout)
        self.stack.addWidget(self.report_screen)

        self.history_screen = OrderHistoryScreen(self.state)
        self.history_screen.nav_to_active.connect(self._on_nav_to_active_orders)
        self.history_screen.logout_requested.connect(self._on_logout)
        self.history_screen.refund_requested.connect(self._on_refund_requested)
        self.history_screen.reprint_requested.connect(self._on_reprint_requested)
        self.stack.addWidget(self.history_screen)

        self.shift_history_screen = ShiftHistoryScreen(self.state)
        self.shift_history_screen.back_requested.connect(
            lambda: self.stack.setCurrentWidget(self.settings_screen)
        )
        self.shift_history_screen.open_shift_report.connect(self.show_shift_report)
        self.shift_history_screen.logout_requested.connect(self._on_logout)
        self.stack.addWidget(self.shift_history_screen)

        self.reservations_screen = ReservationsScreen(self.state)
        self.reservations_screen.back_requested.connect(
            lambda: self.stack.setCurrentWidget(self.settings_screen)
        )
        self.reservations_screen.logout_requested.connect(self._on_logout)
        self.stack.addWidget(self.reservations_screen)

        from pos.screens.abc_menu_screen import AbcMenuScreen
        self.abc_menu_screen = AbcMenuScreen(self.state)
        self.abc_menu_screen.back_requested.connect(
            lambda: self.stack.setCurrentWidget(self.settings_screen)
        )
        self.stack.addWidget(self.abc_menu_screen)

        self.settings_screen = SettingsScreen(self.state)
        self.settings_screen.logout_requested.connect(self._on_logout)
        self.settings_screen.nav_requested.connect(self._on_nav)
        self.settings_screen.open_shift_report.connect(self._on_settings_open_shift_report)
        self.settings_screen.open_history.connect(self._on_nav_to_history)
        self.settings_screen.open_shift_history.connect(self._on_open_shift_history)
        self.settings_screen.open_reservations.connect(self._on_open_reservations)
        self.settings_screen.open_abc_menu.connect(self._on_open_abc_menu)
        self.stack.addWidget(self.settings_screen)

        # KDS-канбан для роли cook.
        self.kitchen_screen = KitchenScreen(self.state)
        self.kitchen_screen.logout_requested.connect(self._on_logout)
        self.stack.addWidget(self.kitchen_screen)

        # SA-7 — bootstrap: если лицензия не активирована локально, показываем
        # экран активации; иначе сразу PIN-login.
        from pos.resources.license_store import load_license
        if load_license() is None:
            self.stack.setCurrentWidget(self.activation_screen)
        else:
            self.stack.setCurrentWidget(self.login_screen)

        # Global QStatusBar убран — дублировал «● Online» внизу окна, тот же
        # индикатор уже есть внутри TablesScreen / ActiveOrdersScreen.
        # Для transient-сообщений (`status.showMessage`) оставляем заглушку,
        # которая просто игнорирует вызовы (не падаем в существующем коде).
        class _NoopStatus:
            def showMessage(self, *_a, **_k): pass
        self.status = _NoopStatus()
        # SSE стартуем только после логина — без токена коннект бы получил 401.

    def _on_license_activated(self, _payload: dict) -> None:
        """SA-7 — после успешной активации → переход на PIN-login."""
        self.stack.setCurrentWidget(self.login_screen)

    def _on_login(self, user: dict) -> None:
        self._cashier_name = user.get("full_name", "")
        # Подтянуть permissions/role в state (для скрытия UI и has_perm()).
        self.state.refresh_me()
        # После логина — обновим статус лицензии и стартуем поллинг + heartbeat.
        self._poll_license()
        self._license_timer.start()
        role = (user.get("role") or "").strip()
        # Cook уходит сразу в KDS-канбан, минуя OpenShiftScreen.
        if role == "cook":
            self.state.refresh()
            self.state.start_stream()
            self.kitchen_screen.set_cook(self._cashier_name)
            self.kitchen_screen.start_polling()
            self.stack.setCurrentWidget(self.kitchen_screen)
            return
        # Cashier (default) — OpenShiftScreen.
        existing = self.state.refresh_shift()
        self.shift_screen.reset(existing=existing)
        self.stack.setCurrentWidget(self.shift_screen)

    def _poll_license(self) -> None:
        """Тянет /license/status/ и шлёт heartbeat. Banner обновится через signal."""
        self.state.refresh_license()
        try:
            self.state.heartbeat(app_version=APP_VERSION)
        except Exception:
            pass

    def _on_shift_opened(self, shift: dict) -> None:
        """shift — dict из backend /shifts/open/ или /shifts/current/."""
        self.state.set_current_shift(shift)
        self._shift_id = int(shift.get("id") or 0)
        self._shift_no = int(shift.get("number") or 0)

        # Подтягиваем актуальное состояние перед стартом SSE.
        self.state.refresh()
        self.state.start_stream()

        self.tables_screen.set_cashier(self._cashier_name, self._shift_no)
        self.orders_screen.set_cashier_name(
            f"{self._cashier_name}  |  Смена №{self._shift_no}"
            if self._cashier_name else ""
        )
        self.menu_screen.set_cashier(self._cashier_name, self._shift_no)
        self.history_screen.set_cashier(self._cashier_name, self._shift_no)
        self.stack.setCurrentWidget(self.tables_screen)
        self.tables_screen.sidebar.set_active("tables")

    def _on_nav(self, name: str) -> None:
        if name == "tables":
            self.stack.setCurrentWidget(self.tables_screen)
            self.tables_screen.sidebar.set_active("tables")
        elif name == "orders":
            self.stack.setCurrentWidget(self.orders_screen)
            self.orders_screen.sidebar.set_active("orders")
        elif name == "settings":
            self.settings_screen.set_section("printers")
            self.stack.setCurrentWidget(self.settings_screen)
            self.settings_screen.sidebar.set_active("settings")

    def _show_stop_list(self) -> None:
        from pos.screens.stop_list_dialog import StopListDialog

        dlg = StopListDialog(client=self.state.client, parent=self)
        dlg.exec()

    def _on_nav_to_active_orders(self) -> None:
        self.stack.setCurrentWidget(self.orders_screen)
        self.orders_screen.sidebar.set_active("orders")

    def _on_nav_to_history(self) -> None:
        self.history_screen.reload()
        self.stack.setCurrentWidget(self.history_screen)
        self.history_screen.sidebar.set_active("orders")

    def _on_open_shift_history(self) -> None:
        """Из «Настройки → Отчёты → Архив смен» — список смен."""
        self.shift_history_screen.reload()
        self.stack.setCurrentWidget(self.shift_history_screen)

    def _on_open_reservations(self) -> None:
        """Из «Настройки → Отчёты → Резервации»."""
        self.reservations_screen.reload()
        self.stack.setCurrentWidget(self.reservations_screen)

    def _on_open_abc_menu(self) -> None:
        """Из «Настройки → Отчёты → ABC-анализ»."""
        self.abc_menu_screen.reload()
        self.stack.setCurrentWidget(self.abc_menu_screen)

    def _on_settings_open_shift_report(self) -> None:
        """Из «Настройки → Отчёты» — отчёт по текущей смене."""
        shift = self.state.current_shift
        if shift is None or not shift.get("id"):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "Нет открытой смены",
                "Откройте смену, чтобы увидеть отчёт.",
            )
            return
        self.show_shift_report(int(shift["id"]))

    def _on_logout(self) -> None:
        # Если есть открытая смена — сначала предложить её закрыть.
        shift = self.state.current_shift
        if shift is not None and shift.get("status") == "open":
            from PySide6.QtWidgets import QMessageBox

            box = QMessageBox(self)
            box.setWindowTitle("Закрытие смены")
            box.setText(
                f"У вас открыта смена №{shift.get('number')}.\n"
                "Закрыть смену перед выходом?"
            )
            box.setIcon(QMessageBox.Question)
            close_yes = box.addButton("Закрыть смену", QMessageBox.YesRole)
            logout_only = box.addButton("Выйти без закрытия", QMessageBox.NoRole)
            box.addButton("Отмена", QMessageBox.RejectRole)
            box.exec()

            if box.clickedButton() == close_yes:
                # Подтянуть свежий shift из API (актуальные revenue/balance).
                fresh = self.state.refresh_shift() or shift
                dlg = CloseShiftScreen(
                    shift=fresh, client=self.state.client, parent=self
                )
                dlg.shift_closed.connect(self._on_shift_closed_logout_flow)
                dlg.exec()
                return
            if box.clickedButton() == logout_only:
                self._do_logout()
                return
            return  # Отмена — остаёмся на экране

        self._do_logout()

    def _on_shift_closed_logout_flow(self, shift: dict) -> None:
        """После закрытия смены через диалог логаута — показать отчёт,
        потом logout. Кнопка «Назад» в отчёте → logout (смена уже закрыта)."""
        self.state.set_current_shift(None)
        self.show_shift_report(int(shift.get("id") or 0))

    def show_shift_report(self, shift_id: int) -> None:
        """Показать отчёт по смене (frame 15-16). Точка входа: после
        закрытия смены либо явный пункт меню (когда добавим)."""
        self.report_screen.set_shift_id(shift_id)
        self.stack.setCurrentWidget(self.report_screen)

    def _on_report_back(self) -> None:
        # Если смена ещё открыта — возврат на TablesScreen; иначе logout (смена
        # закрыта — больше делать в системе нечего).
        shift = self.state.current_shift
        if shift and shift.get("status") == "open":
            self.stack.setCurrentWidget(self.tables_screen)
            self.tables_screen.sidebar.set_active("tables")
        else:
            self._do_logout()

    def _on_report_close_shift(self) -> None:
        """Кнопка «Закрыть смену» из отчёта — открываем CloseShiftScreen."""
        # Пытаемся обновить shift с сервера: если в локальном state он
        # отсутствует, возможно его ещё не подгрузили после перехода на отчёт.
        fresh = self.state.refresh_shift()
        if fresh is None or fresh.get("status") != "open":
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.information(
                self, "Смена уже закрыта",
                "Эта смена уже закрыта — повторное закрытие невозможно.",
            )
            return
        dlg = CloseShiftScreen(shift=fresh, client=self.state.client, parent=self)
        dlg.shift_closed.connect(self._on_shift_closed_from_report)
        dlg.exec()

    def _on_shift_closed_from_report(self, shift: dict) -> None:
        """После закрытия из отчёта — обновляем экран отчёта (теперь read-only)."""
        self.state.set_current_shift(None)
        self.report_screen.set_shift_id(int(shift.get("id") or 0))

    def _do_logout(self) -> None:
        self.state.stop_stream()
        self.state.set_current_shift(None)
        self._shift_id = None
        self._shift_no = 0
        # Останавливаем кухонный поллинг (если был активен — для роли cook)
        if hasattr(self, "kitchen_screen"):
            self.kitchen_screen.stop_polling()
        # License polling тоже останавливаем (после logout не нужен)
        if hasattr(self, "_license_timer"):
            self._license_timer.stop()
        self.license_banner.hide()
        self.login_screen.session_store.clear()
        self.stack.setCurrentWidget(self.login_screen)
        self.login_screen.setFocus(Qt.OtherFocusReason)

    def _on_auth_expired(self) -> None:
        """Backend сказал 401 AUTH_TOKEN_EXPIRED (REST или SSE) — токен в
        keyring более не валиден. Чистим, останавливаем стрим, переключаем
        UI на PIN-login. Кассир введёт PIN и продолжит работу."""
        self.state.stop_stream()
        self.login_screen.session_store.clear()
        self.stack.setCurrentWidget(self.login_screen)
        self.login_screen.setFocus(Qt.OtherFocusReason)

    def _on_pay_requested(self, order_id: int, *, compact: bool = False) -> None:
        """Открыть PaymentDialog. compact=True для table-payment flow (frame 8)."""
        order = next(
            (o for o in self.state.orders if int(o["id"]) == order_id), None
        )
        if order is None:
            self.status.showMessage(f"Заказ #{order_id} не найден", 3000)
            return
        table = next(
            (t for t in self.state.tables if int(t["id"]) == int(order.get("table") or 0)),
            None,
        )
        dlg = PaymentDialog(
            order=order, table=table, client=self.state.client,
            parent=self, compact=compact,
        )
        dlg.order_paid.connect(self._on_order_paid)
        dlg.exec()

    def _on_order_paid(self, _order: dict, print_job: dict) -> None:
        if not print_job or not print_job.get("id"):
            return
        # Имя/адрес принтера для banner — попытка взять из state. В MVP
        # хардкодим лейбл; в Phase 2 будет /printing/printers/.
        receipt = ReceiptStatusDialog(
            print_job=print_job,
            client=self.state.client,
            printer_name="Касса",
            printer_address="",
            parent=self,
        )
        # Подписка на real-time обновления job через SSE.
        self.state.print_job_updated.connect(receipt.update_from_event)
        try:
            receipt.exec()
        finally:
            try:
                self.state.print_job_updated.disconnect(receipt.update_from_event)
            except (TypeError, RuntimeError):
                pass
        # После закрытия чек-модалки — состояние стола обновится через SSE
        # (close_order вызвал free_table, событие table.updated придёт).

    def _on_new_order(self, order_type: str, table_id) -> None:
        """Старт нового заказа: hall (с table_id) / takeaway / delivery."""
        if order_type in {"takeaway", "delivery"}:
            dlg = CustomerDialog(order_type=order_type, parent=self)
            if dlg.exec() != dlg.DialogCode.Accepted:
                return
            self.menu_screen.configure_create(
                order_type=order_type,
                customer_name=dlg.name,
                customer_phone=dlg.phone,
                customer_address=dlg.address,
            )
        else:
            self.menu_screen.configure_create(
                order_type="hall", table_id=int(table_id)
            )
        self.menu_screen.reload()
        self.stack.setCurrentWidget(self.menu_screen)

    def _on_add_items(self, order_id: int) -> None:
        """Дозаказ к существующему заказу — открыть menu в режиме add_items."""
        self.menu_screen.configure_add_items(int(order_id))
        self.menu_screen.reload()
        self.stack.setCurrentWidget(self.menu_screen)

    def _on_refund_requested(self, order_id: int) -> None:
        """Открыть RefundDialog (frame 13) — заказ DONE."""
        from pos.http_client import ApiError
        from pos.screens.refund_dialog import RefundDialog

        # Подтянуть полный заказ (history может содержать минимальный список).
        try:
            order = self.state.client.get(f"/orders/{order_id}/")
        except ApiError as e:
            self.status.showMessage(f"Не удалось загрузить заказ: {e.message}", 4000)
            return
        if not isinstance(order, dict) or order.get("status") != "done":
            self.status.showMessage(
                "Возврат возможен только по закрытым заказам", 4000
            )
            return
        dlg = RefundDialog(order=order, client=self.state.client, parent=self)
        dlg.refund_completed.connect(lambda _r: self.history_screen.reload())
        dlg.exec()

    def _on_reprint_requested(self, order_id: int) -> None:
        """Повторная печать чека закрытого заказа — POST /orders/{id}/reprint_receipt/."""
        from pos.http_client import ApiError

        try:
            self.state.client.post(
                f"/orders/{order_id}/reprint_receipt/",
                json={},
                idempotent=True,
            )
        except ApiError as e:
            self.status.showMessage(
                f"Не удалось напечатать: {e.message}", 4000
            )
            return
        self.status.showMessage(
            f"Чек заказа #{order_id} отправлен на печать (ДУБЛИКАТ)", 3000
        )

    def _on_cancel_item(self, order_id: int, item: dict) -> None:
        """Открыть CancelItemDialog для отмены позиции с причиной (frame 3).

        Список причин — из state.get_cancel_reasons('item') (кэш + API,
        админ настраивает через «Настройки»)."""
        from pos.screens.cancel_item_dialog import CancelItemDialog

        dlg = CancelItemDialog(
            order_id=int(order_id), item=item,
            client=self.state.client, parent=self,
            reasons=self.state.get_cancel_reasons("item"),
        )
        dlg.item_cancelled.connect(lambda _o: self.state.refresh())
        dlg.exec()

    def _on_pre_bill(self, order_id: int) -> None:
        """Открыть PreBillDialog (frame 5)."""
        from pos.screens.pre_bill_dialog import PreBillDialog

        order = next(
            (o for o in self.state.orders if int(o["id"]) == int(order_id)), None
        )
        if order is None:
            return
        table = next(
            (t for t in self.state.tables if int(t["id"]) == int(order.get("table") or 0)),
            None,
        )
        dlg = PreBillDialog(
            order=order, table=table, client=self.state.client, parent=self
        )
        dlg.pay_requested.connect(self._on_pay_requested)
        dlg.move_requested.connect(self._on_transfer_requested)
        dlg.split_requested.connect(self._on_split_requested)
        dlg.exec()

    def _on_split_requested(self, order_id: int) -> None:
        """Открыть SplitBillDialog (frame 6)."""
        from pos.screens.split_bill_dialog import SplitBillDialog

        order = next(
            (o for o in self.state.orders if int(o["id"]) == int(order_id)), None
        )
        if order is None:
            return
        dlg = SplitBillDialog(order=order, client=self.state.client, parent=self)
        dlg.exec()

    def _on_transfer_requested(self, order_id: int) -> None:
        """Открыть TransferDialog (frame 7)."""
        from pos.screens.transfer_dialog import TransferDialog

        order = next(
            (o for o in self.state.orders if int(o["id"]) == int(order_id)), None
        )
        if order is None:
            return
        dlg = TransferDialog(
            order=order,
            tables=list(self.state.tables),
            client=self.state.client,
            parent=self,
        )
        dlg.transferred.connect(lambda _o: self.state.refresh())
        dlg.exec()

    def _on_menu_submitted(self, _order_id: int) -> None:
        # Возвращаемся на TablesScreen (или ActiveOrders, если пришли оттуда —
        # пока всегда tables как home).
        self.stack.setCurrentWidget(self.tables_screen)
        self.tables_screen.sidebar.set_active("tables")

    def _on_menu_cancelled(self) -> None:
        self.stack.setCurrentWidget(self.tables_screen)
        self.tables_screen.sidebar.set_active("tables")

    def _on_menu_reservation_requested(self, table_id: int) -> None:
        """Кассир нажал «🕐 Бронирование» в MenuScreen при пустой корзине —
        возвращаемся на TablesScreen и сразу открываем форму резерва."""
        self.stack.setCurrentWidget(self.tables_screen)
        self.tables_screen.sidebar.set_active("tables")
        self.tables_screen.open_reservation_form(int(table_id))

    def _on_order_clicked(self, order_id: int) -> None:
        # Открытие OrderDetail из ActiveOrdersScreen — пока используется
        # детализация в TablesScreen (rightPanel). По клику переключаемся
        # на TablesScreen и выделяем стол этого заказа.
        order = next(
            (o for o in self.state.orders if int(o["id"]) == order_id), None
        )
        if order is None:
            return
        table_id = order.get("table")
        if table_id is None:
            return
        self.stack.setCurrentWidget(self.tables_screen)
        self.tables_screen.sidebar.set_active("tables")
        self.tables_screen._on_card_clicked(int(table_id), "detail")

    def _set_online(self, online: bool) -> None:
        # Глобальная QStatusBar убрана — индикатор Online/Offline теперь
        # рисуется внутри каждого экрана (TablesScreen, ActiveOrdersScreen).
        # Сохраняем функцию для обратной совместимости (вызывается из state).
        pass

    def closeEvent(self, event) -> None:  # noqa: N802
        self.state.stop_stream()
        super().closeEvent(event)


def _apply_light_palette(app: QApplication) -> None:
    """Гарантирует light-тему вне зависимости от OS dark mode.

    Без этого на macOS QDialog / QComboBox / QSpinBox / QListWidget берут
    тёмный системный палитра, и наши custom стили на QWidget не
    перекрывают их (стили действуют только на сам QWidget, но не на
    внутренние нативные элементы). Fusion + явная QPalette — гарантия
    одинакового вида на macOS / Windows / Linux.
    """
    from PySide6.QtGui import QColor, QPalette

    app.setStyle("Fusion")

    p = QPalette()
    white = QColor("#FFFFFF")
    bg = QColor("#F5F7FA")  # bg_light из tokens
    text = QColor("#1E293B")  # text_primary
    text_sec = QColor("#64748B")  # text_secondary
    accent = QColor("#D2691E")  # accent_orange (warm amber из restos brand)
    border = QColor("#E2E8F0")  # border_light

    p.setColor(QPalette.Window, bg)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, white)  # фон полей ввода / списков
    p.setColor(QPalette.AlternateBase, bg)
    p.setColor(QPalette.ToolTipBase, white)
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.Button, white)
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.BrightText, QColor("#FFFFFF"))
    p.setColor(QPalette.PlaceholderText, text_sec)
    p.setColor(QPalette.Highlight, accent)
    p.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    p.setColor(QPalette.Link, accent)
    p.setColor(QPalette.Mid, border)
    p.setColor(QPalette.Light, white)
    p.setColor(QPalette.Midlight, bg)
    p.setColor(QPalette.Dark, border)
    p.setColor(QPalette.Shadow, QColor("#CBD5E1"))

    # Disabled — приглушённые
    p.setColor(QPalette.Disabled, QPalette.WindowText, text_sec)
    p.setColor(QPalette.Disabled, QPalette.Text, text_sec)
    p.setColor(QPalette.Disabled, QPalette.ButtonText, text_sec)

    app.setPalette(p)


def _maybe_start_embedded_backend() -> "EmbeddedBackend | None":
    """Если RESTOS_EMBEDDED=1 (или это PyInstaller bundle) — поднимаем
    Postgres + Django внутри этого же exe. Иначе используем external backend
    (через RESTOS_API_URL)."""
    import os
    flag = os.environ.get("RESTOS_EMBEDDED", "")
    is_frozen = getattr(sys, "frozen", False)
    if not (flag == "1" or is_frozen):
        return None

    # Splash в Qt будет позже; пока — print.
    print("→ Starting embedded backend (Postgres + Django)...")
    try:
        from pos.services.embedded_backend import EmbeddedBackend
        eb = EmbeddedBackend(port=8000)
        eb.start(on_progress=lambda m: print(f"  · {m}"))
        return eb
    except Exception as exc:
        print(f"!! Embedded backend failed: {exc}")
        raise


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # SA-7+ single-exe: backend поднимается прежде чем GUI.
    embedded = _maybe_start_embedded_backend()

    app = QApplication(sys.argv)
    app.setApplicationName("RestOS Cashier")
    app.setOrganizationName("RestOS")
    _apply_light_palette(app)
    app.setStyleSheet(
        "QWidget { font-family: 'Inter', -apple-system, 'Segoe UI', sans-serif; }"
    )

    print(f"API base URL: {API_BASE_URL}")
    window = MainWindow()
    window.show()

    # При выходе — корректно остановить backend
    if embedded is not None:
        app.aboutToQuit.connect(embedded.stop)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
