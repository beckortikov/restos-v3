from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    MeView,
    PinLoginView,
    PinLogoutView,
    RestaurantSettingsView,
    UserAdminViewSet,
    WaiterPinLoginView,
    WaiterTokenObtainPairView,
    WaiterTokenRefreshView,
)

router = DefaultRouter()
router.register(r"users", UserAdminViewSet, basename="users")

urlpatterns = [
    path("auth/login/", WaiterTokenObtainPairView.as_view(), name="auth-login"),
    path("auth/refresh/", WaiterTokenRefreshView.as_view(), name="auth-refresh"),
    path("auth/pin/", PinLoginView.as_view(), name="auth-pin"),
    path("auth/pin/logout/", PinLogoutView.as_view(), name="auth-pin-logout"),
    path("auth/waiter/pin/", WaiterPinLoginView.as_view(), name="auth-waiter-pin"),
    path("auth/me/", MeView.as_view(), name="auth-me"),
    path("restaurant/", RestaurantSettingsView.as_view(), name="restaurant-settings"),
    path("", include(router.urls)),
]
