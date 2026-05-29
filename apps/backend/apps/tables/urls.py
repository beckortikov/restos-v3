from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import TableGroupViewSet, TableViewSet, ZoneViewSet

router = DefaultRouter()
router.register("zones", ZoneViewSet, basename="zone")
router.register("groups", TableGroupViewSet, basename="table-group")
router.register("", TableViewSet, basename="table")

urlpatterns = [path("", include(router.urls))]
