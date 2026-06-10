"""
StockService — the single authoritative engine for all stock mutations.

Rules:
- ALL stock changes MUST go through this service.
- Never update StockLevel directly from views, signals, or tasks.
- Every mutation produces an immutable StockMovement record.
- select_for_update() prevents race conditions on concurrent requests.
- Raises InsufficientStockException on under-stock (unless tenant allows negative).
"""
import logging
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from core.exceptions import InsufficientStockException, InvalidStockOperationException
from apps.inventory.models import StockLevel, StockMovement

logger = logging.getLogger("inventra.inventory.stock")


class StockService:

    @classmethod
    @transaction.atomic
    def adjust_stock(
        cls,
        *,
        tenant,
        product,
        warehouse,
        quantity_delta: Decimal,
        movement_type: str,
        performed_by,
        variant=None,
        unit_cost: Decimal = Decimal("0"),
        reference_type: str = "",
        reference_id=None,
        reference_number: str = "",
        notes: str = "",
        batch_number: str = "",
        serial_number: str = "",
        expiry_date=None,
    ) -> StockMovement:
        """
        Core method. Adjusts stock level and writes a movement record.

        Args:
            quantity_delta: Positive = stock in, Negative = stock out.
        Returns:
            The created StockMovement record.
        Raises:
            InsufficientStockException: If quantity_after would be negative
                and tenant.allow_negative_stock is False.
        """
        if quantity_delta == 0:
            raise InvalidStockOperationException("quantity_delta cannot be zero.")

        # Lock row — prevents race conditions under concurrency
        stock_level, created = StockLevel.objects.select_for_update().get_or_create(
            tenant=tenant,
            product=product,
            variant=variant,
            warehouse=warehouse,
            defaults={
                "quantity": Decimal("0"),
                "reserved_quantity": Decimal("0"),
                "average_cost": unit_cost or Decimal("0"),
            },
        )

        quantity_before = stock_level.quantity
        quantity_after = quantity_before + quantity_delta

        # Guard against negative stock unless tenant explicitly allows it
        allow_negative = cls._tenant_allows_negative(tenant)
        if quantity_after < 0 and not allow_negative:
            raise InsufficientStockException(
                f"Insufficient stock for '{product.name}'.",
                detail={
                    "product": product.sku,
                    "warehouse": warehouse.code,
                    "available": float(stock_level.available_quantity),
                    "requested": float(abs(quantity_delta)),
                },
            )

        # Update running average cost on stock-in
        if quantity_delta > 0 and unit_cost > 0:
            stock_level.average_cost = cls._calculate_average_cost(
                current_qty=quantity_before,
                current_avg_cost=stock_level.average_cost,
                incoming_qty=quantity_delta,
                incoming_cost=unit_cost,
            )

        # Apply delta
        stock_level.quantity = quantity_after
        stock_level.save(update_fields=["quantity", "average_cost", "updated_at"])

        # Write immutable ledger record
        movement = StockMovement.objects.create(
            tenant=tenant,
            product=product,
            variant=variant,
            warehouse=warehouse,
            movement_type=movement_type,
            quantity=quantity_delta,
            quantity_before=quantity_before,
            quantity_after=quantity_after,
            unit_cost=unit_cost,
            total_cost=abs(quantity_delta) * unit_cost,
            reference_type=reference_type,
            reference_id=reference_id,
            reference_number=reference_number,
            notes=notes,
            performed_by=performed_by,
            batch_number=batch_number,
            serial_number=serial_number,
            expiry_date=expiry_date,
        )

        # Trigger reorder alert if needed (async — non-blocking)
        if quantity_after <= product.reorder_point and product.track_inventory:
            cls._trigger_reorder_alert(product, tenant)

        logger.info(
            "[STOCK] %s | SKU: %s | Warehouse: %s | Δ%s → %s | Tenant: %s",
            movement_type, product.sku, warehouse.code,
            quantity_delta, quantity_after, tenant.slug,
        )

        return movement

    @classmethod
    @transaction.atomic
    def transfer_stock(
        cls,
        *,
        tenant,
        product,
        from_warehouse,
        to_warehouse,
        quantity: Decimal,
        performed_by,
        variant=None,
        notes: str = "",
        reference_id=None,
        reference_number: str = "",
    ) -> tuple:
        """
        Atomically move stock from one warehouse to another.
        Both movements happen or neither does.
        Returns (out_movement, in_movement)
        """
        if quantity <= 0:
            raise InvalidStockOperationException("Transfer quantity must be positive.")
        if from_warehouse == to_warehouse:
            raise InvalidStockOperationException("Source and destination warehouse must differ.")

        out_movement = cls.adjust_stock(
            tenant=tenant,
            product=product,
            variant=variant,
            warehouse=from_warehouse,
            quantity_delta=-quantity,
            movement_type=StockMovement.MovementType.TRANSFER_OUT,
            performed_by=performed_by,
            reference_id=reference_id,
            reference_number=reference_number,
            notes=notes or f"Transfer out → {to_warehouse.name}",
        )
        in_movement = cls.adjust_stock(
            tenant=tenant,
            product=product,
            variant=variant,
            warehouse=to_warehouse,
            quantity_delta=quantity,
            movement_type=StockMovement.MovementType.TRANSFER_IN,
            performed_by=performed_by,
            unit_cost=out_movement.unit_cost,
            reference_id=reference_id,
            reference_number=reference_number,
            notes=notes or f"Transfer in ← {from_warehouse.name}",
        )
        return out_movement, in_movement

    @classmethod
    @transaction.atomic
    def process_purchase_receipt(
        cls,
        *,
        tenant,
        warehouse,
        performed_by,
        items: list[dict],  # [{"product": p, "qty": 10, "cost": 500.0, ...}]
        reference_id=None,
        reference_number: str = "",
    ) -> list[StockMovement]:
        """
        Receive goods from a purchase order.
        items: list of dicts with keys: product, quantity, unit_cost,
               variant (optional), batch_number, serial_number, expiry_date.
        """
        movements = []
        for item in items:
            movement = cls.adjust_stock(
                tenant=tenant,
                product=item["product"],
                variant=item.get("variant"),
                warehouse=warehouse,
                quantity_delta=Decimal(str(item["quantity"])),
                movement_type=StockMovement.MovementType.PURCHASE,
                performed_by=performed_by,
                unit_cost=Decimal(str(item.get("unit_cost", 0))),
                reference_id=reference_id,
                reference_number=reference_number,
                batch_number=item.get("batch_number", ""),
                serial_number=item.get("serial_number", ""),
                expiry_date=item.get("expiry_date"),
            )
            movements.append(movement)
        return movements

    @classmethod
    @transaction.atomic
    def process_sale(
        cls,
        *,
        tenant,
        warehouse,
        performed_by,
        items: list[dict],
        reference_id=None,
        reference_number: str = "",
    ) -> list[StockMovement]:
        """Deduct stock for a confirmed sale order."""
        movements = []
        for item in items:
            movement = cls.adjust_stock(
                tenant=tenant,
                product=item["product"],
                variant=item.get("variant"),
                warehouse=warehouse,
                quantity_delta=-Decimal(str(item["quantity"])),
                movement_type=StockMovement.MovementType.SALE,
                performed_by=performed_by,
                unit_cost=item.get("unit_cost", Decimal("0")),
                reference_id=reference_id,
                reference_number=reference_number,
            )
            movements.append(movement)
        return movements

    @classmethod
    def reserve_stock(cls, *, tenant, product, warehouse, quantity: Decimal, variant=None):
        """
        Reserve stock for a pending order (prevents overselling).
        Does NOT deduct from quantity — increments reserved_quantity.
        """
        with transaction.atomic():
            stock_level = StockLevel.objects.select_for_update().filter(
                tenant=tenant, product=product, variant=variant, warehouse=warehouse
            ).first()

            if not stock_level or stock_level.available_quantity < quantity:
                raise InsufficientStockException(
                    "Not enough available stock to reserve.",
                    detail={
                        "product": product.sku,
                        "available": float(stock_level.available_quantity) if stock_level else 0,
                        "requested": float(quantity),
                    },
                )
            stock_level.reserved_quantity += quantity
            stock_level.save(update_fields=["reserved_quantity", "updated_at"])

    @classmethod
    def release_reservation(cls, *, tenant, product, warehouse, quantity: Decimal, variant=None):
        """Release a stock reservation (e.g. order cancelled)."""
        with transaction.atomic():
            stock_level = StockLevel.objects.select_for_update().filter(
                tenant=tenant, product=product, variant=variant, warehouse=warehouse
            ).first()
            if stock_level:
                stock_level.reserved_quantity = max(
                    stock_level.reserved_quantity - quantity, Decimal("0")
                )
                stock_level.save(update_fields=["reserved_quantity", "updated_at"])

    @staticmethod
    def _calculate_average_cost(
        current_qty: Decimal,
        current_avg_cost: Decimal,
        incoming_qty: Decimal,
        incoming_cost: Decimal,
    ) -> Decimal:
        """Weighted average cost calculation."""
        total_qty = current_qty + incoming_qty
        if total_qty == 0:
            return incoming_cost
        total_value = (current_qty * current_avg_cost) + (incoming_qty * incoming_cost)
        return (total_value / total_qty).quantize(Decimal("0.0001"))

    @staticmethod
    def _tenant_allows_negative(tenant) -> bool:
        """Check tenant setting for negative stock allowance."""
        try:
            return tenant.settings.allow_negative_stock
        except Exception:
            return False

    @staticmethod
    def _trigger_reorder_alert(product, tenant):
        """Fire async reorder alert. Non-blocking."""
        try:
            from apps.inventory.tasks import send_reorder_alert
            send_reorder_alert.delay(str(product.id), str(tenant.id))
        except Exception as e:
            logger.warning(f"Could not queue reorder alert: {e}")
