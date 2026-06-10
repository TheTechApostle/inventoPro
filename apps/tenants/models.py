"""
Tenant models.
A Tenant is a business account on the platform.
One tenant can have multiple branches, users, and warehouses.
"""
from django.db import models
from django.utils.text import slugify
from core.models import BaseModel


class Tenant(BaseModel):
    """
    The root entity for multi-tenancy.
    Everything in the system belongs to a Tenant.
    """

    class PlanType(models.TextChoices):
        FREE = "free", "Free"
        STARTER = "starter", "Starter"
        GROWTH = "growth", "Growth"
        ENTERPRISE = "enterprise", "Enterprise"

    class BusinessType(models.TextChoices):
        RETAIL = "retail", "Retail Store"
        SUPERMARKET = "supermarket", "Supermarket"
        PHARMACY = "pharmacy", "Pharmacy"
        RESTAURANT = "restaurant", "Restaurant"
        HOTEL = "hotel", "Hotel"
        WAREHOUSE = "warehouse", "Warehouse"
        MANUFACTURING = "manufacturing", "Manufacturing"
        FASHION = "fashion", "Fashion"
        CONSTRUCTION = "construction", "Construction"
        DISTRIBUTOR = "distributor", "Distributor"
        ELECTRONICS = "electronics", "Electronics"
        AGRICULTURE = "agriculture", "Agriculture"
        SERVICE = "service", "Service Business"
        WHOLESALE = "wholesale", "Wholesale"
        OTHER = "other", "Other"

    # Identity
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, db_index=True, max_length=100)
    subdomain = models.CharField(max_length=100, unique=True, db_index=True)
    custom_domain = models.CharField(max_length=255, blank=True, null=True, unique=True)
    business_type = models.CharField(
        max_length=30, choices=BusinessType.choices, default=BusinessType.RETAIL
    )
    registration_number = models.CharField(max_length=100, blank=True)

    # Owner (the user who created/owns this tenant)
    owner = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="owned_tenants",
    )

    # Subscription plan
    plan = models.CharField(
        max_length=20, choices=PlanType.choices, default=PlanType.FREE
    )
    plan_started_at = models.DateTimeField(null=True, blank=True)
    plan_expires_at = models.DateTimeField(null=True, blank=True)
    is_trial = models.BooleanField(default=True)

    # Plan limits (enforced in service layer)
    max_users = models.PositiveIntegerField(default=3)
    max_products = models.PositiveIntegerField(default=500)
    max_warehouses = models.PositiveIntegerField(default=1)
    max_monthly_orders = models.PositiveIntegerField(default=200)

    # Branding
    logo = models.ImageField(upload_to="tenant_logos/%Y/", null=True, blank=True)
    primary_color = models.CharField(max_length=7, default="#6366F1")
    secondary_color = models.CharField(max_length=7, default="#8B5CF6")

    # Regional settings
    currency = models.CharField(max_length=10, default="NGN")
    currency_symbol = models.CharField(max_length=5, default="₦")
    timezone = models.CharField(max_length=50, default="Africa/Lagos")
    country = models.CharField(max_length=100, default="Nigeria")
    tax_number = models.CharField(max_length=100, blank=True)
    default_tax_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=7.5
    )  # Nigeria VAT

    # Feature flags
    feature_pos = models.BooleanField(default=True)
    feature_manufacturing = models.BooleanField(default=False)
    feature_ecommerce = models.BooleanField(default=False)
    feature_multi_currency = models.BooleanField(default=False)

    # Onboarding
    onboarding_complete = models.BooleanField(default=False)
    onboarding_step = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "tenants"
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["subdomain"]),
            models.Index(fields=["plan", "is_active"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.slug})"

    def save(self, *args, **kwargs):
        if not self.slug:
            from core.utils import slugify_unique
            self.slug = slugify_unique(self.name)
        if not self.subdomain:
            self.subdomain = self.slug
        super().save(*args, **kwargs)

    @property
    def is_plan_active(self) -> bool:
        from django.utils import timezone
        if self.plan == self.PlanType.FREE:
            return True
        if self.plan_expires_at is None:
            return True
        return timezone.now() <= self.plan_expires_at

    def get_plan_limits(self) -> dict:
        return {
            "max_users": self.max_users,
            "max_products": self.max_products,
            "max_warehouses": self.max_warehouses,
            "max_monthly_orders": self.max_monthly_orders,
        }


class TenantSettings(BaseModel):
    """Extended per-tenant configuration."""
    tenant = models.OneToOneField(
        Tenant, on_delete=models.CASCADE, related_name="settings"
    )
    invoice_prefix = models.CharField(max_length=20, default="INV")
    order_prefix = models.CharField(max_length=20, default="ORD")
    po_prefix = models.CharField(max_length=20, default="PO")
    low_stock_alert_email = models.BooleanField(default=True)
    daily_report_email = models.BooleanField(default=False)
    require_purchase_approval = models.BooleanField(default=False)
    require_sales_approval = models.BooleanField(default=False)
    allow_negative_stock = models.BooleanField(default=False)
    stock_valuation_method = models.CharField(
        max_length=20,
        choices=[("fifo", "FIFO"), ("lifo", "LIFO"), ("avg", "Weighted Average")],
        default="avg",
    )

    class Meta:
        db_table = "tenant_settings"

    def __str__(self):
        return f"Settings: {self.tenant.name}"
