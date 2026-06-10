from rest_framework import serializers
from .models import StockLevel, StockMovement, BatchLot, SerialNumber, StockTransfer, StockTransferItem


class StockLevelSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    product_barcode = serializers.CharField(source="product.barcode", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    warehouse_code = serializers.CharField(source="warehouse.code", read_only=True)
    variant_name = serializers.CharField(source="variant.name", read_only=True)
    available_quantity = serializers.DecimalField(
        max_digits=15, decimal_places=3, read_only=True
    )
    is_low_stock = serializers.BooleanField(read_only=True)
    is_out_of_stock = serializers.BooleanField(read_only=True)
    stock_value = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    reorder_point = serializers.DecimalField(
        source="product.reorder_point", max_digits=15, decimal_places=3, read_only=True
    )

    class Meta:
        model = StockLevel
        fields = [
            "id", "product", "product_name", "product_sku", "product_barcode",
            "variant", "variant_name",
            "warehouse", "warehouse_name", "warehouse_code",
            "quantity", "reserved_quantity", "available_quantity",
            "average_cost", "stock_value",
            "is_low_stock", "is_out_of_stock",
            "reorder_point", "updated_at",
        ]
        read_only_fields = ["id", "updated_at"]


class StockMovementSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    performed_by_name = serializers.CharField(source="performed_by.get_full_name", read_only=True)
    movement_type_display = serializers.CharField(source="get_movement_type_display", read_only=True)

    class Meta:
        model = StockMovement
        fields = [
            "id", "product", "product_name", "product_sku",
            "variant", "warehouse", "warehouse_name",
            "movement_type", "movement_type_display",
            "quantity", "quantity_before", "quantity_after",
            "unit_cost", "total_cost",
            "reference_type", "reference_id", "reference_number",
            "batch_number", "serial_number", "expiry_date",
            "notes", "performed_by", "performed_by_name",
            "created_at",
        ]
        read_only_fields = fields  # movements are immutable


class StockAdjustSerializer(serializers.Serializer):
    """Input for manual stock adjustments."""
    product = serializers.UUIDField()
    variant = serializers.UUIDField(required=False, allow_null=True)
    warehouse = serializers.UUIDField()
    quantity_delta = serializers.DecimalField(max_digits=15, decimal_places=3)
    unit_cost = serializers.DecimalField(max_digits=15, decimal_places=4, default=0)
    movement_type = serializers.ChoiceField(choices=[
        ("adjustment_in", "Adjustment In"),
        ("adjustment_out", "Adjustment Out"),
        ("damage", "Damage/Write-off"),
        ("opening", "Opening Stock"),
    ], default="adjustment_in")
    batch_number = serializers.CharField(required=False, allow_blank=True, default="")
    serial_number = serializers.CharField(required=False, allow_blank=True, default="")
    expiry_date = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, data):
        from apps.products.models import Product
        from apps.warehouses.models import Warehouse
        from apps.products.models import ProductVariant
        request = self.context.get("request")
        tenant = request.tenant

        try:
            data["product"] = Product.objects.get(id=data["product"], tenant=tenant)
        except Product.DoesNotExist:
            raise serializers.ValidationError({"product": "Product not found."})

        try:
            data["warehouse"] = Warehouse.objects.get(id=data["warehouse"], tenant=tenant)
        except Warehouse.DoesNotExist:
            raise serializers.ValidationError({"warehouse": "Warehouse not found."})

        if data.get("variant"):
            try:
                data["variant"] = ProductVariant.objects.get(id=data["variant"], tenant=tenant)
            except ProductVariant.DoesNotExist:
                raise serializers.ValidationError({"variant": "Variant not found."})

        return data


class BatchLotSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    days_to_expiry = serializers.IntegerField(read_only=True)

    class Meta:
        model = BatchLot
        exclude = ["tenant"]
        read_only_fields = ["id", "created_at", "updated_at"]


class SerialNumberSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)

    class Meta:
        model = SerialNumber
        exclude = ["tenant"]
        read_only_fields = ["id", "created_at", "updated_at"]


class StockTransferItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = StockTransferItem
        exclude = ["tenant", "transfer"]
        read_only_fields = ["id", "created_at", "updated_at"]


class StockTransferSerializer(serializers.ModelSerializer):
    items = StockTransferItemSerializer(many=True)
    from_warehouse_name = serializers.CharField(source="from_warehouse.name", read_only=True)
    to_warehouse_name = serializers.CharField(source="to_warehouse.name", read_only=True)
    created_by_name = serializers.CharField(source="created_by.get_full_name", read_only=True)

    class Meta:
        model = StockTransfer
        exclude = ["tenant"]
        read_only_fields = ["id", "transfer_number", "created_at", "updated_at"]
