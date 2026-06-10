"""
Inventory views.
All stock read/write endpoints.
"""
import logging
from decimal import Decimal
from django.db.models import F, Sum, Count, Q
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiParameter
from core.permissions import (
    TenantPermission, CanViewInventory, CanManageInventory, CanAdjustStock
)
from core.mixins import TenantQuerysetMixin
from core.utils import generate_order_number
from .models import (
    StockLevel, StockMovement, BatchLot,
    SerialNumber, StockTransfer, StockTransferItem,
)
from .serializers import (
    StockLevelSerializer, StockMovementSerializer, StockAdjustSerializer,
    BatchLotSerializer, SerialNumberSerializer,
    StockTransferSerializer, StockTransferItemSerializer,
)
from .services import StockService

logger = logging.getLogger("inventra.inventory")


class StockLevelViewSet(TenantQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    """
    Read-only view of current stock levels.
    Use /adjust/ or /transfer/ to modify stock.
    GET  /api/v1/inventory/stock/
    GET  /api/v1/inventory/stock/{id}/
    GET  /api/v1/inventory/stock/low_stock/
    GET  /api/v1/inventory/stock/out_of_stock/
    GET  /api/v1/inventory/stock/valuation/
    POST /api/v1/inventory/stock/adjust/
    """
    queryset = StockLevel.objects.select_related(
        "product", "variant", "warehouse"
    )
    serializer_class = StockLevelSerializer
    permission_classes = [IsAuthenticated, TenantPermission, CanViewInventory]
    filterset_fields = ["warehouse", "product", "variant"]
    search_fields = ["product__name", "product__sku", "product__barcode"]
    ordering_fields = ["quantity", "updated_at", "product__name"]

    @extend_schema(tags=["inventory"])
    @action(detail=False, methods=["get"])
    def low_stock(self, request):
        """Products at or below reorder point."""
        qs = (
            self.get_queryset()
            .filter(
                quantity__lte=F("product__reorder_point"),
                quantity__gt=0,
                product__track_inventory=True,
                is_active=True,
            )
            .select_related("product__category", "warehouse")
            .order_by("quantity")
        )
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(StockLevelSerializer(page, many=True).data)
        return Response({"success": True, "data": StockLevelSerializer(qs, many=True).data})

    @extend_schema(tags=["inventory"])
    @action(detail=False, methods=["get"])
    def out_of_stock(self, request):
        """Products with zero quantity."""
        qs = (
            self.get_queryset()
            .filter(quantity__lte=0, product__track_inventory=True, is_active=True)
            .select_related("product__category", "warehouse")
            .order_by("product__name")
        )
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(StockLevelSerializer(page, many=True).data)
        return Response({"success": True, "data": StockLevelSerializer(qs, many=True).data})

    @extend_schema(tags=["inventory"])
    @action(detail=False, methods=["get"])
    def valuation(self, request):
        """
        Total inventory value broken down by warehouse and category.
        GET /api/v1/inventory/stock/valuation/
        """
        qs = self.get_queryset().filter(quantity__gt=0)

        # Total value
        total = qs.aggregate(
            total_value=Sum(F("quantity") * F("average_cost")),
            total_units=Sum("quantity"),
            product_count=Count("product", distinct=True),
        )

        # By warehouse
        by_warehouse = (
            qs.values("warehouse__id", "warehouse__name", "warehouse__code")
            .annotate(
                value=Sum(F("quantity") * F("average_cost")),
                units=Sum("quantity"),
                products=Count("product", distinct=True),
            )
            .order_by("-value")
        )

        # By category
        by_category = (
            qs.values("product__category__id", "product__category__name")
            .annotate(value=Sum(F("quantity") * F("average_cost")), units=Sum("quantity"))
            .order_by("-value")
        )

        return Response({
            "success": True,
            "data": {
                "summary": {
                    "total_value": total["total_value"] or 0,
                    "total_units": total["total_units"] or 0,
                    "product_count": total["product_count"] or 0,
                },
                "by_warehouse": list(by_warehouse),
                "by_category": list(by_category),
            },
        })

    @extend_schema(tags=["inventory"])
    @action(
        detail=False, methods=["post"],
        permission_classes=[IsAuthenticated, TenantPermission, CanAdjustStock],
    )
    def adjust(self, request):
        """
        Manual stock adjustment.
        POST /api/v1/inventory/stock/adjust/
        """
        serializer = StockAdjustSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        movement = StockService.adjust_stock(
            tenant=request.tenant,
            product=d["product"],
            variant=d.get("variant"),
            warehouse=d["warehouse"],
            quantity_delta=d["quantity_delta"],
            movement_type=d["movement_type"],
            performed_by=request.user,
            unit_cost=d.get("unit_cost", Decimal("0")),
            batch_number=d.get("batch_number", ""),
            serial_number=d.get("serial_number", ""),
            expiry_date=d.get("expiry_date"),
            notes=d.get("notes", ""),
        )
        return Response(
            {"success": True, "data": StockMovementSerializer(movement).data},
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(tags=["inventory"])
    @action(
        detail=False, methods=["post"],
        permission_classes=[IsAuthenticated, TenantPermission, CanAdjustStock],
        url_path="bulk-adjust",
    )
    def bulk_adjust(self, request):
        """
        Bulk stock adjustment (e.g. stocktake).
        POST /api/v1/inventory/stock/bulk-adjust/
        Body: {"adjustments": [...StockAdjustSerializer fields...]}
        """
        items = request.data.get("adjustments", [])
        if not items:
            return Response(
                {"success": False, "error": {"message": "No adjustments provided."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        results, errors = [], []
        for i, item in enumerate(items):
            s = StockAdjustSerializer(data=item, context={"request": request})
            if not s.is_valid():
                errors.append({"index": i, "errors": s.errors})
                continue
            d = s.validated_data
            try:
                movement = StockService.adjust_stock(
                    tenant=request.tenant,
                    product=d["product"],
                    variant=d.get("variant"),
                    warehouse=d["warehouse"],
                    quantity_delta=d["quantity_delta"],
                    movement_type=d["movement_type"],
                    performed_by=request.user,
                    unit_cost=d.get("unit_cost", Decimal("0")),
                    notes=d.get("notes", ""),
                )
                results.append(StockMovementSerializer(movement).data)
            except Exception as e:
                errors.append({"index": i, "error": str(e)})

        return Response({
            "success": True,
            "processed": len(results),
            "failed": len(errors),
            "movements": results,
            "errors": errors,
        }, status=status.HTTP_207_MULTI_STATUS if errors else status.HTTP_201_CREATED)

    @extend_schema(tags=["inventory"])
    @action(detail=False, methods=["get"], url_path="by-warehouse/(?P<warehouse_id>[^/.]+)")
    def by_warehouse(self, request, warehouse_id=None):
        """GET /api/v1/inventory/stock/by-warehouse/{warehouse_id}/"""
        qs = self.get_queryset().filter(
            warehouse__id=warehouse_id, quantity__gt=0
        ).select_related("product__category", "warehouse")
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(StockLevelSerializer(page, many=True).data)
        return Response({"success": True, "data": StockLevelSerializer(qs, many=True).data})


class StockMovementViewSet(TenantQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    """
    Immutable ledger of all stock movements.
    GET  /api/v1/inventory/movements/
    GET  /api/v1/inventory/movements/{id}/
    GET  /api/v1/inventory/movements/summary/
    """
    queryset = StockMovement.objects.select_related(
        "product", "variant", "warehouse", "performed_by"
    )
    serializer_class = StockMovementSerializer
    permission_classes = [IsAuthenticated, TenantPermission, CanViewInventory]
    filterset_fields = ["movement_type", "warehouse", "product"]
    search_fields = [
        "product__name", "product__sku", "reference_number",
        "batch_number", "serial_number",
    ]
    ordering_fields = ["created_at", "quantity"]
    ordering = ["-created_at"]

    @extend_schema(tags=["inventory"])
    @action(detail=False, methods=["get"])
    def summary(self, request):
        """
        Movement summary stats for the given period.
        GET /api/v1/inventory/movements/summary/?days=30
        """
        from core.utils import parse_date_range
        date_from, date_to = parse_date_range(request)

        qs = self.get_queryset().filter(
            created_at__gte=date_from, created_at__lte=date_to
        )
        summary = qs.values("movement_type").annotate(
            count=Count("id"),
            total_qty=Sum("quantity"),
            total_cost=Sum("total_cost"),
        ).order_by("movement_type")

        return Response({"success": True, "data": list(summary)})

    @extend_schema(tags=["inventory"])
    @action(detail=False, methods=["get"], url_path="product/(?P<product_id>[^/.]+)")
    def by_product(self, request, product_id=None):
        """GET /api/v1/inventory/movements/product/{product_id}/?days=90"""
        qs = self.get_queryset().filter(product__id=product_id).order_by("-created_at")
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(StockMovementSerializer(page, many=True).data)
        return Response({"success": True, "data": StockMovementSerializer(qs, many=True).data})


class StockTransferViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    """
    Inter-warehouse stock transfers.
    POST /api/v1/inventory/transfers/
    POST /api/v1/inventory/transfers/{id}/confirm/
    POST /api/v1/inventory/transfers/{id}/receive/
    POST /api/v1/inventory/transfers/{id}/cancel/
    """
    queryset = StockTransfer.objects.prefetch_related("items").select_related(
        "from_warehouse", "to_warehouse", "created_by"
    )
    serializer_class = StockTransferSerializer
    permission_classes = [IsAuthenticated, TenantPermission, CanManageInventory]
    filterset_fields = ["status", "from_warehouse", "to_warehouse"]
    ordering = ["-created_at"]

    def perform_create(self, serializer):
        number = generate_order_number("TRF")
        serializer.save(
            tenant=self.request.tenant,
            transfer_number=number,
            created_by=self.request.user,
        )

    @extend_schema(tags=["inventory"])
    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        """Move transfer to IN_TRANSIT and deduct stock from source warehouse."""
        transfer = self.get_object()
        if transfer.status != StockTransfer.Status.DRAFT:
            return Response(
                {"success": False, "error": {"message": "Only DRAFT transfers can be confirmed."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        for item in transfer.items.all():
            StockService.reserve_stock(
                tenant=request.tenant,
                product=item.product,
                variant=item.variant,
                warehouse=transfer.from_warehouse,
                quantity=item.quantity_requested,
            )

        transfer.status = StockTransfer.Status.IN_TRANSIT
        transfer.shipped_date = timezone.now().date()
        transfer.save(update_fields=["status", "shipped_date", "updated_at"])

        return Response({"success": True, "message": "Transfer confirmed and in transit."})

    @extend_schema(tags=["inventory"])
    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        """Mark transfer received. Adjusts stock on both ends."""
        transfer = self.get_object()
        if transfer.status != StockTransfer.Status.IN_TRANSIT:
            return Response(
                {"success": False, "error": {"message": "Only IN_TRANSIT transfers can be received."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        received_items = request.data.get("items", [])
        qty_map = {str(item["item_id"]): Decimal(str(item["quantity_received"])) for item in received_items}

        for item in transfer.items.all():
            qty = qty_map.get(str(item.id), item.quantity_requested)

            # Release reservation and deduct from source
            StockService.release_reservation(
                tenant=request.tenant,
                product=item.product,
                variant=item.variant,
                warehouse=transfer.from_warehouse,
                quantity=item.quantity_requested,
            )
            StockService.transfer_stock(
                tenant=request.tenant,
                product=item.product,
                variant=item.variant,
                from_warehouse=transfer.from_warehouse,
                to_warehouse=transfer.to_warehouse,
                quantity=qty,
                performed_by=request.user,
                reference_id=transfer.id,
                reference_number=transfer.transfer_number,
            )
            item.quantity_received = qty
            item.save(update_fields=["quantity_received"])

        transfer.status = StockTransfer.Status.RECEIVED
        transfer.received_date = timezone.now().date()
        transfer.received_by = request.user
        transfer.save(update_fields=["status", "received_date", "received_by", "updated_at"])

        return Response({"success": True, "message": "Transfer received and stock updated."})

    @extend_schema(tags=["inventory"])
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        transfer = self.get_object()
        if transfer.status == StockTransfer.Status.RECEIVED:
            return Response(
                {"success": False, "error": {"message": "Received transfers cannot be cancelled."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if transfer.status == StockTransfer.Status.IN_TRANSIT:
            for item in transfer.items.all():
                StockService.release_reservation(
                    tenant=request.tenant,
                    product=item.product,
                    variant=item.variant,
                    warehouse=transfer.from_warehouse,
                    quantity=item.quantity_requested,
                )

        transfer.status = StockTransfer.Status.CANCELLED
        transfer.save(update_fields=["status", "updated_at"])
        return Response({"success": True, "message": "Transfer cancelled."})


class BatchLotViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    """
    Batch/lot tracking.
    GET  /api/v1/inventory/batches/
    GET  /api/v1/inventory/batches/expiring_soon/
    """
    queryset = BatchLot.objects.select_related("product", "warehouse")
    serializer_class = BatchLotSerializer
    permission_classes = [IsAuthenticated, TenantPermission, CanViewInventory]
    filterset_fields = ["product", "warehouse"]
    search_fields = ["batch_number", "product__name", "product__sku"]
    ordering = ["expiry_date"]

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    @extend_schema(tags=["inventory"])
    @action(detail=False, methods=["get"])
    def expiring_soon(self, request):
        """GET /batches/expiring_soon/?days=30"""
        days = int(request.query_params.get("days", 30))
        cutoff = timezone.now().date() + timezone.timedelta(days=days)
        qs = self.get_queryset().filter(
            expiry_date__lte=cutoff,
            expiry_date__gte=timezone.now().date(),
            quantity__gt=0,
        ).order_by("expiry_date")
        return Response({"success": True, "data": BatchLotSerializer(qs, many=True).data})


class SerialNumberViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    """
    Serial number tracking.
    GET  /api/v1/inventory/serials/
    GET  /api/v1/inventory/serials/search/?q=SN1234
    """
    queryset = SerialNumber.objects.select_related("product", "warehouse")
    serializer_class = SerialNumberSerializer
    permission_classes = [IsAuthenticated, TenantPermission, CanViewInventory]
    filterset_fields = ["status", "product", "warehouse"]
    search_fields = ["serial_number", "product__name", "product__sku"]

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    @extend_schema(tags=["inventory"])
    @action(detail=False, methods=["get"])
    def search(self, request):
        """Quick serial number lookup. GET /serials/search/?q=SN123"""
        q = request.query_params.get("q", "").strip()
        if not q:
            return Response({"success": False, "error": {"message": "q param required."}}, status=400)
        qs = self.get_queryset().filter(serial_number__icontains=q)
        return Response({"success": True, "data": SerialNumberSerializer(qs, many=True).data})
