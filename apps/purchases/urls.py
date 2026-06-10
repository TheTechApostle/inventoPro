from rest_framework.routers import DefaultRouter
from .views import SupplierViewSet, PurchaseOrderViewSet

router = DefaultRouter()
router.register("suppliers", SupplierViewSet, basename="suppliers")
router.register("orders", PurchaseOrderViewSet, basename="purchase-orders")

urlpatterns = router.urls
