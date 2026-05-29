"""Отдельный роутер для /api/v1/discounts/."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import DiscountViewSet

router = DefaultRouter()
router.register("", DiscountViewSet, basename="discounts")

urlpatterns = [path("", include(router.urls))]
