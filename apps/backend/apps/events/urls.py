from django.urls import path

from .views import EventStreamView

urlpatterns = [
    path("", EventStreamView.as_view(), name="sse-events"),
]
