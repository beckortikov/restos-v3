from django.urls import path

from .views import (
    HeartbeatView,
    IssueLicenseTokenView,
    LicenseActivateView,
    LicenseStatusView,
)

urlpatterns = [
    path("license/status/", LicenseStatusView.as_view(), name="license-status"),
    path("heartbeat/", HeartbeatView.as_view(), name="heartbeat"),
    # SA-7 — активация POS на конкретной машине (без user-auth, HWID-binding)
    path("license/activate/", LicenseActivateView.as_view(), name="license-activate"),
    # Cloud-only: возвращает 404 на restaurant-инстансе через runtime-check
    # в самой view (флаг SUPERADMIN_ENABLED).
    path("license/issue_token/", IssueLicenseTokenView.as_view(), name="license-issue-token"),
]
