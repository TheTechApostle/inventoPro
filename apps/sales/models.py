"""
Sales models.
Covers customers, orders, invoices, payments, and POS sessions.
"""
from decimal import Decimal
from django.db import models
from django.utils import timezone
from core.models import TenantAwareModel


class Customer(TenantAwareModel):
    """A customer belonging to a tenant."""
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True, db_index=True)
    phone = models.CharField(max_length=30, blank=True, db_index=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True)
    company_name = models.CharField(max_length=200, blank=True)
    tax_number = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    credit_limit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    outstanding_balance = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    loyalty_points = models.PositiveIntegerField(default=0)
    customer_group = models.CharField(max_length=100, blank=True)
    tags = models.JSONField(default=list)

    class Meta:
        db_table = "customers"
        indexes = [
            models.Index(fields=["tenant", "email"]),
            models.Index(fields=["tenant", "phone"]),
        ]

    def __str__(self):
        name = f"{self.first_name} {self.last_name}".strip()
        return f"{name} ({self.phone or self.email})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()


class SalesOrder(TenantAwareModel):
    """
    A sales order / invoice.
    Drives stock deductions and payment tracking.
    """
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        CONFIRMED = "confirmed", "Confirmed"
        PROCESSING = "processing", "Processing"
        PACKED = "packed", "Packed"
        SHIPPED = "shipped", "Shipped"
        DELIVERED = "delivered", "Delivered"
        CANCELLED = "cancelled", "Cancelled"
        RETURNED = "returned", "Returned"

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PARTIAL = "partial", "Partially Paid"
        PAID = "paid", "Paid"
        OVERPAID = "overpaid", "Overpaid"
        REFUNDED = "refunded", "Refunded"

    class SaleChannel(models.TextChoices):
        POS = "pos", "Point of Sale"
        ONLINE = "online", "Online"
        PHONE = "phone", "Phone Order"
        WHATSAPP = "whatsapp", "WhatsApp"
        WALK_IN = "walk_in", "Walk-in"
        OTHER = "other", "Other"

    order_number = models.CharField(max_length=50, db_index=True)
    customer = models.ForeignKey(
        Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name="orders"
    )
    warehouse = models.ForeignKey(
        "warehouses.Warehouse", on_delete=models.PROTECT, related_name="sales_orders"
    )
    branch = models.ForeignKey(
        "warehouses.Branch", on_delete=models.SET_NULL, null=True, blank=True
    )

    # Status
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    payment_status = models.CharField(
        max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID, db_index=True
    )
    sale_channel = models.CharField(
        max_length=20, choices=SaleChannel.choices, default=SaleChannel.WALK_IN
    )

    # Financials
    subtotal = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    discount_type = models.CharField(
        max_length=10, choices=[("fixed", "Fixed"), ("percent", "Percent")], default="fixed"
    )
    discount_value = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    shipping_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    amount_due = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    # Meta
    currency = models.CharField(max_length=10, default="NGN")
    notes = models.TextField(blank=True)
    internal_notes = models.TextField(blank=True)
    tags = models.JSONField(default=list)

    # Dates
    order_date = models.DateField(default=timezone.now)
    due_date = models.DateField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    # Staff
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="created_orders"
    )
    assigned_to = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="assigned_orders"
    )

    # POS reference
    pos_session = models.ForeignKey(
        "POSSession", on_delete=models.SET_NULL, null=True, blank=True, related_name="orders"
    )

    class Meta:
        db_table = "sales_orders"
        unique_together = [("tenant", "order_number")]
        indexes = [
            models.Index(fields=["tenant", "status", "-created_at"]),
            models.Index(fields=["tenant", "payment_status", "-created_at"]),
            models.Index(fields=["tenant", "customer", "-created_at"]),
            models.Index(fields=["tenant", "order_date"]),
        ]

    def __str__(self):
        return f"Order {self.order_number} — {self.total_amount}"

    def recalculate_totals(self):
        """Recompute subtotal, discount, tax, total from line items."""
        items = self.items.filter(is_active=True)
        subtotal = sum(item.line_total for item in items)
        self.subtotal = subtotal

        # Discount
        if self.discount_type == "percent":
            self.discount_amount = (subtotal * self.discount_value / 100).quantize(Decimal("0.01"))
        else:
            self.discount_amount = min(self.discount_value, subtotal)

        taxable = subtotal - self.discount_amount
        # Tax from tenant settings
        try:
            tax_rate = self.tenant.default_tax_rate
        except Exception:
            tax_rate = Decimal("0")
        self.tax_amount = (taxable * tax_rate / 100).quantize(Decimal("0.01"))
        self.total_amount = taxable + self.tax_amount + self.shipping_amount
        self.amount_due = max(self.total_amount - self.amount_paid, Decimal("0"))
        self.save(update_fields=[
            "subtotal", "discount_amount", "tax_amount",
            "total_amount", "amount_due", "updated_at",
        ])

    def update_payment_status(self):
        if self.amount_paid <= 0:
            self.payment_status = self.PaymentStatus.UNPAID
        elif self.amount_paid >= self.total_amount:
            self.payment_status = self.PaymentStatus.PAID
        else:
            self.payment_status = self.PaymentStatus.PARTIAL
        self.save(update_fields=["payment_status", "updated_at"])


class SalesOrderItem(TenantAwareModel):
    """A line item on a sales order."""
    order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("products.Product", on_delete=models.PROTECT)
    variant = models.ForeignKey(
        "products.ProductVariant", on_delete=models.PROTECT, null=True, blank=True
    )
    description = models.CharField(max_length=500, blank=True)
    quantity = models.DecimalField(max_digits=15, decimal_places=3)
    unit_price = models.DecimalField(max_digits=15, decimal_places=2)
    cost_price = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    class Meta:
        db_table = "sales_order_items"

    def __str__(self):
        return f"{self.product.name} x{self.quantity} = {self.line_total}"

    def save(self, *args, **kwargs):
        gross = self.quantity * self.unit_price
        if self.discount_pct:
            self.discount_amount = (gross * self.discount_pct / 100).quantize(Decimal("0.01"))
        self.line_total = (gross - self.discount_amount).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)

    @property
    def profit(self):
        return (self.unit_price - self.cost_price) * self.quantity


class Payment(TenantAwareModel):
    """A payment record against a sales order."""
    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        CARD = "card", "Card"
        TRANSFER = "transfer", "Bank Transfer"
        POS_TERMINAL = "pos_terminal", "POS Terminal"
        MOBILE_MONEY = "mobile_money", "Mobile Money"
        CREDIT = "credit", "Store Credit"
        CHEQUE = "cheque", "Cheque"
        SPLIT = "split", "Split Payment"
        OTHER = "other", "Other"

    order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    method = models.CharField(max_length=20, choices=Method.choices)
    reference = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    received_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT)
    payment_date = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "payments"
        indexes = [models.Index(fields=["tenant", "order", "payment_date"])]

    def __str__(self):
        return f"Payment {self.amount} [{self.method}] for {self.order.order_number}"


class POSSession(TenantAwareModel):
    """
    A cashier's POS session.
    Tracks opening/closing float and session totals.
    """
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"

    warehouse = models.ForeignKey(
        "warehouses.Warehouse", on_delete=models.PROTECT, related_name="pos_sessions"
    )
    cashier = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="pos_sessions"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    opening_float = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    closing_float = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    expected_cash = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    opened_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "pos_sessions"
        indexes = [models.Index(fields=["tenant", "status", "-opened_at"])]

    def __str__(self):
        return f"POS Session {self.cashier.get_full_name()} [{self.status}]"

    @property
    def total_sales(self):
        return self.orders.filter(
            status__in=["confirmed", "delivered"]
        ).aggregate(
            total=__import__("django.db.models", fromlist=["Sum"]).Sum("total_amount")
        )["total"] or Decimal("0")

    @property
    def cash_variance(self):
        if self.closing_float is not None:
            return self.closing_float - self.expected_cash
        return None
