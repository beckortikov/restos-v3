from django.urls import path

from . import views

urlpatterns = [
    path("abc-menu/", views.abc_menu_report, name="analytics-abc-menu"),
    path("abc-snapshots/", views.abc_snapshots, name="analytics-abc-snapshots"),
    path(
        "abc-snapshots/<int:snapshot_id>/",
        views.abc_snapshot_detail, name="analytics-abc-snapshot-detail",
    ),
    path("peak-hours/", views.peak_hours_report, name="analytics-peak-hours"),
    path("food-cost/", views.food_cost_report, name="analytics-food-cost"),
    path("waiters/", views.waiter_analytics_report, name="analytics-waiters"),
]
