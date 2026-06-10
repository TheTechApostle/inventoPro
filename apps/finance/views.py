"""
Finance app — serializers, views, and URLs.
"""
from decimal import Decimal
from django.utils import timezone
from rest_framework import serializers, viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema
from rest_framework.routers import DefaultRouter
from core.permissions import TenantPermission, CanViewFinance, CanManageFinance
from core.mixins import TenantQuerysetMixin
from .models import ExpenseCategory, Expense, TaxRate, FinancialSummary


# ── Serializers ──────────────────────────────────────────────────────────────

class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        exclude = ["tenant"]
        read_only_fields = ["id", "is_system", "created_at", "updated_at"]


class ExpenseSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    submitted_by_name = serializers.CharField(source="submitted_by.get_full_name", read_only=True)
    approved_by_name = serializers.CharField(source="approved_by.get_full_name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Expense
        exclude = ["tenant"]
        read_only_fields = [
            "id", "total_amount", "status", "approved_by",
            "approved_at", "created_at", "updated_at",
        ]


class TaxRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxRate
        exclude = ["tenant"]
        read_only_fields = ["id", "created_at", "updated_at"]


class FinancialSummarySerializer(serializers.ModelSerializer):
    gross_margin_pct = serializers.SerializerMethodField()
    net_margin_pct = serializers.SerializerMethodField()

    class Meta:
        model = FinancialSummary
        exclude = ["tenant"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_gross_margin_pct(self, obj):
        if obj.total_revenue:
            return round((obj.gross_profit / obj.total_revenue) * 100, 2)
        return 0

    def get_net_margin_pct(self, obj):
        if obj.total_revenue:
            return round((obj.net_profit / obj.total_revenue) * 100, 2)
        return 0


# ── ViewSets ─────────────────────────────────────────────────────────────────

class ExpenseCategoryViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    queryset = ExpenseCategory.objects.all()
    serializer_class = ExpenseCategorySerializer
    permission_classes = [IsAuthenticated, TenantPermission, CanViewFinance]
    search_fields = ["name"]

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class ExpenseViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    queryset = Expense.objects.select_related(
        "category", "submitted_by", "approved_by", "warehouse"
    )
    serializer_class = ExpenseSerializer
    permission_classes = [IsAuthenticated, TenantPermission, CanViewFinance]
    filterset_fields = ["status", "category", "payment_method", "warehouse"]
    search_fields = ["title", "vendor", "reference"]
    ordering_fields = ["expense_date", "amount", "created_at"]
    ordering = ["-expense_date"]

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, submitted_by=self.request.user)

    @extend_schema(tags=["finance"])
    @action(detail=True, methods=["post"],
            permission_classes=[IsAuthenticated, TenantPermission, CanManageFinance])
    def approve(self, request, pk=None):
        expense = self.get_object()
        if expense.status != Expense.Status.SUBMITTED:
            return Response(
                {"success": False, "error": {"message": "Only submitted expenses can be approved."}},
                status=400,
            )
        expense.status = Expense.Status.APPROVED
        expense.approved_by = request.user
        expense.approved_at = timezone.now()
        expense.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
        return Response({"success": True, "message": "Expense approved."})

    @extend_schema(tags=["finance"])
    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        expense = self.get_object()
        if expense.status != Expense.Status.DRAFT:
            return Response({"success": False, "error": {"message": "Only drafts can be submitted."}}, status=400)
        expense.status = Expense.Status.SUBMITTED
        expense.save(update_fields=["status", "updated_at"])
        return Response({"success": True, "message": "Expense submitted for approval."})

    @extend_schema(tags=["finance"])
    @action(detail=False, methods=["get"])
    def summary(self, request):
        """GET /finance/expenses/summary/?date_from=&date_to="""
        from core.utils import parse_date_range
        from django.db.models import Sum, Count
        date_from, date_to = parse_date_range(request)

        qs = self.get_queryset().filter(
            expense_date__gte=date_from.date(),
            expense_date__lte=date_to.date(),
            status__in=["approved", "paid"],
        )
        summary = qs.values("category__name").annotate(
            total=Sum("total_amount"), count=Count("id")
        ).order_by("-total")

        totals = qs.aggregate(
            grand_total=Sum("total_amount"),
            expense_count=Count("id"),
        )

        return Response({
            "success": True,
            "data": {
                "by_category": list(summary),
                "grand_total": totals["grand_total"] or 0,
                "expense_count": totals["expense_count"] or 0,
                "period": {"from": date_from.date(), "to": date_to.date()},
            },
        })


class TaxRateViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    queryset = TaxRate.objects.all()
    serializer_class = TaxRateSerializer
    permission_classes = [IsAuthenticated, TenantPermission, CanManageFinance]
    search_fields = ["name"]

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class ProfitLossView(viewsets.ViewSet):
    """
    P&L report.
    GET /api/v1/finance/pl/
    """
    permission_classes = [IsAuthenticated, TenantPermission, CanViewFinance]

    @extend_schema(tags=["finance"])
    def list(self, request):
        from core.utils import parse_date_range
        from django.db.models import Sum
        from apps.sales.models import SalesOrder, SalesOrderItem
        from apps.purchases.models import PurchaseOrderItem

        date_from, date_to = parse_date_range(request)

        # Revenue
        confirmed_orders = SalesOrder.objects.filter(
            tenant=request.tenant,
            status__in=["confirmed", "delivered"],
            order_date__gte=date_from.date(),
            order_date__lte=date_to.date(),
        )
        revenue = confirmed_orders.aggregate(
            total=Sum("total_amount"), tax=Sum("tax_amount")
        )

        # COGS — sum of (quantity * cost_price) from items
        cogs = SalesOrderItem.objects.filter(
            tenant=request.tenant,
            order__in=confirmed_orders,
        ).aggregate(
            total=Sum(
                __import__("django.db.models", fromlist=["F", "ExpressionWrapper", "DecimalField"]).ExpressionWrapper(
                    __import__("django.db.models", fromlist=["F"]).F("quantity") *
                    __import__("django.db.models", fromlist=["F"]).F("cost_price"),
                    output_field=__import__("django.db.models", fromlist=["DecimalField"]).DecimalField(),
                )
            )
        )

        # Expenses
        expenses = Expense.objects.filter(
            tenant=request.tenant,
            expense_date__gte=date_from.date(),
            expense_date__lte=date_to.date(),
            status__in=["approved", "paid"],
        ).aggregate(total=Sum("total_amount"))

        total_revenue = revenue["total"] or Decimal("0")
        total_cogs = cogs["total"] or Decimal("0")
        total_expenses = expenses["total"] or Decimal("0")
        gross_profit = total_revenue - total_cogs
        net_profit = gross_profit - total_expenses

        return Response({
            "success": True,
            "data": {
                "period": {"from": date_from.date(), "to": date_to.date()},
                "revenue": {
                    "total": total_revenue,
                    "tax": revenue["tax"] or 0,
                    "order_count": confirmed_orders.count(),
                },
                "cogs": total_cogs,
                "gross_profit": gross_profit,
                "gross_margin_pct": round((gross_profit / total_revenue * 100), 2) if total_revenue else 0,
                "expenses": total_expenses,
                "net_profit": net_profit,
                "net_margin_pct": round((net_profit / total_revenue * 100), 2) if total_revenue else 0,
            },
        })


# ── URLs ─────────────────────────────────────────────────────────────────────

router = DefaultRouter()
router.register("categories", ExpenseCategoryViewSet, basename="expense-categories")
router.register("expenses", ExpenseViewSet, basename="expenses")
router.register("tax-rates", TaxRateViewSet, basename="tax-rates")
router.register("pl", ProfitLossView, basename="pl")

urlpatterns = router.urls
