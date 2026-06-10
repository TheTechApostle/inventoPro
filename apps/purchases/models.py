"""
Purchases models.
Supplier, purchase orders, goods receipt.
"""
from decimal import Decimal
from django.db import models
from django.utils import timezone
from core.models import TenantAwareModel


class Supplier(TenantAwareModel):
    name = models.CharField(max_length=255, db_index=True)
    contact_person = models.CharField(max_length=150, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True)
    tax_number = models.CharField(max_length=100, blank=True)
    payment_terms = models.CharField(max_length=200, blank=True)
    credit_limit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    outstanding_balance = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    tags = models.JSONField(default=list)

    class Meta:
        db_table = "suppliers"
        indexes = [models.Index(fields=["tenant", "name"])]

    def __str__(self):
        return self.name


class PurchaseOrder(TenantAwareModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent to Supplier"
        CONFIRMED = "confirmed", "Confirmed"
        PARTIAL = "partial", "Partially Received"
        RECEIVED = "received", "Fully Received"
        CANCELLED = "cancelled", "Cancelled"

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PARTIAL = "partial", "Partially Paid"
        PAID = "paid", "Paid"

    po_number = models.CharField(max_length=50, db_index=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchase_orders")
    warehouse = models.ForeignKey(
        "warehouses.Warehouse", on_delete=models.PROTECT, related_name="purchase_orders"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    payment_status = models.CharField(
        max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID
    )

    subtotal = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    shipping_cost = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    amount_due = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    currency = models.CharField(max_length=10, default="NGN")
    order_date = models.DateField(default=timezone.now)
    expected_date = models.DateField(null=True, blank=True)
    received_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    requires_approval = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="approved_pos"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="created_pos"
    )

    class Meta:
        db_table = "purchase_orders"
        unique_together = [("tenant", "po_number")]
        indexes = [
            models.Index(fields=["tenant", "status", "-created_at"]),
            models.Index(fields=["tenant", "supplier", "-created_at"]),
        ]

    def __str__(self):
        return f"PO {self.po_number} — {self.supplier.name}"

    def recalculate_totals(self):
        items = self.items.filter(is_active=True)
        subtotal = sum(item.line_total for item in items)
        self.subtotal = subtotal
        self.total_amount = subtotal - self.discount_amount + self.tax_amount + self.shipping_cost
        self.amount_due = max(self.total_amount - self.amount_paid, Decimal("0"))
        self.save(update_fields=["subtotal", "total_amount", "amount_due", "updated_at"])


class PurchaseOrderItem(TenantAwareModel):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("products.Product", on_delete=models.PROTECT)
    variant = models.ForeignKey(
        "products.ProductVariant", on_delete=models.PROTECT, null=True, blank=True
    )
    quantity_ordered = models.DecimalField(max_digits=15, decimal_places=3)
    quantity_received = models.DecimalField(max_digits=15, decimal_places=3, default=0)
    unit_cost = models.DecimalField(max_digits=15, decimal_places=4)
    line_total = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    batch_number = models.CharField(max_length=100, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "purchase_order_items"

    def __str__(self):
        return f"{self.product.name} x{self.quantity_ordered} @ {self.unit_cost}"

    def save(self, *args, **kwargs):
        self.line_total = (self.quantity_ordered * self.unit_cost).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)

    @property
    def quantity_pending(self):
        return max(self.quantity_ordered - self.quantity_received, Decimal("0"))
