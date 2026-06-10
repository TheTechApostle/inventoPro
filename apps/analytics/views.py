"""
Analytics views — dashboard, KPIs, trends, reports.
"""
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema
from rest_framework.routers import DefaultRouter
from core.permissions import TenantPermission, CanViewAnalytics
from .services import DashboardService


class AnalyticsViewSet(viewsets.ViewSet):
    """
    All analytics endpoints under /api/v1/analytics/
    """
    permission_classes = [IsAuthenticated, TenantPermission, CanViewAnalytics]

    @extend_schema(tags=["analytics"])
    @action(detail=False, methods=["get"])
    def overview(self, request):
        """
        GET /analytics/overview/?days=30
        Main KPI dashboard summary.
        """
        days = int(request.query_params.get("days", 30))
        data = DashboardService.get_overview(tenant=request.tenant, period_days=days)
        return Response({"success": True, "data": data})

    @extend_schema(tags=["analytics"])
    @action(detail=False, methods=["get"])
    def revenue_trend(self, request):
        """
        GET /analytics/revenue_trend/?days=30&group_by=day
        group_by options: day | week | month
        """
        days = int(request.query_params.get("days", 30))
        group_by = request.query_params.get("group_by", "day")
        data = DashboardService.revenue_trend(
            tenant=request.tenant, days=days, group_by=group_by
        )
        return Response({"success": True, "data": data})

    @extend_schema(tags=["analytics"])
    @action(detail=False, methods=["get"])
    def top_products(self, request):
        """
        GET /analytics/top_products/?days=30&limit=10
        """
        days = int(request.query_params.get("days", 30))
        limit = int(request.query_params.get("limit", 10))
        data = DashboardService.top_products(tenant=request.tenant, days=days, limit=limit)
        return Response({"success": True, "data": data})

    @extend_schema(tags=["analytics"])
    @action(detail=False, methods=["get"])
    def top_customers(self, request):
        """GET /analytics/top_customers/?days=30&limit=10"""
        days = int(request.query_params.get("days", 30))
        limit = int(request.query_params.get("limit", 10))
        data = DashboardService.top_customers(tenant=request.tenant, days=days, limit=limit)
        return Response({"success": True, "data": data})

    @extend_schema(tags=["analytics"])
    @action(detail=False, methods=["get"])
    def sales_by_channel(self, request):
        """GET /analytics/sales_by_channel/?days=30"""
        days = int(request.query_params.get("days", 30))
        data = DashboardService.sales_by_channel(tenant=request.tenant, days=days)
        return Response({"success": True, "data": data})

    @extend_schema(tags=["analytics"])
    @action(detail=False, methods=["get"])
    def warehouse_comparison(self, request):
        """GET /analytics/warehouse_comparison/"""
        data = DashboardService.warehouse_comparison(tenant=request.tenant)
        return Response({"success": True, "data": data})

    @extend_schema(tags=["analytics"])
    @action(detail=False, methods=["get"])
    def stock_movement_trend(self, request):
        """GET /analytics/stock_movement_trend/?days=30"""
        days = int(request.query_params.get("days", 30))
        data = DashboardService.stock_movement_trend(tenant=request.tenant, days=days)
        return Response({"success": True, "data": data})

    @extend_schema(tags=["analytics"])
    @action(detail=False, methods=["get"])
    def inventory_aging(self, request):
        """
        GET /analytics/inventory_aging/
        Products grouped by how long they've been in stock with no movement.
        """
        from django.utils import timezone
        from datetime import timedelta
        from apps.inventory.models import StockLevel, StockMovement
        from django.db.models import Max, OuterRef, Subquery

        tenant = request.tenant
        now = timezone.now()

        # Last movement date per product
        last_movement = (
            StockMovement.objects.filter(
                tenant=tenant, product=OuterRef("product")
            )
            .order_by("-created_at")
            .values("created_at")[:1]
        )

        stock = (
            StockLevel.objects.filter(tenant=tenant, quantity__gt=0)
            .annotate(last_moved=Subquery(last_movement))
            .select_related("product", "warehouse")
        )

        buckets = {"0-30": [], "31-60": [], "61-90": [], "90+": []}
        for item in stock:
            if not item.last_moved:
                buckets["90+"].append(item.product.sku)
                continue
            age = (now - item.last_moved).days
            if age <= 30:
                buckets["0-30"].append(item.product.sku)
            elif age <= 60:
                buckets["31-60"].append(item.product.sku)
            elif age <= 90:
                buckets["61-90"].append(item.product.sku)
            else:
                buckets["90+"].append(item.product.sku)

        return Response({
            "success": True,
            "data": {
                bucket: {"count": len(skus), "products": skus[:20]}
                for bucket, skus in buckets.items()
            },
        })


class AnalyticsDailyTasksViewSet(viewsets.ViewSet):
    """Internal use — trigger report generation."""
    permission_classes = [IsAuthenticated, TenantPermission]

    @action(detail=False, methods=["post"])
    def generate_daily(self, request):
        from apps.analytics.tasks import generate_daily_report
        generate_daily_report.delay(str(request.tenant.id))
        return Response({"success": True, "message": "Report generation queued."})


router = DefaultRouter()
router.register("", AnalyticsViewSet, basename="analytics")

urlpatterns = router.urls
