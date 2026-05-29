"""Отдельный роутер для /api/v1/payment_providers/.

Лежит в orders/, но монтируется на верхний уровень URL — иначе DefaultRouter
в orders/urls.py с пустым префиксом OrderViewSet перехватит /payment_providers/.
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import PaymentProviderViewSet

router = DefaultRouter()
router.register("", PaymentProviderViewSet, basename="payment-providers")

urlpatterns = [path("", include(router.urls))]
