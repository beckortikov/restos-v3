"""Настройки — frames 18-22 в design/pos_cashier.pen.

Полноэкранный screen со структурой:
- sidebar 72px (settings active)
- nav-panel 240px со списком секций (Принтеры, Меню, Пользователи, ...)
- main content area — рендер выбранной секции

В этой итерации реализована секция «Принтеры» (frame 18).
Остальные секции — placeholder'ы под последующие итерации.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from pos.resources.tokens import COLORS, RADIUS, SPACING
from pos.state import State
from pos.widgets.sidebar import Sidebar


# Секции (key, label) в том порядке как в дизайне
SETTINGS_SECTIONS: list[tuple[str, str]] = [
    ("printers", "Принтеры"),
    ("print_journal", "Журнал печати"),
    ("menu", "Меню и категории"),
    ("tables", "Зоны и столы"),
    ("inventory", "Склад"),
    ("cooking", "Заготовки"),
    ("users", "Пользователи"),
    ("payroll", "Зарплата"),
    ("payment", "Способы оплаты"),
    ("discounts", "Скидки и сервис"),
    ("reports", "Отчёты"),
    ("analytics", "Аналитика"),
    ("audit", "Журнал действий"),
    ("general", "Общие"),
    ("about", "О системе"),
]


class SettingsScreen(QWidget):
    """Сигналы:
        logout_requested()
        nav_requested(str)  # tables | orders | menu
        open_shift_report() — из Reports section
        open_history() — из Reports section
    """

    logout_requested = Signal()
    nav_requested = Signal(str)
    open_shift_report = Signal()
    open_history = Signal()
    open_shift_history = Signal()
    open_reservations = Signal()
    open_abc_menu = Signal()

    def __init__(self, state: State, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self._active_section: str = "printers"
        self._nav_buttons: dict[str, QPushButton] = {}
        self._section_widgets: dict[str, QWidget] = {}
        self._build()
        self.set_section("printers")

    # -------- public --------

    def set_section(self, key: str) -> None:
        if key not in {s[0] for s in SETTINGS_SECTIONS}:
            return
        self._active_section = key
        for k, btn in self._nav_buttons.items():
            btn.setChecked(k == key)
            btn.setStyleSheet(self._nav_btn_qss(active=(k == key)))
        if key in self._section_widgets:
            self._content_stack.setCurrentWidget(self._section_widgets[key])
        # Перезагружаем секцию (если поддерживает)
        section = self._section_widgets.get(key)
        if section and hasattr(section, "reload"):
            section.reload()

    # -------- build --------

    def _build(self) -> None:
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"SettingsScreen {{ background-color: {COLORS['bg_light']}; }}"
        )
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = Sidebar(active="settings")
        self.sidebar.nav_clicked.connect(self._on_nav)
        root.addWidget(self.sidebar)

        # Settings nav-panel 240
        nav_panel = self._build_nav_panel()
        root.addWidget(nav_panel)

        # Main content stacked
        self._content_stack = QStackedWidget()
        self._content_stack.setStyleSheet(
            f"QStackedWidget {{ background: {COLORS['bg_light']}; }}"
        )
        # Build sections
        from pos.screens.settings_sections.about_section import AboutSection
        from pos.screens.settings_sections.audit_section import AuditSection
        from pos.screens.settings_sections.discounts_section import DiscountsSection
        from pos.screens.settings_sections.general_section import GeneralSection
        from pos.screens.settings_sections.menu_section import MenuSection
        from pos.screens.settings_sections.tables_section import TablesSection
        from pos.screens.settings_sections.payments_section import PaymentsSection
        from pos.screens.settings_sections.printers_section import PrintersSection
        from pos.screens.settings_sections.reports_section import ReportsSection
        from pos.screens.settings_sections.users_section import UsersSection

        printers = PrintersSection(client=self.state.client)
        self._section_widgets["printers"] = printers
        self._content_stack.addWidget(printers)

        from pos.screens.settings_sections.print_journal_section import (
            PrintJournalSection,
        )
        print_journal = PrintJournalSection(client=self.state.client)
        self._section_widgets["print_journal"] = print_journal
        self._content_stack.addWidget(print_journal)

        menu_section = MenuSection(client=self.state.client)
        self._section_widgets["menu"] = menu_section
        self._content_stack.addWidget(menu_section)

        tables_section = TablesSection(client=self.state.client)
        self._section_widgets["tables"] = tables_section
        self._content_stack.addWidget(tables_section)

        from pos.screens.settings_sections.inventory_section import (
            InventorySection,
        )
        inventory_section = InventorySection(client=self.state.client)
        self._section_widgets["inventory"] = inventory_section
        self._content_stack.addWidget(inventory_section)

        users = UsersSection(client=self.state.client)
        self._section_widgets["users"] = users
        self._content_stack.addWidget(users)

        payments = PaymentsSection(client=self.state.client)
        self._section_widgets["payment"] = payments
        self._content_stack.addWidget(payments)

        discounts = DiscountsSection(client=self.state.client)
        self._section_widgets["discounts"] = discounts
        self._content_stack.addWidget(discounts)

        reports = ReportsSection()
        reports.open_shift_report.connect(self.open_shift_report.emit)
        reports.open_history.connect(self.open_history.emit)
        reports.open_shift_history.connect(self.open_shift_history.emit)
        reports.open_reservations.connect(self.open_reservations.emit)
        reports.open_abc_menu.connect(self.open_abc_menu.emit)
        self._section_widgets["reports"] = reports
        self._content_stack.addWidget(reports)

        from pos.screens.settings_sections.cooking_section import CookingSection
        cooking = CookingSection(client=self.state.client)
        self._section_widgets["cooking"] = cooking
        self._content_stack.addWidget(cooking)

        from pos.screens.settings_sections.payroll_section import PayrollSection
        from pos.screens.settings_sections.analytics_section import AnalyticsSection

        payroll = PayrollSection(client=self.state.client)
        self._section_widgets["payroll"] = payroll
        self._content_stack.addWidget(payroll)

        analytics = AnalyticsSection(client=self.state.client)
        self._section_widgets["analytics"] = analytics
        self._content_stack.addWidget(analytics)

        audit = AuditSection(client=self.state.client)
        self._section_widgets["audit"] = audit
        self._content_stack.addWidget(audit)

        general = GeneralSection(client=self.state.client)
        self._section_widgets["general"] = general
        self._content_stack.addWidget(general)

        about = AboutSection()
        self._section_widgets["about"] = about
        self._content_stack.addWidget(about)

        root.addWidget(self._content_stack, 1)

    def _build_nav_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("settingsNav")
        panel.setFixedWidth(240)
        panel.setStyleSheet(
            f"#settingsNav {{"
            f"  background: {COLORS['bg_white']};"
            f"  border-right: 1px solid {COLORS['border_light']};"
            f"}}"
        )
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, SPACING["xl"], 0, SPACING["xl"])
        v.setSpacing(0)

        title = QLabel("Настройки")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 16pt; font-weight: 700;"
            f" padding: 0 20px 16px 20px;"
        )
        v.addWidget(title)

        for key, label in SETTINGS_SECTIONS:
            btn = self._make_nav_btn(key, label)
            self._nav_buttons[key] = btn
            v.addWidget(btn)

        v.addStretch(1)
        return panel

    def _make_nav_btn(self, key: str, label: str) -> QPushButton:
        btn = QPushButton(label)
        btn.setCheckable(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setFixedHeight(48)
        btn.setStyleSheet(self._nav_btn_qss(active=False))
        btn.clicked.connect(lambda _checked=False, k=key: self.set_section(k))
        return btn

    def _nav_btn_qss(self, *, active: bool) -> str:
        if active:
            return (
                f"QPushButton {{"
                f"  background: {COLORS['accent_orange']};"
                f"  color: {COLORS['text_white']};"
                f"  border: none; border-radius: 0;"
                f"  text-align: left; padding: 0 20px;"
                f"  font-size: 12pt; font-weight: 600;"
                f"}}"
            )
        return (
            f"QPushButton {{"
            f"  background: transparent;"
            f"  color: {COLORS['text_primary']};"
            f"  border: none;"
            f"  text-align: left; padding: 0 20px;"
            f"  font-size: 12pt; font-weight: 500;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )

    # -------- handlers --------

    def _on_nav(self, name: str) -> None:
        if name == "logout":
            self.logout_requested.emit()
        elif name in {"tables", "orders", "menu"}:
            self.nav_requested.emit(name)
