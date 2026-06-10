"""
Core abstract models.
Every domain model in Inventra inherits from these.
"""
import uuid
from django.db import models
from django.utils import timezone
from core.managers import TenantAwareManager


class BaseModel(models.Model):
    """
    Abstract base for ALL models.
    Provides UUID PK, created_at, updated_at, is_active.
    """
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        db_index=True,
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        abstract = True
        ordering = ["-created_at"]

    def soft_delete(self):
        """Mark inactive rather than deleting from DB."""
        self.is_active = False
        self.save(update_fields=["is_active", "updated_at"])


class TenantAwareModel(BaseModel):
    """
    Abstract base for all tenant-scoped models.
    Automatically filters querysets by the current tenant context.
    Never bypass this — use .objects.unscoped() only in admin/migrations.
    """
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s_set",
        db_index=True,
    )

    objects = TenantAwareManager()

    class Meta:
        abstract = True
        ordering = ["-created_at"]
