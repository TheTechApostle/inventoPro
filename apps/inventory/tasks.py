"""
Inventory async tasks.
"""
import logging
from celery import shared_task

logger = logging.getLogger("inventra.inventory.tasks")


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_reorder_alert(self, product_id: str, tenant_id: str):
    """
    Fires when a product hits its reorder point.
    Creates an in-app notification + sends email to managers.
    """
    try:
        from apps.products.models import Product
        from apps.tenants.models import Tenant
        from apps.inventory.models import StockLevel
        from apps.notifications.services import NotificationService

        product = Product.objects.unscoped().get(id=product_id)
        tenant = Tenant.objects.get(id=tenant_id)

        # Get total stock across all warehouses
        total_stock = (
            StockLevel.objects.unscoped()
            .filter(product=product, tenant=tenant)
            .aggregate(total=__import__("django.db.models", fromlist=["Sum"]).Sum("quantity"))
        )["total"] or 0

        NotificationService.create(
            tenant=tenant,
            title=f"Low Stock Alert: {product.name}",
            body=(
                f"{product.name} (SKU: {product.sku}) has dropped to "
                f"{total_stock} units, below the reorder point of {product.reorder_point}."
            ),
            notification_type="low_stock",
            reference_id=str(product.id),
            reference_type="product",
        )
        logger.info(f"[TASK] Reorder alert sent: {product.sku} | Tenant: {tenant.slug}")

    except Exception as exc:
        logger.error(f"[TASK] Reorder alert failed: {exc}")
        raise self.retry(exc=exc)


@shared_task
def check_all_low_stock():
    """
    Daily sweep — find all products at or below reorder point
    and send consolidated alerts per tenant.
    Called by Celery Beat.
    """
    from django.db.models import F, Sum
    from apps.inventory.models import StockLevel
    from apps.notifications.services import NotificationService
    from apps.tenants.models import Tenant

    tenants = Tenant.objects.filter(is_active=True)
    for tenant in tenants:
        low_stock_items = (
            StockLevel.objects.unscoped()
            .filter(
                tenant=tenant,
                quantity__lte=F("product__reorder_point"),
                quantity__gt=0,
                product__track_inventory=True,
                is_active=True,
            )
            .select_related("product", "warehouse")
        )

        if low_stock_items.exists():
            names = ", ".join(
                set(item.product.name for item in low_stock_items[:5])
            )
            suffix = f" and {low_stock_items.count() - 5} more" if low_stock_items.count() > 5 else ""
            NotificationService.create(
                tenant=tenant,
                title=f"{low_stock_items.count()} products running low",
                body=f"Low stock: {names}{suffix}",
                notification_type="low_stock_digest",
            )

    logger.info("[TASK] check_all_low_stock complete")


@shared_task
def check_expiring_batches():
    """
    Daily sweep — notify about batches expiring within 30 days.
    """
    from django.utils import timezone
    from apps.inventory.models import BatchLot
    from apps.notifications.services import NotificationService
    from apps.tenants.models import Tenant
    from datetime import timedelta

    cutoff = timezone.now().date() + timedelta(days=30)
    tenants = Tenant.objects.filter(is_active=True)

    for tenant in tenants:
        expiring = BatchLot.objects.unscoped().filter(
            tenant=tenant,
            expiry_date__lte=cutoff,
            expiry_date__gte=timezone.now().date(),
            quantity__gt=0,
        ).count()

        if expiring > 0:
            NotificationService.create(
                tenant=tenant,
                title=f"{expiring} batch(es) expiring within 30 days",
                body="Review your batch inventory to take action on near-expiry stock.",
                notification_type="batch_expiry",
            )
