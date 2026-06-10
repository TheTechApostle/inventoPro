from rest_framework import serializers


class BaseModelSerializer(serializers.ModelSerializer):
    """
    Base serializer.
    Adds read-only id, created_at, updated_at to all serializers.
    """
    id = serializers.UUIDField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    class Meta:
        abstract = True
        read_only_fields = ["id", "created_at", "updated_at", "tenant"]


class TenantAwareSerializer(BaseModelSerializer):
    """
    Excludes tenant from serialized output (tenant is implicit from context).
    """
    class Meta(BaseModelSerializer.Meta):
        abstract = True
        exclude_fields = ["tenant"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Remove tenant field from output
        self.fields.pop("tenant", None)
