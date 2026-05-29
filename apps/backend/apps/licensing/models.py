"""License model — лицензия ресторана.

Бизнес-логика:
- Один Restaurant имеет 0..1 активных License (через `restaurant.license`).
- `started_at`/`expires_at` — окно активности.
- После `expires_at` начинается grace-период (`GRACE_DAYS` = 7 дней),
  в течение которого приложение ещё работает, но кассир видит баннер.
- После `expires_at + grace` — read-only mode (middleware режет writes).
- Можно явно `is_blocked=True` (за неуплату/нарушение) — мгновенный read-only.
- `last_heartbeat_at` обновляется POS-клиентом раз в час → видим живых.
- `app_version` — какая версия POS подключена (отслеживание апдейтов).

Управление через Django admin (`/admin/licensing/license/`):
- Вендор создаёт License на новый ресторан, плата вне системы (счёт/карта).
- Продление — кнопка «Renew +30/+90 дней» (action в admin).
- Блокировка — `is_blocked=True` + `block_reason`.
"""
from datetime import timedelta

from django.db import models
from django.utils import timezone


class LicensePlan(models.TextChoices):
    """Тарифные планы.

    В МVP различаются только периодом и ценой — feature-flags по плану
    добавим позже. Сейчас все планы дают полный функционал.
    """
    TRIAL = "trial", "Триал"
    START = "start", "Старт"
    BUSINESS = "business", "Бизнес"
    PRO = "pro", "Про"


class License(models.Model):
    """Лицензия ресторана. OneToOne с Restaurant — одна активная за раз."""

    GRACE_DAYS = 7  # сколько дней после expires_at работает с warning

    restaurant = models.OneToOneField(
        "users.Restaurant", on_delete=models.CASCADE,
        related_name="license",
    )
    plan = models.CharField(
        max_length=12, choices=LicensePlan.choices,
        default=LicensePlan.TRIAL,
    )
    license_key = models.CharField(
        max_length=64, blank=True, db_index=True,
        help_text="Уникальный ключ лицензии (генерим UUID, для offline-активации)",
    )
    started_at = models.DateTimeField(
        default=timezone.now,
        help_text="Дата активации (для триала — установка)",
    )
    expires_at = models.DateTimeField(
        help_text="Дата окончания. После + grace дней — read-only.",
    )
    is_blocked = models.BooleanField(
        default=False, db_index=True,
        help_text="Принудительная блокировка (за неуплату). Игнорирует grace.",
    )
    block_reason = models.CharField(max_length=255, blank=True)
    notes = models.TextField(
        blank=True,
        help_text="Внутренние заметки вендора (контакт, история платежей)",
    )
    # SA-7 — machine binding (Phase 8E)
    hardware_uuid = models.CharField(
        max_length=64, blank=True, default="", db_index=True,
        help_text=(
            "Windows BIOS UUID привязанной машины. Пустое = ещё не активирована."
            " Сбросить — для перепривязки при смене железа."
        ),
    )
    activated_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Когда POS впервые активировался на этой машине.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "licenses"
        verbose_name = "Лицензия"
        verbose_name_plural = "Лицензии"

    def __str__(self) -> str:
        return f"License<{self.restaurant.name}> {self.plan} until {self.expires_at:%d.%m.%Y}"

    # ---- computed ----

    @property
    def grace_until(self):
        """Конец grace-периода (когда полностью отключаемся в read-only)."""
        return self.expires_at + timedelta(days=self.GRACE_DAYS)

    @property
    def status(self) -> str:
        """Текущий статус: active / grace / expired / blocked."""
        if self.is_blocked:
            return "blocked"
        now = timezone.now()
        if now < self.expires_at:
            return "active"
        if now < self.grace_until:
            return "grace"
        return "expired"

    @property
    def is_writable(self) -> bool:
        """Можно ли писать в БД сейчас (false → read-only mode)."""
        return self.status in ("active", "grace")

    @property
    def days_left(self) -> int:
        """Дней до полной блокировки (включая grace). Может быть отрицательным."""
        delta = self.grace_until - timezone.now()
        return delta.days

    @property
    def days_to_expiry(self) -> int:
        """Дней до основной даты `expires_at` (без учёта grace)."""
        delta = self.expires_at - timezone.now()
        return delta.days

    # ---- helpers ----

    def renew(self, *, days: int) -> None:
        """Продлить на N дней от **большего** из (now, expires_at).

        Если лицензия ещё активна — продлеваем от expires_at.
        Если уже истекла — продлеваем от now (новый период).
        Снимает is_blocked.
        """
        from django.utils import timezone as _tz

        now = _tz.now()
        base = max(now, self.expires_at)
        self.expires_at = base + timedelta(days=int(days))
        self.is_blocked = False
        self.block_reason = ""
        self.save(
            update_fields=[
                "expires_at", "is_blocked", "block_reason", "updated_at",
            ]
        )


class LicenseTokenCache(models.Model):
    """Локальный кэш JWT-токена лицензии, выданного vendor-облаком.

    Используется ТОЛЬКО на ресторанном инстансе (`SUPERADMIN_ENABLED=False`).
    На cloud-инстансе эта таблица обычно пустая — там источник правды это
    модель `License`.

    Один ресторанный сервер обслуживает один ресторан → одна строка в БД
    (singleton, id=1).
    """

    SINGLETON_ID = 1

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    token = models.TextField(
        help_text="JWT, полученный от cloud /license/issue_token/",
    )
    claims = models.JSONField(
        default=dict,
        help_text="Декодированный payload JWT — основа для _enforce_license",
    )
    # Дублируем критичные поля для быстрого чтения без JSON parsing
    plan = models.CharField(max_length=24, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_blocked = models.BooleanField(default=False)
    block_reason = models.CharField(max_length=255, blank=True)

    fetched_at = models.DateTimeField(
        auto_now=True,
        help_text="Когда был последний успешный refresh от cloud",
    )

    class Meta:
        db_table = "license_token_cache"
        verbose_name = "Кэш лицензионного токена"
        verbose_name_plural = "Кэш лицензионных токенов"

    def __str__(self) -> str:
        return f"LicenseTokenCache plan={self.plan} expires={self.expires_at}"
