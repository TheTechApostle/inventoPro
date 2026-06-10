from rest_framework.routers import DefaultRouter
from .views import AnalyticsViewSet

router = DefaultRouter()
router.register("", AnalyticsViewSet, basename="analytics")

urlpatterns = router.urls
