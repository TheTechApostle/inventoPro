from rest_framework.routers import DefaultRouter
from .views import CategoryViewSet, UnitViewSet, ProductViewSet

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="categories")
router.register("units", UnitViewSet, basename="units")
router.register("", ProductViewSet, basename="products")

urlpatterns = router.urls
