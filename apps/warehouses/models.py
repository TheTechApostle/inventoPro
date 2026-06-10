from django.db import models
from core.models import TenantAwareModel


class Warehouse(TenantAwareModel):
    """
    A physical location where stock is stored.
    Tenant can have multiple warehouses (within plan limits).
    """
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=20)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    manager = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="managed_warehouses"
    )
    is_default = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "warehouses"
        unique_together = [("tenant", "code")]
        ordering = ["-is_default", "name"]

    def __str__(self):
        return f"{self.name} ({self.code})"

    def save(self, *args, **kwargs):
        # Ensure only one default per tenant
        if self.is_default:
            Warehouse.objects.filter(tenant=self.tenant, is_default=True).update(is_default=False)
        super().save(*args, **kwargs)


class Branch(TenantAwareModel):
    """
    Branch / outlet of a business.
    A branch may have its own warehouse or share one.
    """
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=20)
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="branches"
    )
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    manager = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="managed_branches"
    )
    is_default = models.BooleanField(default=False)

    class Meta:
        db_table = "branches"
        unique_together = [("tenant", "code")]

    def __str__(self):
        return f"{self.name} [{self.code}]"
