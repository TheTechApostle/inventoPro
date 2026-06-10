"""
DashboardService — aggregated analytics for executive dashboards.
All queries are scoped to a tenant and optimised for speed.
Heavy queries are cached in Redis; cache is busted nightly.
"""
import logging
from decimal import Decimal
from django.db.models import Sum, Count, Avg, F, Q, Max, Min
from django.db.models.functions import TruncDate, TruncMonth, TruncWeek
from django.utils import timezone
from django.core.cache import cache
from datetime import timedelta

logger = logging.getLogger("inventra.analytics")

CACHE_TTL = 300  # 5 minutes


def _cache_key(tenant_slug: str, key: str) -> str:
    return f"analytics:{tenant_slug}:{key}"


class DashboardService:

    @classmethod
    def get_overview(cls, tenant, period_days: int = 30) -> dict:
        """
        Main dashboard overview.
        Returns KPI summary + trends for a given period.
        """
        cache_key = _cache_key(tenant.slug, f"overview:{period_days}")
        cached = cache.get(cache_key)
        if cached:
            return cached

        since = timezone.now() - timedelta(days=period_days)
        prev_since = since - timedelta(days=period_days)  # comparison period

        from apps.sales.models import SalesOrder
        from apps.inventory.models import StockLevel
        from apps.finance.models import Expense
        from apps.purchases.models import PurchaseOrder

        # Current period sales
        current_sales = SalesOrder.objects.filter(
            tenant=tenant,
            status__in=["confirmed", "delivered"],
            created_at__gte=since,
        )
        prev_sales = SalesOrder.objects.filter(
            tenant=tenant,
            status__in=["confirmed", "delivered"],
            created_at__gte=prev_since,
            created_at__lt=since,
        )

        curr_rev = current_sales.aggregate(t=Sum("total_amount"))["t"] or Decimal("0")
        prev_rev = prev_sales.aggregate(t=Sum("total_amount"))["t"] or Decimal("0")
        curr_count = current_sales.count()
        prev_count = prev_sales.count()

        # Expenses
        curr_expenses = Expense.objects.filter(
            tenant=tenant,
            expense_date__gte=since.date(),
            status__in=["approved", "paid"],
        ).aggregate(t=Sum("total_amount"))["t"] or Decimal("0")

        # Inventory
        stock_stats = StockLevel.objects.filter(tenant=tenant, is_active=True).aggregate(
            low_stock=Count("id", filter=Q(quantity__lte=F("product__reorder_point"), quantity__gt=0)),
            out_of_stock=Count("id", filter=Q(quantity__lte=0)),
            total_value=Sum(F("quantity") * F("average_cost")),
        )

        # Outstanding payables
        outstanding_po = PurchaseOrder.objects.filter(
            tenant=tenant,
            status__in=["confirmed", "partial"],
            payment_status__in=["unpaid", "partial"],
        ).aggregate(t=Sum("amount_due"))["t"] or Decimal("0")

        from core.utils import calculate_percentage_change
        result = {
            "period_days": period_days,
            "revenue": {
                "current": curr_rev,
                "previous": prev_rev,
                "change_pct": calculate_percentage_change(float(prev_rev), float(curr_rev)),
            },
            "orders": {
                "current": curr_count,
                "previous": prev_count,
                "change_pct": calculate_percentage_change(prev_count, curr_count),
            },
            "avg_order_value": round(float(curr_rev / curr_count), 2) if curr_count else 0,
            "expenses": curr_expenses,
            "gross_profit": curr_rev - curr_expenses,
            "inventory": {
                "low_stock_count": stock_stats["low_stock"] or 0,
                "out_of_stock_count": stock_stats["out_of_stock"] or 0,
                "total_value": stock_stats["total_value"] or 0,
            },
            "outstanding_payables": outstanding_po,
        }

        cache.set(cache_key, result, CACHE_TTL)
        return result

    @classmethod
    def revenue_trend(cls, tenant, days: int = 30, group_by: str = "day") -> list:
        """
        Daily/weekly/monthly revenue trend.
        group_by: "day" | "week" | "month"
        """
        from apps.sales.models import SalesOrder

        since = timezone.now() - timedelta(days=days)
        trunc_fn = {"day": TruncDate, "week": TruncWeek, "month": TruncMonth}.get(
            group_by, TruncDate
        )

        return list(
            SalesOrder.objects.filter(
                tenant=tenant,
                status__in=["confirmed", "delivered"],
                created_at__gte=since,
            )
            .annotate(period=trunc_fn("created_at"))
            .values("period")
            .annotate(
                revenue=Sum("total_amount"),
                orders=Count("id"),
                avg_value=Avg("total_amount"),
            )
            .order_by("period")
        )

    @classmethod
    def top_products(cls, tenant, days: int = 30, limit: int = 10) -> list:
        """Top selling products by revenue and quantity."""
        from apps.sales.models import SalesOrderItem

        since = timezone.now() - timedelta(days=days)
        return list(
            SalesOrderItem.objects.filter(
                tenant=tenant,
                order__status__in=["confirmed", "delivered"],
                order__created_at__gte=since,
            )
            .values("product__id", "product__name", "product__sku", "product__image")
            .annotate(
                total_qty=Sum("quantity"),
                total_revenue=Sum("line_total"),
                total_profit=Sum(
                    F("line_total") - F("quantity") * F("cost_price")
                ),
                order_count=Count("order", distinct=True),
            )
            .order_by("-total_revenue")[:limit]
        )

    @classmethod
    def top_customers(cls, tenant, days: int = 30, limit: int = 10) -> list:
        """Top customers by spend."""
        from apps.sales.models import SalesOrder

        since = timezone.now() - timedelta(days=days)
        return list(
            SalesOrder.objects.filter(
                tenant=tenant,
                status__in=["confirmed", "delivered"],
                created_at__gte=since,
                customer__isnull=False,
            )
            .values(
                "customer__id", "customer__first_name",
                "customer__last_name", "customer__email", "customer__phone",
            )
            .annotate(
                total_spent=Sum("total_amount"),
                order_count=Count("id"),
                avg_order=Avg("total_amount"),
            )
            .order_by("-total_spent")[:limit]
        )

    @classmethod
    def sales_by_channel(cls, tenant, days: int = 30) -> list:
        """Revenue breakdown by sale channel."""
        from apps.sales.models import SalesOrder

        since = timezone.now() - timedelta(days=days)
        return list(
            SalesOrder.objects.filter(
                tenant=tenant,
                status__in=["confirmed", "delivered"],
                created_at__gte=since,
            )
            .values("sale_channel")
            .annotate(revenue=Sum("total_amount"), orders=Count("id"))
            .order_by("-revenue")
        )

    @classmethod
    def warehouse_comparison(cls, tenant) -> list:
        """Stock value and movement stats per warehouse."""
        from apps.inventory.models import StockLevel, StockMovement
        from apps.warehouses.models import Warehouse

        warehouses = Warehouse.objects.filter(tenant=tenant, is_active=True)
        result = []
        for wh in warehouses:
            stock = StockLevel.objects.filter(tenant=tenant, warehouse=wh).aggregate(
                total_value=Sum(F("quantity") * F("average_cost")),
                product_count=Count("product", distinct=True),
                total_units=Sum("quantity"),
            )
            result.append({
                "warehouse_id": str(wh.id),
                "warehouse_name": wh.name,
                "warehouse_code": wh.code,
                **{k: v or 0 for k, v in stock.items()},
            })
        return result

    @classmethod
    def stock_movement_trend(cls, tenant, days: int = 30) -> list:
        """Daily stock in vs stock out trend."""
        from apps.inventory.models import StockMovement

        since = timezone.now() - timedelta(days=days)
        IN_TYPES = ["purchase", "adjustment_in", "return_customer", "opening", "transfer_in"]
        OUT_TYPES = ["sale", "adjustment_out", "damage", "return_supplier", "transfer_out"]

        return list(
            StockMovement.objects.filter(tenant=tenant, created_at__gte=since)
            .annotate(date=TruncDate("created_at"))
            .values("date")
            .annotate(
                stock_in=Sum("quantity", filter=Q(movement_type__in=IN_TYPES)),
                stock_out=Sum("quantity", filter=Q(movement_type__in=OUT_TYPES)),
                movement_count=Count("id"),
            )
            .order_by("date")
        )
