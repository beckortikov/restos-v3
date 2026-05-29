"""Permission class для super-admin endpoints."""
from rest_framework.permissions import BasePermission


class IsSuperAdmin(BasePermission):
    """Доступ только для is_superuser=True + is_active=True."""

    message = "Требуется super-admin доступ"

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and getattr(user, "is_superuser", False)
            and getattr(user, "is_active", False)
        )
