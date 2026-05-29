from rest_framework.routers import DefaultRouter

from .views import PayrollPeriodViewSet, TimeEntryViewSet

router = DefaultRouter()
router.register(r"time", TimeEntryViewSet, basename="payroll-time")
router.register(r"periods", PayrollPeriodViewSet, basename="payroll-periods")

urlpatterns = router.urls
