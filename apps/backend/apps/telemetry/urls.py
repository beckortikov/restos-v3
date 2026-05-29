from django.urls import path

from . import views

urlpatterns = [
    path("push/", views.TelemetryPushView.as_view(), name="telemetry-push"),
    path("catalog/", views.CatalogPushView.as_view(), name="telemetry-catalog"),
]
