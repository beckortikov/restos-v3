"""Команда создания/обновления super-admin пользователя.

Usage:
    python manage.py create_superadmin --username vendor --password ******
    python manage.py create_superadmin --username vendor --password ****** --full-name "Vendor Admin"

Создаёт User c is_superuser=True, is_staff=True, restaurant=None, role=manager.
Если пользователь с username уже существует — обновляет пароль и поднимает is_superuser.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.users.models import User, UserRole


class Command(BaseCommand):
    help = "Создать или обновить super-admin пользователя (без ресторана)."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--password", required=True)
        parser.add_argument("--full-name", default="")

    def handle(self, *args, **opts):
        username = (opts["username"] or "").strip()
        password = opts["password"]
        full_name = (opts["full_name"] or "").strip() or username

        if not username:
            raise CommandError("--username обязателен")
        if not password or len(password) < 6:
            raise CommandError("--password должен быть >= 6 символов")

        existing = User.objects.filter(username=username).first()
        if existing is not None:
            existing.set_password(password)
            existing.is_superuser = True
            existing.is_staff = True
            existing.is_active = True
            existing.restaurant = None
            if full_name:
                existing.full_name = full_name
            # Роль формально нужна — берём manager, но фактически SA проверяется
            # через is_superuser, не через role.
            if not existing.role:
                existing.role = UserRole.MANAGER
            existing.save()
            self.stdout.write(self.style.SUCCESS(
                f"Обновлён существующий пользователь {username!r} → super-admin."
            ))
            return

        user = User.objects.create_user(
            username=username,
            password=password,
            full_name=full_name,
            role=UserRole.MANAGER,  # формально, фактически SA через is_superuser
            restaurant=None,
            is_active=True,
        )
        user.is_superuser = True
        user.is_staff = True
        user.save(update_fields=["is_superuser", "is_staff"])
        self.stdout.write(self.style.SUCCESS(
            f"Создан super-admin {username!r} (id={user.id})."
        ))
