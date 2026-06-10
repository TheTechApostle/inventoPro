"""Products app — serializers, views, and URLs in one file for compactness."""
from rest_framework import serializers, viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from core.permissions import TenantPermission, CanViewProducts, CanManageProducts
from core.mixins import TenantQuerysetMixin, TenantCreateMixin
from .models import Category, Unit, Product, ProductVariant, BundleItem


# ── Serializers ──────────────────────────────────────────────────────────────

class CategorySerializer(serializers.ModelSerializer):
    children_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        exclude = ["tenant"]
        read_only_fields = ["id", "slug", "created_at", "updated_at"]

    def get_children_count(self, obj):
        return obj.children.filter(is_active=True).count()


class UnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unit
        exclude = ["tenant"]
        read_only_fields = ["id", "created_at", "updated_at"]


class ProductVariantSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductVariant
        exclude = ["tenant", "product"]
        read_only_fields = ["id", "created_at", "updated_at"]


class BundleItemSerializer(serializers.ModelSerializer):
    component_name = serializers.CharField(source="component.name", read_only=True)
    component_sku = serializers.CharField(source="component.sku", read_only=True)

    class Meta:
        model = BundleItem
        exclude = ["tenant", "bundle"]
        read_only_fields = ["id", "created_at", "updated_at"]


class ProductListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views."""
    category_name = serializers.CharField(source="category.name", read_only=True)
    margin_percentage = serializers.FloatField(read_only=True)

    class Meta:
        model = Product
        fields = [
            "id", "name", "sku", "barcode", "product_type",
            "category_name", "selling_price", "cost_price",
            "margin_percentage", "unit_of_measure",
            "reorder_point", "is_active", "image",
        ]


class ProductDetailSerializer(serializers.ModelSerializer):
    """Full serializer for create/update/retrieve."""
    category_name = serializers.CharField(source="category.name", read_only=True)
    variants = ProductVariantSerializer(many=True, read_only=True)
    bundle_items = BundleItemSerializer(many=True, read_only=True)
    margin_percentage = serializers.FloatField(read_only=True)

    class Meta:
        model = Product
        exclude = ["tenant"]
        read_only_fields = ["id", "slug", "created_at", "updated_at"]


# ── ViewSets ─────────────────────────────────────────────────────────────────

class CategoryViewSet(TenantQuerysetMixin, TenantCreateMixin, viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [IsAuthenticated, TenantPermission, CanViewProducts]
    search_fields = ["name"]
    filterset_fields = ["parent", "is_active"]

    @action(detail=False, methods=["get"])
    def tree(self, request):
        """GET /categories/tree/ — returns root categories with children nested."""
        roots = Category.objects.filter(
            tenant=request.tenant, parent__isnull=True, is_active=True
        ).prefetch_related("children")
        data = []
        for cat in roots:
            children = CategorySerializer(
                cat.children.filter(is_active=True), many=True
            ).data
            cat_data = CategorySerializer(cat).data
            cat_data["children"] = children
            data.append(cat_data)
        return Response({"success": True, "data": data})


class UnitViewSet(TenantQuerysetMixin, TenantCreateMixin, viewsets.ModelViewSet):
    queryset = Unit.objects.all()
    serializer_class = UnitSerializer
    permission_classes = [IsAuthenticated, TenantPermission, CanViewProducts]


class ProductViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    queryset = Product.objects.select_related("category", "unit").prefetch_related("variants")
    permission_classes = [IsAuthenticated, TenantPermission, CanViewProducts]
    search_fields = ["name", "sku", "barcode", "description"]
    filterset_fields = ["product_type", "category", "is_active", "is_featured", "track_inventory"]
    ordering_fields = ["name", "selling_price", "cost_price", "created_at"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        if self.action == "list":
            return ProductListSerializer
        return ProductDetailSerializer

    def perform_create(self, serializer):
        from apps.tenants.services import TenantService
        count = Product.objects.filter(tenant=self.request.tenant).count()
        TenantService.check_plan_limit(self.request.tenant, "products", count)
        serializer.save(tenant=self.request.tenant)

    @action(detail=True, methods=["post"])
    def add_variant(self, request, pk=None):
        """POST /products/{id}/add_variant/"""
        product = self.get_object()
        serializer = ProductVariantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(product=product, tenant=request.tenant)
        return Response({"success": True, "data": serializer.data}, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"])
    def low_stock(self, request):
        """GET /products/low_stock/ — products at or below reorder point."""
        from django.db.models import F, OuterRef, Subquery
        from apps.inventory.models import StockLevel
        # Get products where any warehouse stock is <= reorder point
        low = StockLevel.objects.filter(
            tenant=request.tenant,
            product=OuterRef("pk"),
            quantity__lte=F("product__reorder_point"),
        )
        products = Product.objects.filter(
            tenant=request.tenant,
            is_active=True,
            track_inventory=True,
        ).filter(
            id__in=StockLevel.objects.filter(
                tenant=request.tenant,
                quantity__lte=F("product__reorder_point"),
            ).values("product_id")
        )
        serializer = ProductListSerializer(products, many=True)
        return Response({"success": True, "count": products.count(), "data": serializer.data})

    @action(detail=False, methods=["post"])
    def bulk_upload(self, request):
        """POST /products/bulk_upload/ — accept CSV/JSON list of products."""
        products_data = request.data.get("products", [])
        if not products_data:
            return Response(
                {"success": False, "error": {"message": "No products provided."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        created, errors = [], []
        for item in products_data:
            s = ProductDetailSerializer(data=item)
            if s.is_valid():
                s.save(tenant=request.tenant)
                created.append(s.data["sku"])
            else:
                errors.append({"sku": item.get("sku"), "errors": s.errors})
        return Response({
            "success": True,
            "created_count": len(created),
            "error_count": len(errors),
            "errors": errors,
        })
