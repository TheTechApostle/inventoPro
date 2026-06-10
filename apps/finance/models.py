"""
Finance models.
Expenses, tax rates, financial accounts, and P&L computation.
"""
from decimal import Decimal
from django.db import models
from django.utils import timezone
from core.models import TenantAwareModel


class ExpenseCategory(TenantAwareModel):
    name = models.CharField(max_length=200)
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="subcategories"
    )
    description = models.TextField(blank=True)
    is_system = models.BooleanField(default=False)

    class Meta:
        db_table = "expense_categories"
        unique_together = [("tenant", "name")]

    def __str__(self):
        return self.name


class Expense(TenantAwareModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        PAID = "paid", "Paid"

    class PaymentMethod(models.TextChoices):
        CASH = "cash", "Cash"
        CARD = "card", "Card"
        TRANSFER = "transfer", "Bank Transfer"
        OTHER = "other", "Other"

    title = models.CharField(max_length=300)
    category = models.ForeignKey(
        ExpenseCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="expenses"
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default="NGN")
    payment_method = models.CharField(
        max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.CASH
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    expense_date = models.DateField(default=timezone.now)
    receipt = models.FileField(upload_to="expense_receipts/%Y/%m/", null=True, blank=True)
    notes = models.TextField(blank=True)
    reference = models.CharField(max_length=200, blank=True)
    vendor = models.CharField(max_length=200, blank=True)
    warehouse = models.ForeignKey(
        "warehouses.Warehouse", on_delete=models.SET_NULL, null=True, blank=True
    )
    submitted_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="submitted_expenses"
    )
    approved_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="approved_expenses"
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "expenses"
        indexes = [
            models.Index(fields=["tenant", "status", "-expense_date"]),
            models.Index(fields=["tenant", "category", "-expense_date"]),
        ]

    def __str__(self):
        return f"{self.title} — {self.total_amount}"

    def save(self, *args, **kwargs):
        if not self.total_amount:
            self.total_amount = self.amount + self.tax_amount
        super().save(*args, **kwargs)


class TaxRate(TenantAwareModel):
    name = models.CharField(max_length=100)
    rate = models.DecimalField(max_digits=5, decimal_places=2)
    is_default = models.BooleanField(default=False)
    applies_to = models.CharField(
        max_length=20,
        choices=[("sales", "Sales"), ("purchases", "Purchases"), ("both", "Both")],
        default="both",
    )
    description = models.TextField(blank=True)

    class Meta:
        db_table = "tax_rates"
        unique_together = [("tenant", "name")]

    def __str__(self):
        return f"{self.name} ({self.rate}%)"


class FinancialSummary(TenantAwareModel):
    """
    Pre-aggregated daily financial summary per tenant.
    Populated by Celery Beat — used for fast dashboard queries.
    """
    date = models.DateField(db_index=True)
    total_revenue = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    total_cogs = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    gross_profit = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    total_expenses = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    net_profit = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    order_count = models.PositiveIntegerField(default=0)
    items_sold = models.DecimalField(max_digits=15, decimal_places=3, default=0)

    class Meta:
        db_table = "financial_summaries"
        unique_together = [("tenant", "date")]
        ordering = ["-date"]

    def __str__(self):
        return f"{self.tenant.slug} | {self.date} | Profit: {self.net_profit}"
