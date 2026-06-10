from rest_framework.routers import DefaultRouter
from .views import CustomerViewSet, SalesOrderViewSet, POSSessionViewSet

router = DefaultRouter()
router.register("customers", CustomerViewSet, basename="customers")
router.register("orders", SalesOrderViewSet, basename="sales-orders")
router.register("pos", POSSessionViewSet, basename="pos-sessions")

urlpatterns = router.urls
