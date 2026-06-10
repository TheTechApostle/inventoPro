"""
Sales views.
Orders, customers, payments, POS sessions.
"""
import logging
from decimal import Decimal
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema
from core.permissions import (
    TenantPermission, CanViewSales, CanManageSales, CanVoidSales
)
from core.mixins import TenantQuerysetMixin
from .models import Customer, SalesOrder, Payment, POSSession
from .serializers import (
    CustomerSerializer,
    SalesOrderListSerializer, SalesOrderDetailSerializer,
    CreateSalesOrderSerializer, RecordPaymentSerializer,
    POSSessionSerializer,
)
from .services import SalesService

logger = logging.getLogger("inventra.sales")


class CustomerViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    """
    Full CRUD for customers.
    GET  /api/v1/sales/customers/
    GET  /api/v1/sales/customers/{id}/
    GET  /api/v1/sales/customers/{id}/orders/
    """
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    permission_classes = [IsAuthenticated, TenantPermission, CanViewSales]
    search_fields = ["first_name", "last_name", "email", "phone", "company_name"]
    filterset_fields = ["is_active", "customer_group"]
    ordering_fields = ["first_name", "outstanding_balance", "created_at"]

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    @extend_schema(tags=["sales"])
    @action(detail=True, methods=["get"])
    def orders(self, request, pk=None):
        """GET /customers/{id}/orders/"""
        customer = self.get_object()
        orders = SalesOrder.objects.filter(
            tenant=request.tenant, customer=customer
        ).order_by("-created_at")
        page = self.paginate_queryset(orders)
        if page is not None:
            return self.get_paginated_response(SalesOrderListSerializer(page, many=True).data)
        return Response({"success": True, "data": SalesOrderListSerializer(orders, many=True).data})

    @extend_schema(tags=["sales"])
    @action(detail=True, methods=["get"])
    def statement(self, request, pk=None):
        """GET /customers/{id}/statement/ — outstanding balance summary."""
        customer = self.get_object()
        from core.utils import parse_date_range
        date_from, date_to = parse_date_range(request)

        orders = SalesOrder.objects.filter(
            tenant=request.tenant, customer=customer,
            created_at__gte=date_from, created_at__lte=date_to,
        )
        from django.db.models import Sum
        summary = orders.aggregate(
            total_invoiced=Sum("total_amount"),
            total_paid=Sum("amount_paid"),
            total_due=Sum("amount_due"),
        )
        return Response({
            "success": True,
            "data": {
                "customer": CustomerSerializer(customer).data,
                "period": {"from": date_from, "to": date_to},
                **{k: v or 0 for k, v in summary.items()},
                "order_count": orders.count(),
            }
        })


class SalesOrderViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    """
    Sales order management.
    POST /api/v1/sales/orders/              — create
    GET  /api/v1/sales/orders/{id}/         — retrieve
    POST /api/v1/sales/orders/{id}/confirm/ — confirm + deduct stock
    POST /api/v1/sales/orders/{id}/pay/     — record payment
    POST /api/v1/sales/orders/{id}/cancel/  — cancel
    POST /api/v1/sales/orders/{id}/deliver/ — mark delivered
    GET  /api/v1/sales/orders/today/        — today's orders
    """
    queryset = SalesOrder.objects.select_related(
        "customer", "warehouse", "created_by", "pos_session"
    ).prefetch_related("items", "payments")
    permission_classes = [IsAuthenticated, TenantPermission, CanViewSales]
    filterset_fields = [
        "status", "payment_status", "sale_channel",
        "warehouse", "customer",
    ]
    search_fields = ["order_number", "customer__first_name", "customer__phone"]
    ordering_fields = ["order_date", "total_amount", "created_at"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        if self.action == "create":
            return CreateSalesOrderSerializer
        if self.action == "list":
            return SalesOrderListSerializer
        return SalesOrderDetailSerializer

    @extend_schema(tags=["sales"])
    def create(self, request, *args, **kwargs):
        """Create a new sales order (DRAFT state)."""
        serializer = CreateSalesOrderSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        order = SalesService.create_order(
            tenant=request.tenant,
            warehouse=d["warehouse"],
            created_by=request.user,
            customer=d.get("customer"),
            items=d["items"],
            sale_channel=d.get("sale_channel", "walk_in"),
            discount_type=d.get("discount_type", "fixed"),
            discount_value=d.get("discount_value", Decimal("0")),
            shipping_amount=d.get("shipping_amount", Decimal("0")),
            due_date=d.get("due_date"),
            notes=d.get("notes", ""),
            pos_session=d.get("pos_session"),
        )
        return Response(
            {"success": True, "data": SalesOrderDetailSerializer(order).data},
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(tags=["sales"])
    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        """Confirm order — deducts stock from warehouse."""
        order = self.get_object()
        order = SalesService.confirm_order(order=order, confirmed_by=request.user)
        return Response({"success": True, "data": SalesOrderDetailSerializer(order).data})

    @extend_schema(tags=["sales"])
    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        """Record a payment against this order."""
        order = self.get_object()
        serializer = RecordPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        payment = SalesService.record_payment(
            order=order,
            amount=d["amount"],
            method=d["method"],
            received_by=request.user,
            reference=d.get("reference", ""),
            notes=d.get("notes", ""),
        )
        return Response({
            "success": True,
            "message": f"Payment of {payment.amount} recorded.",
            "data": SalesOrderDetailSerializer(order).data,
        })

    @extend_schema(tags=["sales"])
    @action(detail=True, methods=["post"],
            permission_classes=[IsAuthenticated, TenantPermission, CanVoidSales])
    def cancel(self, request, pk=None):
        """Cancel an order. Reverses stock if already confirmed."""
        order = self.get_object()
        reason = request.data.get("reason", "")
        order = SalesService.cancel_order(order=order, cancelled_by=request.user, reason=reason)
        return Response({"success": True, "message": "Order cancelled.", "data": SalesOrderDetailSerializer(order).data})

    @extend_schema(tags=["sales"])
    @action(detail=True, methods=["post"])
    def deliver(self, request, pk=None):
        """Mark order as delivered."""
        order = self.get_object()
        if order.status not in ("confirmed", "packed", "shipped"):
            return Response(
                {"success": False, "error": {"message": f"Cannot deliver a {order.status} order."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        order.status = "delivered"
        order.delivered_at = timezone.now()
        order.save(update_fields=["status", "delivered_at", "updated_at"])
        return Response({"success": True, "data": SalesOrderDetailSerializer(order).data})

    @extend_schema(tags=["sales"])
    @action(detail=False, methods=["get"])
    def today(self, request):
        """GET /orders/today/ — today's orders."""
        today = timezone.now().date()
        qs = self.get_queryset().filter(order_date=today)
        from django.db.models import Sum, Count
        summary = qs.aggregate(
            total_revenue=Sum("total_amount"),
            total_paid=Sum("amount_paid"),
            order_count=Count("id"),
        )
        page = self.paginate_queryset(qs)
        data = SalesOrderListSerializer(page or qs, many=True).data
        resp = {
            "success": True,
            "summary": {k: v or 0 for k, v in summary.items()},
            "results": data,
        }
        if page is not None:
            return self.get_paginated_response(data)
        return Response(resp)


class POSSessionViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    """
    POS session management.
    POST /api/v1/sales/pos/open/
    POST /api/v1/sales/pos/{id}/close/
    GET  /api/v1/sales/pos/current/
    """
    queryset = POSSession.objects.select_related("cashier", "warehouse")
    serializer_class = POSSessionSerializer
    permission_classes = [IsAuthenticated, TenantPermission, CanManageSales]
    filterset_fields = ["status", "warehouse"]
    ordering = ["-opened_at"]

    @extend_schema(tags=["sales"])
    @action(detail=False, methods=["post"])
    def open(self, request):
        """POST /pos/open/"""
        from apps.warehouses.models import Warehouse
        warehouse_id = request.data.get("warehouse")
        opening_float = Decimal(str(request.data.get("opening_float", "0")))

        try:
            warehouse = Warehouse.objects.get(id=warehouse_id, tenant=request.tenant)
        except Warehouse.DoesNotExist:
            return Response({"success": False, "error": {"message": "Warehouse not found."}}, status=400)

        session = SalesService.open_pos_session(
            tenant=request.tenant,
            warehouse=warehouse,
            cashier=request.user,
            opening_float=opening_float,
        )
        return Response(
            {"success": True, "data": POSSessionSerializer(session).data},
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(tags=["sales"])
    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        """POST /pos/{id}/close/"""
        session = self.get_object()
        if session.status != "open":
            return Response({"success": False, "error": {"message": "Session is not open."}}, status=400)

        closing_float = Decimal(str(request.data.get("closing_float", "0")))
        notes = request.data.get("notes", "")
        session = SalesService.close_pos_session(
            session=session, closing_float=closing_float, notes=notes
        )
        return Response({"success": True, "data": POSSessionSerializer(session).data})

    @extend_schema(tags=["sales"])
    @action(detail=False, methods=["get"])
    def current(self, request):
        """GET /pos/current/ — current user's open session."""
        session = POSSession.objects.filter(
            tenant=request.tenant,
            cashier=request.user,
            status="open",
        ).first()
        if not session:
            return Response({"success": True, "data": None})
        return Response({"success": True, "data": POSSessionSerializer(session).data})
