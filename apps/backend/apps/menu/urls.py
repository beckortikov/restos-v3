from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    CategoryViewSet,
    MenuItemNoteViewSet,
    MenuItemViewSet,
    ModifierGroupViewSet,
)

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="menu-category")
router.register("items", MenuItemViewSet, basename="menu-item")
router.register("notes", MenuItemNoteViewSet, basename="menu-note")
router.register(
    "modifier-groups", ModifierGroupViewSet, basename="menu-modifier-group",
)

urlpatterns = [path("", include(router.urls))]
