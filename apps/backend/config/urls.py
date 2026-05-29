from django.conf import settings
from django.contrib import admin
from django.urls import include, path

api_v1 = [
    path("", include("apps.users.urls")),
    path("tables/", include("apps.tables.urls")),
    path("menu/", include("apps.menu.urls")),
    path("orders/", include("apps.orders.urls")),
    path("cancel_reasons/", include("apps.orders.urls_cancel_reasons")),
    path("payment_providers/", include("apps.orders.urls_payments")),
    path("discounts/", include("apps.orders.urls_discounts")),
    path("printing/", include("apps.printing.urls")),
    path("events/", include("apps.events.urls")),
    path("shifts/", include("apps.shifts.urls")),
    path("audit/", include("apps.audit.urls")),
    path("reservations/", include("apps.reservations.urls")),
    path("kitchen/", include("apps.kitchen.urls")),
    path("", include("apps.licensing.urls")),  # /license/status/ + /heartbeat/
    path("analytics/", include("apps.analytics.urls")),
    path("inventory/", include("apps.inventory.urls")),
    path("payroll/", include("apps.payroll.urls")),
]

# Super-Admin endpoints монтируются ТОЛЬКО когда settings.SUPERADMIN_ENABLED=True.
# В развёртывании на сервере ресторана это всегда False — SA-страница и API
# возвращают 404 (не существует в URLconf). См. config/settings/base.py.
if getattr(settings, "SUPERADMIN_ENABLED", False):
    api_v1.append(path("superadmin/", include("apps.superadmin.urls")))
    # Telemetry push принимаем только на cloud
    api_v1.append(path("telemetry/", include("apps.telemetry.urls")))

urlpatterns = [
    path("api/v1/", include(api_v1)),
]

if getattr(settings, "DJANGO_ADMIN_ENABLED", True):
    urlpatterns.insert(0, path("admin/", admin.site.urls))

# SA web UI убран — управление через Django admin (`/admin/` оформлен
# через django-jazzmin). JSON API `/api/v1/superadmin/` (выше) оставлен
# для автоматизации и curl/CI/мониторинга.
