from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.routers import DefaultRouter
from core.permissions import TenantPermission, CanManageSettings
from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.get_full_name", read_only=True)

    class Meta:
        model = AuditLog
        fields = [
            "id", "user", "user_name", "action", "model_name",
            "object_id", "object_repr", "changes",
            "ip_address", "endpoint", "method", "response_status",
            "created_at",
        ]
        read_only_fields = fields


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticated, TenantPermission, CanManageSettings]
    filterset_fields = ["action", "model_name", "user"]
    search_fields = ["object_repr", "endpoint", "model_name"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return AuditLog.objects.filter(
            tenant=self.request.tenant
        ).select_related("user").order_by("-created_at")


router = DefaultRouter()
router.register("logs", AuditLogViewSet, basename="audit-logs")

urlpatterns = router.urls
