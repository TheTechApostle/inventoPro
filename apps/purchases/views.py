"""
Purchases app — serializers, views, and URLs.
"""
from decimal import Decimal
from django.utils import timezone
from rest_framework import serializers, viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from core.permissions import (
    TenantPermission, CanViewPurchases, CanManagePurchases, CanApprovePurchases
)
from core.mixins import TenantQuerysetMixin
from core.utils import generate_order_number
from .models import Supplier, PurchaseOrder, PurchaseOrderItem


# ── Serializers ──────────────────────────────────────────────────────────────

class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        exclude = ["tenant"]
        read_only_fields = ["id", "outstanding_balance", "created_at", "updated_at"]


class POItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    quantity_pending = serializers.DecimalField(max_digits=15, decimal_places=3, read_only=True)

    class Meta:
        model = PurchaseOrderItem
        exclude = ["tenant", "order"]
        read_only_fields = ["id", "line_total", "quantity_received", "created_at"]


class POItemWriteSerializer(serializers.Serializer):
    product = serializers.UUIDField()
    variant = serializers.UUIDField(required=False, allow_null=True)
    quantity_ordered = serializers.DecimalField(max_digits=15, decimal_places=3, min_value=Decimal("0.001"))
    unit_cost = serializers.DecimalField(max_digits=15, decimal_places=4, min_value=Decimal("0"))
    batch_number = serializers.CharField(required=False, allow_blank=True, default="")
    expiry_date = serializers.DateField(required=False, allow_null=True)

    def validate(self, data):
        from apps.products.models import Product, ProductVariant
        request = self.context.get("request")
        tenant = request.tenant
        try:
            data["product"] = Product.objects.get(id=data["product"], tenant=tenant)
        except Product.DoesNotExist:
            raise serializers.ValidationError({"product": "Product not found."})
        if data.get("variant"):
            try:
                data["variant"] = ProductVariant.objects.get(id=data["variant"], tenant=tenant)
            except ProductVariant.DoesNotExist:
                raise serializers.ValidationError({"variant": "Variant not found."})
        return data


class PurchaseOrderListSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    item_count = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = [
            "id", "po_number", "supplier", "supplier_name",
            "warehouse", "warehouse_name", "status", "status_display",
            "payment_status", "total_amount", "amount_paid", "amount_due",
            "item_count", "order_date", "expected_date", "created_at",
        ]

    def get_item_count(self, obj):
        return obj.items.count()


class PurchaseOrderDetailSerializer(serializers.ModelSerializer):
    items = POItemSerializer(many=True, read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    created_by_name = serializers.CharField(source="created_by.get_full_name", read_only=True)
    approved_by_name = serializers.CharField(source="approved_by.get_full_name", read_only=True)

    class Meta:
        model = PurchaseOrder
        exclude = ["tenant"]
        read_only_fields = [
            "id", "po_number", "subtotal", "total_amount",
            "amount_due", "payment_status", "created_at", "updated_at",
        ]


class CreatePurchaseOrderSerializer(serializers.Serializer):
    supplier = serializers.UUIDField()
    warehouse = serializers.UUIDField()
    items = POItemWriteSerializer(many=True, min_length=1)
    expected_date = serializers.DateField(required=False, allow_null=True)
    discount_amount = serializers.DecimalField(max_digits=15, decimal_places=2, default=0)
    shipping_cost = serializers.DecimalField(max_digits=15, decimal_places=2, default=0)
    notes = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, data):
        from apps.warehouses.models import Warehouse
        request = self.context.get("request")
        tenant = request.tenant
        try:
            data["supplier"] = Supplier.objects.get(id=data["supplier"], tenant=tenant)
        except Supplier.DoesNotExist:
            raise serializers.ValidationError({"supplier": "Supplier not found."})
        try:
            data["warehouse"] = Warehouse.objects.get(id=data["warehouse"], tenant=tenant)
        except Warehouse.DoesNotExist:
            raise serializers.ValidationError({"warehouse": "Warehouse not found."})
        return data


class ReceiveItemSerializer(serializers.Serializer):
    item_id = serializers.UUIDField()
    quantity_received = serializers.DecimalField(max_digits=15, decimal_places=3, min_value=Decimal("0.001"))


class ReceiveGoodsSerializer(serializers.Serializer):
    items = ReceiveItemSerializer(many=True, min_length=1)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


# ── ViewSets ─────────────────────────────────────────────────────────────────

class SupplierViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    permission_classes = [IsAuthenticated, TenantPermission, CanViewPurchases]
    search_fields = ["name", "email", "phone", "contact_person"]
    filterset_fields = ["is_active"]

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class PurchaseOrderViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    queryset = PurchaseOrder.objects.select_related(
        "supplier", "warehouse", "created_by", "approved_by"
    ).prefetch_related("items")
    permission_classes = [IsAuthenticated, TenantPermission, CanViewPurchases]
    filterset_fields = ["status", "payment_status", "supplier", "warehouse"]
    search_fields = ["po_number", "supplier__name"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        if self.action == "create":
            return CreatePurchaseOrderSerializer
        if self.action == "list":
            return PurchaseOrderListSerializer
        return PurchaseOrderDetailSerializer

    def create(self, request, *args, **kwargs):
        serializer = CreatePurchaseOrderSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        # Check approval requirement
        requires_approval = getattr(
            getattr(request.tenant, "settings", None), "require_purchase_approval", False
        )

        from django.db import transaction
        with transaction.atomic():
            po = PurchaseOrder.objects.create(
                tenant=request.tenant,
                po_number=generate_order_number("PO"),
                supplier=d["supplier"],
                warehouse=d["warehouse"],
                expected_date=d.get("expected_date"),
                discount_amount=d.get("discount_amount", Decimal("0")),
                shipping_cost=d.get("shipping_cost", Decimal("0")),
                notes=d.get("notes", ""),
                requires_approval=requires_approval,
                created_by=request.user,
                currency=request.tenant.currency,
            )
            for item in d["items"]:
                PurchaseOrderItem.objects.create(
                    tenant=request.tenant,
                    order=po,
                    product=item["product"],
                    variant=item.get("variant"),
                    quantity_ordered=item["quantity_ordered"],
                    unit_cost=item["unit_cost"],
                    batch_number=item.get("batch_number", ""),
                    expiry_date=item.get("expiry_date"),
                )
            po.recalculate_totals()

        return Response(
            {"success": True, "data": PurchaseOrderDetailSerializer(po).data},
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(tags=["purchases"])
    @action(detail=True, methods=["post"],
            permission_classes=[IsAuthenticated, TenantPermission, CanApprovePurchases])
    def approve(self, request, pk=None):
        """Approve a PO. Required if tenant requires_purchase_approval=True."""
        po = self.get_object()
        if po.status not in ("draft", "sent"):
            return Response({"success": False, "error": {"message": "PO cannot be approved at this stage."}}, status=400)
        po.approved_by = request.user
        po.approved_at = timezone.now()
        po.status = PurchaseOrder.Status.CONFIRMED
        po.save(update_fields=["approved_by", "approved_at", "status", "updated_at"])
        return Response({"success": True, "message": "Purchase order approved."})

    @extend_schema(tags=["purchases"])
    @action(detail=True, methods=["post"],
            permission_classes=[IsAuthenticated, TenantPermission, CanManagePurchases])
    def receive(self, request, pk=None):
        """
        Receive goods. Updates stock for each received item.
        POST /purchases/orders/{id}/receive/
        Body: {"items": [{"item_id": uuid, "quantity_received": 10}], "notes": ""}
        """
        po = self.get_object()
        if po.status not in ("confirmed", "partial", "sent"):
            return Response(
                {"success": False, "error": {"message": "PO is not in a receivable state."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = ReceiveGoodsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        qty_map = {str(item["item_id"]): item["quantity_received"] for item in d["items"]}

        from apps.inventory.services import StockService
        from django.db import transaction
        with transaction.atomic():
            receipt_items = []
            for item in po.items.filter(is_active=True):
                qty = qty_map.get(str(item.id))
                if not qty:
                    continue
                qty = min(qty, item.quantity_pending)
                if qty <= 0:
                    continue

                receipt_items.append({
                    "product": item.product,
                    "variant": item.variant,
                    "quantity": qty,
                    "unit_cost": item.unit_cost,
                    "batch_number": item.batch_number,
                    "expiry_date": item.expiry_date,
                })
                item.quantity_received += qty
                item.save(update_fields=["quantity_received"])

            if receipt_items:
                StockService.process_purchase_receipt(
                    tenant=request.tenant,
                    warehouse=po.warehouse,
                    performed_by=request.user,
                    items=receipt_items,
                    reference_id=po.id,
                    reference_number=po.po_number,
                )

            # Determine new PO status
            all_received = all(
                item.quantity_received >= item.quantity_ordered
                for item in po.items.filter(is_active=True)
            )
            po.status = PurchaseOrder.Status.RECEIVED if all_received else PurchaseOrder.Status.PARTIAL
            po.received_date = timezone.now().date()
            po.save(update_fields=["status", "received_date", "updated_at"])

        return Response({
            "success": True,
            "message": f"Goods received. PO is now {po.status}.",
            "data": PurchaseOrderDetailSerializer(po).data,
        })

    @extend_schema(tags=["purchases"])
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        po = self.get_object()
        if po.status in ("received",):
            return Response({"success": False, "error": {"message": "Cannot cancel a received PO."}}, status=400)
        po.status = PurchaseOrder.Status.CANCELLED
        po.save(update_fields=["status", "updated_at"])
        return Response({"success": True, "message": "Purchase order cancelled."})


# ── URLs ─────────────────────────────────────────────────────────────────────

router = DefaultRouter()
router.register("suppliers", SupplierViewSet, basename="suppliers")
router.register("orders", PurchaseOrderViewSet, basename="purchase-orders")

urlpatterns = router.urls
