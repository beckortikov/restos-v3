from django.urls import path

from . import views

urlpatterns = [
    path("auth/login/", views.SuperAdminLoginView.as_view(), name="sa-login"),
    path("restaurants/", views.list_restaurants, name="sa-restaurants-list"),
    path("restaurants/create/", views.create_restaurant, name="sa-restaurant-create"),
    path("restaurants/<int:pk>/", views.restaurant_detail, name="sa-restaurant-detail"),
    path("restaurants/<int:pk>/license/", views.license_detail, name="sa-license-detail"),
    path("restaurants/<int:pk>/license/extend/", views.license_extend, name="sa-license-extend"),
    path("restaurants/<int:pk>/license/change_plan/", views.license_change_plan, name="sa-license-change-plan"),
    path("restaurants/<int:pk>/license/block/", views.license_block, name="sa-license-block"),
    path("restaurants/<int:pk>/license/unblock/", views.license_unblock, name="sa-license-unblock"),
    path("stats/", views.stats, name="sa-stats"),
]
