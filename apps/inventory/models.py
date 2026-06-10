"""
Inventory engine models.
StockLevel = current quantity per product per warehouse.
StockMovement = immutable ledger of every quantity change.
"""
from django.db import models
from django.utils import timezone
from core.models import TenantAwareModel


class StockLevel(TenantAwareModel):
    """
    Current stock level per product (+ variant) per warehouse.
    This is the single source of truth for "how much do we have right now".
    NEVER update this directly — always use StockService.adjust_stock().
    """
    product = models.ForeignKey(
        "products.Product", on_delete=models.CASCADE, related_name="stock_levels"
    )
    variant = models.ForeignKey(
        "products.ProductVariant", on_delete=models.CASCADE,
        null=True, blank=True, related_name="stock_levels"
    )
    warehouse = models.ForeignKey(
        "warehouses.Warehouse", on_delete=models.CASCADE, related_name="stock_levels"
    )
    quantity = models.DecimalField(max_digits=15, decimal_places=3, default=0)
    reserved_quantity = models.DecimalField(
        max_digits=15, decimal_places=3, default=0,
        help_text="Stock committed to undelivered orders"
    )
    # Running average cost (updated on each purchase)
    average_cost = models.DecimalField(max_digits=15, decimal_places=4, default=0)

    class Meta:
        db_table = "stock_levels"
        unique_together = [("tenant", "product", "variant", "warehouse")]
        indexes = [
            models.Index(fields=["tenant", "product", "warehouse"]),
            models.Index(fields=["tenant", "warehouse"]),
        ]

    def __str__(self):
        variant_str = f" ({self.variant.name})" if self.variant else ""
        return f"{self.product.name}{variant_str} @ {self.warehouse.name}: {self.quantity}"

    @property
    def available_quantity(self):
        return max(self.quantity - self.reserved_quantity, 0)

    @property
    def is_low_stock(self) -> bool:
        return self.quantity <= self.product.reorder_point

    @property
    def is_out_of_stock(self) -> bool:
        return self.quantity <= 0

    @property
    def stock_value(self):
        return self.quantity * self.average_cost


class StockMovement(TenantAwareModel):
    """
    Immutable ledger record for every stock mutation.
    Think of it as a double-entry bookkeeping line for inventory.
    Every +/- quantity MUST produce one StockMovement record.
    DO NOT update records here — only insert new ones.
    """

    class MovementType(models.TextChoices):
        OPENING = "opening", "Opening Stock"
        PURCHASE = "purchase", "Purchase Receipt"
        SALE = "sale", "Sale"
        TRANSFER_OUT = "transfer_out", "Transfer Out"
        TRANSFER_IN = "transfer_in", "Transfer In"
        ADJUSTMENT_IN = "adjustment_in", "Adjustment (Increase)"
        ADJUSTMENT_OUT = "adjustment_out", "Adjustment (Decrease)"
        RETURN_FROM_CUSTOMER = "return_customer", "Return from Customer"
        RETURN_TO_SUPPLIER = "return_supplier", "Return to Supplier"
        DAMAGE = "damage", "Damage / Write-off"
        PRODUCTION_INPUT = "production_input", "Production Input (Consumed)"
        PRODUCTION_OUTPUT = "production_output", "Production Output (Finished)"

    product = models.ForeignKey(
        "products.Product", on_delete=models.PROTECT, related_name="movements"
    )
    variant = models.ForeignKey(
        "products.ProductVariant", on_delete=models.PROTECT,
        null=True, blank=True, related_name="movements"
    )
    warehouse = models.ForeignKey(
        "warehouses.Warehouse", on_delete=models.PROTECT, related_name="movements"
    )
    movement_type = models.CharField(max_length=25, choices=MovementType.choices, db_index=True)

    # Quantity delta: positive = stock in, negative = stock out
    quantity = models.DecimalField(max_digits=15, decimal_places=3)
    quantity_before = models.DecimalField(max_digits=15, decimal_places=3)
    quantity_after = models.DecimalField(max_digits=15, decimal_places=3)

    # Cost at time of movement
    unit_cost = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    total_cost = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    # Linkage to source document
    reference_type = models.CharField(
        max_length=50, blank=True,
        help_text="e.g. sale_order, purchase_order, stock_transfer"
    )
    reference_id = models.UUIDField(null=True, blank=True, db_index=True)
    reference_number = models.CharField(max_length=100, blank=True)

    # Tracking fields (optional)
    batch_number = models.CharField(max_length=100, blank=True, db_index=True)
    serial_number = models.CharField(max_length=100, blank=True, db_index=True)
    expiry_date = models.DateField(null=True, blank=True)

    notes = models.TextField(blank=True)
    performed_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="stock_movements"
    )

    class Meta:
        db_table = "stock_movements"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "product", "-created_at"]),
            models.Index(fields=["tenant", "movement_type", "-created_at"]),
            models.Index(fields=["tenant", "warehouse", "-created_at"]),
            models.Index(fields=["tenant", "reference_id"]),
        ]

    def __str__(self):
        return (
            f"{self.movement_type} | {self.product.sku} | "
            f"Δ{self.quantity} | {self.warehouse.code}"
        )

    def save(self, *args, **kwargs):
        if not self.total_cost:
            self.total_cost = abs(self.quantity) * self.unit_cost
        super().save(*args, **kwargs)


class BatchLot(TenantAwareModel):
    """
    Tracks a batch/lot of products — for pharma, food, chemicals, etc.
    """
    product = models.ForeignKey(
        "products.Product", on_delete=models.CASCADE, related_name="batches"
    )
    warehouse = models.ForeignKey(
        "warehouses.Warehouse", on_delete=models.CASCADE, related_name="batches"
    )
    batch_number = models.CharField(max_length=100, db_index=True)
    manufacture_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True, db_index=True)
    quantity = models.DecimalField(max_digits=15, decimal_places=3, default=0)
    cost_price = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    supplier_reference = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "batch_lots"
        unique_together = [("tenant", "product", "warehouse", "batch_number")]
        indexes = [
            models.Index(fields=["tenant", "product", "expiry_date"]),
        ]

    def __str__(self):
        return f"Batch {self.batch_number} — {self.product.sku}"

    @property
    def is_expired(self) -> bool:
        if not self.expiry_date:
            return False
        return timezone.now().date() > self.expiry_date

    @property
    def days_to_expiry(self):
        if not self.expiry_date:
            return None
        delta = self.expiry_date - timezone.now().date()
        return delta.days


class SerialNumber(TenantAwareModel):
    """Tracks individual serialized items."""

    class Status(models.TextChoices):
        IN_STOCK = "in_stock", "In Stock"
        SOLD = "sold", "Sold"
        RETURNED = "returned", "Returned"
        DAMAGED = "damaged", "Damaged"
        RESERVED = "reserved", "Reserved"

    product = models.ForeignKey(
        "products.Product", on_delete=models.CASCADE, related_name="serial_numbers"
    )
    warehouse = models.ForeignKey(
        "warehouses.Warehouse", on_delete=models.CASCADE, related_name="serial_numbers"
    )
    serial_number = models.CharField(max_length=200, db_index=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.IN_STOCK, db_index=True
    )
    cost_price = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    purchase_date = models.DateField(null=True, blank=True)
    sold_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "serial_numbers"
        unique_together = [("tenant", "product", "serial_number")]
        indexes = [
            models.Index(fields=["tenant", "product", "status"]),
        ]

    def __str__(self):
        return f"S/N {self.serial_number} — {self.product.sku} [{self.status}]"


class StockTransfer(TenantAwareModel):
    """Transfer of stock between warehouses."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        IN_TRANSIT = "in_transit", "In Transit"
        RECEIVED = "received", "Received"
        CANCELLED = "cancelled", "Cancelled"

    transfer_number = models.CharField(max_length=50, unique=True, db_index=True)
    from_warehouse = models.ForeignKey(
        "warehouses.Warehouse", on_delete=models.PROTECT, related_name="outgoing_transfers"
    )
    to_warehouse = models.ForeignKey(
        "warehouses.Warehouse", on_delete=models.PROTECT, related_name="incoming_transfers"
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    expected_date = models.DateField(null=True, blank=True)
    shipped_date = models.DateField(null=True, blank=True)
    received_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="created_transfers"
    )
    received_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT,
        null=True, blank=True, related_name="received_transfers"
    )

    class Meta:
        db_table = "stock_transfers"
        indexes = [
            models.Index(fields=["tenant", "status", "-created_at"]),
        ]

    def __str__(self):
        return f"Transfer {self.transfer_number}: {self.from_warehouse.code} → {self.to_warehouse.code}"


class StockTransferItem(TenantAwareModel):
    """Line item in a stock transfer."""
    transfer = models.ForeignKey(
        StockTransfer, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey("products.Product", on_delete=models.PROTECT)
    variant = models.ForeignKey(
        "products.ProductVariant", on_delete=models.PROTECT, null=True, blank=True
    )
    quantity_requested = models.DecimalField(max_digits=15, decimal_places=3)
    quantity_received = models.DecimalField(max_digits=15, decimal_places=3, default=0)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "stock_transfer_items"
