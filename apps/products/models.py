"""
Product catalog models.
Products are the items tracked in inventory.
"""
from django.db import models
from core.models import TenantAwareModel


class Category(TenantAwareModel):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220)
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="children"
    )
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="categories/%Y/", null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "categories"
        unique_together = [("tenant", "slug")]
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class Unit(TenantAwareModel):
    """Units of measure: piece, kg, litre, box, carton, etc."""
    name = models.CharField(max_length=100)
    abbreviation = models.CharField(max_length=20)
    is_base = models.BooleanField(default=False)

    class Meta:
        db_table = "units"
        unique_together = [("tenant", "abbreviation")]

    def __str__(self):
        return f"{self.name} ({self.abbreviation})"


class Product(TenantAwareModel):
    """
    A product in the catalog.
    Can be simple, have variants, be a bundle/kit, or a service.
    """

    class ProductType(models.TextChoices):
        SIMPLE = "simple", "Simple Product"
        VARIANT = "variant", "Product with Variants"
        BUNDLE = "bundle", "Bundle / Kit"
        SERVICE = "service", "Service"

    class TaxType(models.TextChoices):
        TAXABLE = "taxable", "Taxable"
        EXEMPT = "exempt", "Tax Exempt"
        ZERO_RATED = "zero_rated", "Zero Rated"

    # Identity
    name = models.CharField(max_length=300, db_index=True)
    slug = models.SlugField(max_length=320)
    sku = models.CharField(max_length=100, db_index=True)
    barcode = models.CharField(max_length=150, blank=True, db_index=True)
    product_type = models.CharField(
        max_length=20, choices=ProductType.choices, default=ProductType.SIMPLE
    )

    # Categorization
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="products"
    )
    tags = models.JSONField(default=list, blank=True)

    # Pricing
    cost_price = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    selling_price = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    min_selling_price = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        help_text="Floor price — cannot sell below this"
    )

    # Tax
    tax_type = models.CharField(
        max_length=20, choices=TaxType.choices, default=TaxType.TAXABLE
    )
    tax_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Override per-product; 0 = use tenant default"
    )

    # Unit
    unit = models.ForeignKey(
        Unit, on_delete=models.SET_NULL, null=True, blank=True
    )
    unit_of_measure = models.CharField(max_length=50, default="piece")

    # Physical attributes
    weight = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    dimensions = models.JSONField(
        default=dict, blank=True,
        help_text='{"length": 10, "width": 5, "height": 3, "unit": "cm"}'
    )

    # Inventory tracking
    track_inventory = models.BooleanField(default=True)
    track_serial = models.BooleanField(default=False)
    track_batch = models.BooleanField(default=False)
    track_expiry = models.BooleanField(default=False)

    # Reorder settings
    reorder_point = models.DecimalField(max_digits=15, decimal_places=3, default=0)
    reorder_quantity = models.DecimalField(max_digits=15, decimal_places=3, default=0)
    max_stock_level = models.DecimalField(max_digits=15, decimal_places=3, default=0)

    # Media
    image = models.ImageField(upload_to="products/%Y/", null=True, blank=True)
    images = models.JSONField(default=list, blank=True)  # additional image URLs

    # Content
    description = models.TextField(blank=True)
    short_description = models.CharField(max_length=500, blank=True)
    notes = models.TextField(blank=True)

    # Meta
    is_featured = models.BooleanField(default=False)
    is_purchasable = models.BooleanField(default=True)
    is_sellable = models.BooleanField(default=True)

    class Meta:
        db_table = "products"
        unique_together = [("tenant", "sku")]
        indexes = [
            models.Index(fields=["tenant", "name"]),
            models.Index(fields=["tenant", "barcode"]),
            models.Index(fields=["tenant", "category", "is_active"]),
            models.Index(fields=["tenant", "product_type"]),
        ]

    def __str__(self):
        return f"{self.name} [{self.sku}]"

    @property
    def margin_percentage(self) -> float:
        if self.selling_price and self.cost_price:
            return round(
                ((self.selling_price - self.cost_price) / self.selling_price) * 100, 2
            )
        return 0.0

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            import uuid
            self.slug = f"{slugify(self.name)}-{uuid.uuid4().hex[:6]}"
        super().save(*args, **kwargs)


class ProductVariant(TenantAwareModel):
    """
    A variant of a product (e.g. Red/XL, Blue/M).
    Overrides parent product's price and SKU.
    """
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="variants"
    )
    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=100, db_index=True)
    barcode = models.CharField(max_length=150, blank=True)
    attributes = models.JSONField(
        default=dict,
        help_text='{"color": "Red", "size": "XL"}'
    )
    cost_price = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    selling_price = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    image = models.ImageField(upload_to="variants/%Y/", null=True, blank=True)

    class Meta:
        db_table = "product_variants"
        unique_together = [("tenant", "sku")]

    def __str__(self):
        return f"{self.product.name} — {self.name}"


class BundleItem(TenantAwareModel):
    """An item that is part of a Bundle/Kit product."""
    bundle = models.ForeignKey(
        Product, on_delete=models.CASCADE,
        related_name="bundle_items",
        limit_choices_to={"product_type": "bundle"},
    )
    component = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="used_in_bundles"
    )
    variant = models.ForeignKey(
        ProductVariant, on_delete=models.SET_NULL, null=True, blank=True
    )
    quantity = models.DecimalField(max_digits=15, decimal_places=3, default=1)

    class Meta:
        db_table = "bundle_items"

    def __str__(self):
        return f"{self.bundle.name} includes {self.quantity}x {self.component.name}"
