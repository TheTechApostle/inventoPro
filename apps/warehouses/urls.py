from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import WarehouseViewSet, BranchViewSet

router = DefaultRouter()
router.register("warehouses", WarehouseViewSet, basename="warehouses")
router.register("branches", BranchViewSet, basename="branches")

urlpatterns = router.urls
