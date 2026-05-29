from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ShiftViewSet

router = DefaultRouter()
router.register("", ShiftViewSet, basename="shift")

urlpatterns = [path("", include(router.urls))]
