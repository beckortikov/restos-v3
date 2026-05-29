"""Сгенерировать api_key для ресторана и вывести его в stdout.

Запускается на vendor cloud:
    python manage.py generate_restaurant_api_key --restaurant-id 5

Возвращает 64-символьный hex-ключ. ЗАПИШИ его в env-конфиг
ресторанного сервера (`RESTAURANT_API_KEY=...`) — больше его никто не
увидит, в БД хранится только сам ключ (как пароль — без хеширования
пока, но в БД доступ есть только у нас).

При повторном вызове перегенерирует — старый ключ инвалидируется.
"""
import secrets

from django.core.management.base import BaseCommand, CommandError

from apps.users.models import Restaurant


class Command(BaseCommand):
    help = "Генерирует/ротейтит api_key ресторана для machine-to-machine auth."

    def add_arguments(self, parser):
        parser.add_argument(
            "--restaurant-id", type=int, required=True,
            help="ID ресторана в облачной БД",
        )

    def handle(self, *args, **opts):
        rid = opts["restaurant_id"]
        try:
            r = Restaurant.objects.get(id=rid)
        except Restaurant.DoesNotExist as exc:
            raise CommandError(f"Ресторан id={rid} не найден") from exc

        new_key = secrets.token_hex(32)  # 64 hex символа
        old_key = r.api_key
        r.api_key = new_key
        r.save(update_fields=["api_key"])

        self.stdout.write(self.style.SUCCESS(
            f"Сгенерирован новый api_key для «{r.name}» (id={r.id})."
        ))
        if old_key:
            self.stdout.write(self.style.WARNING(
                "  ВНИМАНИЕ: предыдущий ключ инвалидирован."
            ))
        self.stdout.write("")
        self.stdout.write(self.style.WARNING(
            "Запиши это в env-конфиг ресторанного сервера:"
        ))
        self.stdout.write("")
        self.stdout.write(f"  RESTAURANT_API_KEY={new_key}")
        self.stdout.write("")
        self.stdout.write(self.style.WARNING(
            "После этого ключ больше нигде не отображается."
        ))
