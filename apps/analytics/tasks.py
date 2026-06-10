from celery import shared_task
import logging

logger = logging.getLogger("inventra.analytics.tasks")


@shared_task
def generate_daily_reports():
    """Called by Celery Beat — rebuilds FinancialSummary for each active tenant."""
    from apps.tenants.models import Tenant
    from django.utils import timezone

    tenants = Tenant.objects.filter(is_active=True)
    date = timezone.now().date()

    for tenant in tenants:
        try:
            _build_daily_summary(tenant, date)
        except Exception as e:
            logger.error(f"[ANALYTICS] Daily report failed for {tenant.slug}: {e}")

    logger.info(f"[ANALYTICS] Daily reports complete for {tenants.count()} tenants")


@shared_task
def generate_daily_report(tenant_id: str):
    """Generate daily summary for a single tenant."""
    from apps.tenants.models import Tenant
    from django.utils import timezone

    tenant = Tenant.objects.get(id=tenant_id)
    _build_daily_summary(tenant, timezone.now().date())


def _build_daily_summary(tenant, date):
    from apps.finance.models import FinancialSummary
    from apps.sales.models import SalesOrder, SalesOrderItem
    from apps.finance.models import Expense
    from django.db.models import Sum, Count, F

    orders = SalesOrder.objects.filter(
        tenant=tenant,
        status__in=["confirmed", "delivered"],
        order_date=date,
    )
    revenue = orders.aggregate(t=Sum("total_amount"))["t"] or 0
    order_count = orders.count()

    cogs_agg = SalesOrderItem.objects.filter(
        tenant=tenant, order__in=orders
    ).aggregate(
        cogs=Sum(F("quantity") * F("cost_price")),
        qty=Sum("quantity"),
    )
    cogs = cogs_agg["cogs"] or 0
    items_sold = cogs_agg["qty"] or 0

    expenses = Expense.objects.filter(
        tenant=tenant,
        expense_date=date,
        status__in=["approved", "paid"],
    ).aggregate(t=Sum("total_amount"))["t"] or 0

    gross_profit = revenue - cogs
    net_profit = gross_profit - expenses

    FinancialSummary.objects.update_or_create(
        tenant=tenant,
        date=date,
        defaults={
            "total_revenue": revenue,
            "total_cogs": cogs,
            "gross_profit": gross_profit,
            "total_expenses": expenses,
            "net_profit": net_profit,
            "order_count": order_count,
            "items_sold": items_sold,
        },
    )
    logger.info(f"[ANALYTICS] Summary built: {tenant.slug} | {date} | Revenue: {revenue}")
