from decimal import Decimal
from rest_framework import serializers
from .models import Customer, SalesOrder, SalesOrderItem, Payment, POSSession


class CustomerSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = Customer
        exclude = ["tenant"]
        read_only_fields = ["id", "outstanding_balance", "loyalty_points", "created_at", "updated_at"]


class SalesOrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    variant_name = serializers.CharField(source="variant.name", read_only=True)
    profit = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)

    class Meta:
        model = SalesOrderItem
        exclude = ["tenant", "order"]
        read_only_fields = ["id", "line_total", "discount_amount", "created_at", "updated_at"]


class SalesOrderItemWriteSerializer(serializers.Serializer):
    product = serializers.UUIDField()
    variant = serializers.UUIDField(required=False, allow_null=True)
    quantity = serializers.DecimalField(max_digits=15, decimal_places=3, min_value=Decimal("0.001"))
    unit_price = serializers.DecimalField(max_digits=15, decimal_places=2, min_value=Decimal("0"))
    cost_price = serializers.DecimalField(max_digits=15, decimal_places=2, default=0)
    discount_pct = serializers.DecimalField(max_digits=5, decimal_places=2, default=0)
    tax_rate = serializers.DecimalField(max_digits=5, decimal_places=2, default=0)

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


class PaymentSerializer(serializers.ModelSerializer):
    received_by_name = serializers.CharField(source="received_by.get_full_name", read_only=True)

    class Meta:
        model = Payment
        exclude = ["tenant"]
        read_only_fields = ["id", "created_at", "updated_at"]


class SalesOrderListSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.full_name", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    payment_status_display = serializers.CharField(source="get_payment_status_display", read_only=True)
    item_count = serializers.SerializerMethodField()

    class Meta:
        model = SalesOrder
        fields = [
            "id", "order_number", "customer", "customer_name",
            "warehouse", "warehouse_name", "status", "status_display",
            "payment_status", "payment_status_display",
            "total_amount", "amount_paid", "amount_due",
            "item_count", "sale_channel", "order_date", "created_at",
        ]

    def get_item_count(self, obj):
        return obj.items.filter(is_active=True).count()


class SalesOrderDetailSerializer(serializers.ModelSerializer):
    items = SalesOrderItemSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    customer_name = serializers.CharField(source="customer.full_name", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    created_by_name = serializers.CharField(source="created_by.get_full_name", read_only=True)

    class Meta:
        model = SalesOrder
        exclude = ["tenant"]
        read_only_fields = [
            "id", "order_number", "subtotal", "discount_amount",
            "tax_amount", "total_amount", "amount_due",
            "payment_status", "created_at", "updated_at",
        ]


class CreateSalesOrderSerializer(serializers.Serializer):
    customer = serializers.UUIDField(required=False, allow_null=True)
    warehouse = serializers.UUIDField()
    items = SalesOrderItemWriteSerializer(many=True, min_length=1)
    sale_channel = serializers.ChoiceField(
        choices=SalesOrder.SaleChannel.choices, default="walk_in"
    )
    discount_type = serializers.ChoiceField(
        choices=[("fixed", "Fixed"), ("percent", "Percent")], default="fixed"
    )
    discount_value = serializers.DecimalField(max_digits=15, decimal_places=2, default=0)
    shipping_amount = serializers.DecimalField(max_digits=15, decimal_places=2, default=0)
    due_date = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    pos_session = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, data):
        from apps.warehouses.models import Warehouse
        from apps.customers.models import Customer  # noqa
        request = self.context.get("request")
        tenant = request.tenant

        try:
            data["warehouse"] = Warehouse.objects.get(id=data["warehouse"], tenant=tenant)
        except Warehouse.DoesNotExist:
            raise serializers.ValidationError({"warehouse": "Warehouse not found."})

        if data.get("customer"):
            try:
                data["customer"] = Customer.objects.get(id=data["customer"], tenant=tenant)
            except Exception:
                data["customer"] = None

        if data.get("pos_session"):
            from apps.sales.models import POSSession
            try:
                data["pos_session"] = POSSession.objects.get(
                    id=data["pos_session"], tenant=tenant, status="open"
                )
            except POSSession.DoesNotExist:
                raise serializers.ValidationError({"pos_session": "Active POS session not found."})
        return data


class RecordPaymentSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=15, decimal_places=2, min_value=Decimal("0.01"))
    method = serializers.ChoiceField(choices=Payment.Method.choices)
    reference = serializers.CharField(required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class POSSessionSerializer(serializers.ModelSerializer):
    cashier_name = serializers.CharField(source="cashier.get_full_name", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    total_sales = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    cash_variance = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)

    class Meta:
        model = POSSession
        exclude = ["tenant"]
        read_only_fields = [
            "id", "status", "expected_cash",
            "opened_at", "closed_at", "created_at", "updated_at",
        ]
