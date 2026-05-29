from datetime import timedelta

import bcrypt
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone

from .managers import UserManager


class UserRole(models.TextChoices):
    CASHIER = "cashier", "Кассир"
    WAITER = "waiter", "Официант"
    COOK = "cook", "Повар"
    MANAGER = "manager", "Менеджер"


# Все доступные permission-ключи. Используются в `User.permissions` (override
# поверх дефолтов роли) и в `_check_perm(...)` сервисов/permission-классов.
ALL_PERMISSIONS: tuple[str, ...] = (
    # Заказы
    "orders.create",
    "orders.cancel",            # отмена позиции / заказа (свой)
    "orders.cancel_others",     # отмена чужого заказа
    "orders.discount_apply",    # применение скидки
    "orders.discount_large",    # скидка > 30% — требует manager-override
    "orders.refund",            # возврат закрытого заказа
    "orders.transfer",          # перенос заказа на другой стол
    # Смены
    "shifts.open",
    "shifts.close",
    "shifts.cash_op",           # cash_in/cash_out
    "shifts.x_report",          # печать промежуточного X-отчёта
    # Меню
    "menu.view",
    "menu.edit",                # CRUD блюд/категорий
    "menu.stop_list",           # переключение is_available
    # Настройки
    "settings.users",           # CRUD пользователей
    "settings.printers",        # настройки принтеров и станций
    "settings.payments",        # способы оплаты
    "settings.discounts",       # дефолтные скидки
    "settings.restaurant",      # параметры ресторана (kitchen_enabled и т.д.)
    "settings.audit",           # просмотр audit-лога
    # Резервации
    "reservations.manage",
    # Столы
    "tables.merge",
    "tables.force_free",
    # Кухня
    "kitchen.access",           # доступ к KDS-канбану
    # Менеджер-override
    "manager.override",         # подтверждение «опасных» действий чужим PIN-ом
)


# Дефолтные пресеты — что разрешено каждой роли «из коробки».
# `User.permissions` (JSON) может переопределить — если поле не пусто,
# используется как полный список вместо дефолта.
ROLE_DEFAULT_PERMISSIONS: dict[str, set[str]] = {
    "cashier": {
        "orders.create", "orders.cancel", "orders.discount_apply",
        "orders.refund", "orders.transfer",
        "shifts.open", "shifts.close", "shifts.cash_op", "shifts.x_report",
        "menu.view", "menu.stop_list",
        "settings.printers", "settings.payments", "settings.discounts",
        "reservations.manage",
        "tables.merge", "tables.force_free",
        "kitchen.access",
    },
    "waiter": {
        "orders.create", "orders.cancel",
        "menu.view",
        "reservations.manage",
        "tables.merge",
    },
    "cook": {
        "menu.view",
        "kitchen.access",
    },
    "manager": set(ALL_PERMISSIONS),  # менеджер может всё
}


class Restaurant(models.Model):
    name = models.CharField(max_length=128)
    address = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    currency = models.CharField(max_length=3, default="TJS")
    timezone = models.CharField(max_length=64, default="Asia/Dushanbe")
    pin_lock_timeout_min = models.PositiveSmallIntegerField(default=30)
    # Кол-во копий чека на печать (1=только гостю, 2=гость+бухгалтер, 3=…).
    # Применяется в enqueue_receipt_print: создаются N PrintJob-ов подряд.
    receipt_copies = models.PositiveSmallIntegerField(
        default=1,
        help_text="Сколько копий чека печатать при close_order (1-5)",
    )
    # Включена ли роль кухни в ресторане. Если False — позиции автоматически
    # становятся READY при создании (повара нет, готовят за стойкой).
    # Полезно для маленьких кафе/доставки без отдельного KDS.
    kitchen_enabled = models.BooleanField(
        default=True,
        help_text="Если False — позиции автоматически READY при создании заказа",
    )
    # Heartbeat от POS-клиента — обновляется раз в час через POST /heartbeat/.
    # Используется super-admin'ом чтобы видеть какие рестораны сейчас живые.
    last_heartbeat_at = models.DateTimeField(
        null=True, blank=True, db_index=True,
        help_text="Последний heartbeat от POS-клиента",
    )
    app_version = models.CharField(
        max_length=32, blank=True,
        help_text="Версия POS-клиента, который пингует",
    )
    # Manager-override порог: отмена заказа на сумму >= этого значения
    # требует подтверждения PIN-ом менеджера. 0 = выключено.
    manager_override_threshold_tjs = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Сумма заказа от которой отмена требует PIN менеджера. 0 = всегда без override.",
    )
    # Кастомизация чека — каждый ресторан хочет своё. Шапка обычно =
    # name + address (auto). `receipt_header_extra` — доп. строки.
    # Подвал — «Спасибо за визит!», «Wi-Fi: ...», «ИНН ...» и т.п.
    receipt_header_extra = models.TextField(
        blank=True,
        help_text="Доп. строки в шапке чека (после name/address/phone)",
    )
    receipt_footer = models.TextField(
        blank=True, default="Спасибо за визит!",
        help_text="Подвал чека. Поддерживает переносы строк.",
    )
    # Авто-открытие денежного ящика после печати чека (ESC/POS DLE команда).
    auto_open_cash_drawer = models.BooleanField(
        default=False,
        help_text="Автоматически открывать денежный ящик после печати чека",
    )
    # Phase 8B — глобальный toggle автосписания со склада. Если False — при
    # close_order никакой техкарты не списывается (режим «без склада»).
    tech_cards_enabled = models.BooleanField(
        default=True,
        help_text="Глобально включает автосписание ингредиентов по техкартам",
    )
    # «Виртуальный режим принтеров» — при включении ВСЕ PrintJob'ы пишутся
    # как .txt файл в PRINTER_OUTPUT_DIR (вместо отправки на железо).
    # Полезно для тестирования флоу заказ/дозаказ/оплата без физ. принтера.
    # Просмотр результатов — Settings → Журнал печати.
    printer_virtual_mode = models.BooleanField(
        default=False,
        help_text="Force-virtual: все принтеры пишут в файл вместо физ. печати",
    )
    # Phase 8A — разрешать ли расход хозтоваров при недостаточном остатке.
    # Если False — supply_expense блокируется ошибкой INSUFFICIENT_STOCK.
    supply_allow_negative = models.BooleanField(
        default=False,
        help_text="Разрешать выдачу хозтоваров при нулевом или отрицательном остатке",
    )
    # API-ключ ресторанного сервера для аутентификации в vendor cloud.
    # Хранится только на vendor cloud (как пароль) + в env-конфиге локального
    # сервера ресторана (RESTAURANT_API_KEY) для запросов к /license/issue_token/.
    # Никогда не публикуется через API — есть `has_api_key` в сериализаторах.
    api_key = models.CharField(
        max_length=128, blank=True, db_index=True,
        help_text="Секретный ключ для аутентификации restaurant-сервера в vendor cloud",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ресторан"
        verbose_name_plural = "Рестораны"

    def __str__(self) -> str:
        return self.name


class User(AbstractBaseUser, PermissionsMixin):
    restaurant = models.ForeignKey(
        Restaurant, on_delete=models.CASCADE, related_name="users", null=True, blank=True
    )
    # Закреплённая станция (для роли cook). Если задана — повар видит на KDS
    # только позиции категорий, привязанных к этой станции. Если null — все.
    kitchen_station = models.ForeignKey(
        "printing.PrintStation", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="cooks",
        help_text="Только для роли cook: фильтр KDS по PrintStation",
    )
    username = models.CharField(max_length=64, unique=True)
    full_name = models.CharField(max_length=128)
    role = models.CharField(max_length=16, choices=UserRole.choices, default=UserRole.WAITER)
    # Override permissions для конкретного пользователя.
    # null/empty list → используются дефолты роли (ROLE_DEFAULT_PERMISSIONS).
    # Не пустой → используется как полный список (override полностью).
    permissions = models.JSONField(
        default=list, blank=True,
        help_text="Список permission-keys или [] для использования дефолтов роли",
    )
    pin_hash = models.CharField(max_length=128, blank=True)
    # Phase 6 — Зарплата: ставка за час (0 = сотрудник работает за %, fixed
    # salary или не учитывается в TimeEntry). Изменения ставки не пересчитывают
    # существующие TimeEntry (там хранится snapshot).
    hourly_rate = models.DecimalField(
        "Ставка за час", max_digits=10, decimal_places=2, default=0,
        help_text="0 = не учитывается в табеле",
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    failed_pin_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"

    def __str__(self) -> str:
        return f"{self.full_name} ({self.get_role_display()})"

    def set_pin(self, raw_pin: str) -> None:
        self.pin_hash = bcrypt.hashpw(raw_pin.encode(), bcrypt.gensalt()).decode()

    def check_pin(self, raw_pin: str) -> bool:
        if not self.pin_hash:
            return False
        try:
            return bcrypt.checkpw(raw_pin.encode(), self.pin_hash.encode())
        except (ValueError, TypeError):
            return False

    # ---- permissions ----

    def get_permissions_set(self) -> set[str]:
        """Полный набор разрешённых permission-keys.

        Если `self.permissions` непуст → используется как override.
        Иначе → дефолты роли из `ROLE_DEFAULT_PERMISSIONS`.
        """
        if self.permissions:
            return set(self.permissions)
        return set(ROLE_DEFAULT_PERMISSIONS.get(self.role, set()))

    def has_perm_key(self, key: str) -> bool:
        """Проверка одного permission-key. Менеджер всегда True (override
        матрицу не делает — у него все права)."""
        if self.role == UserRole.MANAGER:
            return True
        return key in self.get_permissions_set()


class PinSession(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="pin_sessions")
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        verbose_name = "PIN-сессия"
        verbose_name_plural = "PIN-сессии"

    def is_valid(self) -> bool:
        return self.expires_at > timezone.now()

    def extend(self, minutes: int) -> None:
        self.expires_at = timezone.now() + timedelta(minutes=minutes)
        self.save(update_fields=["expires_at"])
