"""
Notifications app.
In-app notifications + WebSocket push + email alerts.
"""
import json
import logging
from django.db import models
from django.utils import timezone
from django.core.cache import cache
from core.models import TenantAwareModel

logger = logging.getLogger("inventra.notifications")


# ── Models ────────────────────────────────────────────────────────────────────

class Notification(TenantAwareModel):
    class NotificationType(models.TextChoices):
        LOW_STOCK = "low_stock", "Low Stock"
        LOW_STOCK_DIGEST = "low_stock_digest", "Low Stock Digest"
        BATCH_EXPIRY = "batch_expiry", "Batch Expiry"
        ORDER_CREATED = "order_created", "Order Created"
        ORDER_CONFIRMED = "order_confirmed", "Order Confirmed"
        PAYMENT_RECEIVED = "payment_received", "Payment Received"
        PO_APPROVED = "po_approved", "PO Approved"
        EXPENSE_APPROVED = "expense_approved", "Expense Approved"
        USER_INVITED = "user_invited", "User Invited"
        SYSTEM = "system", "System"

    title = models.CharField(max_length=300)
    body = models.TextField()
    notification_type = models.CharField(
        max_length=30, choices=NotificationType.choices, default=NotificationType.SYSTEM
    )
    reference_id = models.CharField(max_length=100, blank=True)
    reference_type = models.CharField(max_length=50, blank=True)

    # Targeting
    recipient = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE,
        null=True, blank=True, related_name="notifications",
        help_text="Null = broadcast to all tenant admins"
    )

    # State
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notifications"
        indexes = [
            models.Index(fields=["tenant", "recipient", "is_read", "-created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.notification_type}] {self.title}"

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at"])
