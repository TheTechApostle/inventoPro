from rest_framework.routers import DefaultRouter
from .views import (
    ExpenseCategoryViewSet, ExpenseViewSet,
    TaxRateViewSet, ProfitLossView,
)

router = DefaultRouter()
router.register("categories", ExpenseCategoryViewSet, basename="expense-categories")
router.register("expenses", ExpenseViewSet, basename="expenses")
router.register("tax-rates", TaxRateViewSet, basename="tax-rates")
router.register("pl", ProfitLossView, basename="pl")

urlpatterns = router.urls
