from django.urls import path
from .views import TenantRegisterView, TenantDetailView, TenantSettingsView

urlpatterns = [
    path("register/", TenantRegisterView.as_view(), name="tenant-register"),
    path("me/", TenantDetailView.as_view(), name="tenant-detail"),
    path("settings/", TenantSettingsView.as_view(), name="tenant-settings"),
]
