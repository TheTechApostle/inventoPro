from rest_framework.routers import DefaultRouter
from .views import (
    StockLevelViewSet, StockMovementViewSet,
    StockTransferViewSet, BatchLotViewSet, SerialNumberViewSet,
)

router = DefaultRouter()
router.register("stock", StockLevelViewSet, basename="stock")
router.register("movements", StockMovementViewSet, basename="movements")
router.register("transfers", StockTransferViewSet, basename="transfers")
router.register("batches", BatchLotViewSet, basename="batches")
router.register("serials", SerialNumberViewSet, basename="serials")

urlpatterns = router.urls
