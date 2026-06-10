from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from core.permissions import TenantPermission, CanManageSettings
from core.mixins import TenantQuerysetMixin, TenantCreateMixin
from .models import Warehouse, Branch


# ── Serializers ──────────────────────────────────────────────────────────────

class WarehouseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Warehouse
        exclude = ["tenant"]
        read_only_fields = ["id", "created_at", "updated_at"]


class BranchSerializer(serializers.ModelSerializer):
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)

    class Meta:
        model = Branch
        exclude = ["tenant"]
        read_only_fields = ["id", "created_at", "updated_at"]


# ── ViewSets ─────────────────────────────────────────────────────────────────

class WarehouseViewSet(TenantQuerysetMixin, TenantCreateMixin, viewsets.ModelViewSet):
    serializer_class = WarehouseSerializer
    permission_classes = [IsAuthenticated, TenantPermission]
    queryset = Warehouse.objects.all()
    search_fields = ["name", "code", "city"]
    filterset_fields = ["is_active", "is_default"]

    def perform_create(self, serializer):
        from apps.tenants.services import TenantService
        count = Warehouse.objects.filter(tenant=self.request.tenant).count()
        TenantService.check_plan_limit(self.request.tenant, "warehouses", count)
        serializer.save(tenant=self.request.tenant)


class BranchViewSet(TenantQuerysetMixin, TenantCreateMixin, viewsets.ModelViewSet):
    serializer_class = BranchSerializer
    permission_classes = [IsAuthenticated, TenantPermission]
    queryset = Branch.objects.all()
    search_fields = ["name", "code"]


# ── URLs ─────────────────────────────────────────────────────────────────────

router = DefaultRouter()
router.register("warehouses", WarehouseViewSet, basename="warehouses")
router.register("branches", BranchViewSet, basename="branches")

urlpatterns = router.urls
