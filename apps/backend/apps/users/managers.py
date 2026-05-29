from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import BaseUserManager


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, username: str, password: str | None, **extra_fields):
        if not username:
            raise ValueError("username обязателен")
        user = self.model(username=username, **extra_fields)
        user.password = make_password(password) if password else make_password(None)
        user.save(using=self._db)
        return user

    def create_user(self, username: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(username, password, **extra_fields)

    def create_superuser(self, username: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", "cashier")
        extra_fields.setdefault("full_name", username)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True")
        if "restaurant" not in extra_fields and "restaurant_id" not in extra_fields:
            from .models import Restaurant

            restaurant, _ = Restaurant.objects.get_or_create(
                id=1, defaults={"name": "Default", "currency": "TJS"}
            )
            extra_fields["restaurant"] = restaurant
        return self._create_user(username, password, **extra_fields)
