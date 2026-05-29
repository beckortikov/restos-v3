from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import PrinterViewSet, PrintJobViewSet, PrintStationViewSet

router = DefaultRouter()
router.register("printers", PrinterViewSet, basename="printer")
router.register("jobs", PrintJobViewSet, basename="print-job")
router.register("stations", PrintStationViewSet, basename="print-station")

urlpatterns = [path("", include(router.urls))]
