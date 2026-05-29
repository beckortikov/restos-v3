from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AuditEntryViewSet

router = DefaultRouter()
router.register("", AuditEntryViewSet, basename="audit")

urlpatterns = [path("", include(router.urls))]
