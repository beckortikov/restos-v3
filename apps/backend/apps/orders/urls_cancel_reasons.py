"""Отдельный роутер для /api/v1/cancel_reasons/.

Лежит в orders/, чтобы ViewSet оставался рядом со своей моделью,
но монтируется на верхнем уровне URL — иначе бы DefaultRouter в orders/urls.py
конфликтовал с пустым префиксом OrderViewSet.
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import CancelReasonViewSet

router = DefaultRouter()
router.register("", CancelReasonViewSet, basename="cancel-reasons")

urlpatterns = [path("", include(router.urls))]
