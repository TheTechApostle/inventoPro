from rest_framework import generics, viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from drf_spectacular.utils import extend_schema, extend_schema_view
from core.permissions import TenantPermission, CanManageSettings
from .models import Tenant, TenantSettings
from .serializers import (
    TenantSerializer,
    TenantRegisterSerializer,
    TenantUpdateSerializer,
    TenantSettingsSerializer,
)


class TenantRegisterView(generics.CreateAPIView):
    """
    Public endpoint: register a new tenant + owner account.
    POST /api/v1/tenants/register/
    """
    serializer_class = TenantRegisterSerializer
    permission_classes = [AllowAny]

    @extend_schema(tags=["tenants"])
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenant, user = serializer.save()

        # Auto-login: return JWT tokens
        from rest_framework_simplejwt.tokens import RefreshToken
        from apps.accounts.models import TenantMembership
        membership = TenantMembership.objects.get(tenant=tenant, user=user)
        refresh = _build_token(user, tenant, membership)

        return Response(
            {
                "success": True,
                "message": "Account created! Welcome to Inventra.",
                "tenant": TenantSerializer(tenant).data,
                "tokens": {
                    "access": str(refresh.access_token),
                    "refresh": str(refresh),
                },
            },
            status=status.HTTP_201_CREATED,
        )


class TenantDetailView(generics.RetrieveUpdateAPIView):
    """
    GET  /api/v1/tenants/me/  — current tenant info
    PUT  /api/v1/tenants/me/  — update branding/settings
    """
    permission_classes = [IsAuthenticated, TenantPermission]

    def get_object(self):
        return self.request.tenant

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return TenantUpdateSerializer
        return TenantSerializer

    @extend_schema(tags=["tenants"])
    def get(self, request, *args, **kwargs):
        tenant = self.get_object()
        return Response({"success": True, "data": TenantSerializer(tenant).data})

    @extend_schema(tags=["tenants"])
    def patch(self, request, *args, **kwargs):
        tenant = self.get_object()
        serializer = TenantUpdateSerializer(tenant, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"success": True, "data": TenantSerializer(tenant).data})


class TenantSettingsView(generics.RetrieveUpdateAPIView):
    """GET/PATCH /api/v1/tenants/settings/"""
    permission_classes = [IsAuthenticated, TenantPermission, CanManageSettings]
    serializer_class = TenantSettingsSerializer

    def get_object(self):
        settings, _ = TenantSettings.objects.get_or_create(tenant=self.request.tenant)
        return settings

    @extend_schema(tags=["tenants"])
    def get(self, request, *args, **kwargs):
        return Response({"success": True, "data": self.get_serializer(self.get_object()).data})

    @extend_schema(tags=["tenants"])
    def patch(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"success": True, "data": serializer.data})


def _build_token(user, tenant, membership):
    """Build JWT with embedded tenant context."""
    from rest_framework_simplejwt.tokens import RefreshToken
    refresh = RefreshToken.for_user(user)
    refresh["tenant_id"] = str(tenant.id)
    refresh["tenant_slug"] = tenant.slug
    refresh["role"] = membership.role.name
    refresh["permissions"] = membership.role.permissions
    return refresh
