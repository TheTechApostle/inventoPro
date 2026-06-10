"""
Reusable ViewSet mixins.
Import and compose as needed in app views.
"""
from rest_framework.response import Response
from rest_framework import status


class TenantQuerysetMixin:
    """
    Auto-scopes get_queryset() to request.tenant.
    Must be first in MRO: class MyView(TenantQuerysetMixin, ModelViewSet).
    """
    def get_queryset(self):
        qs = super().get_queryset()
        if hasattr(self.request, "tenant") and self.request.tenant:
            return qs.filter(tenant=self.request.tenant)
        return qs.none()


class SuccessResponseMixin:
    """
    Wraps successful create/update responses in a consistent envelope.
    """
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(
            {"success": True, "data": serializer.data},
            status=status.HTTP_201_CREATED,
            headers=headers,
        )

    def perform_create(self, serializer):
        return serializer.save()

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response({"success": True, "data": serializer.data})

    def perform_update(self, serializer):
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.soft_delete()
        return Response({"success": True, "message": "Deleted successfully."}, status=status.HTTP_200_OK)


class TenantCreateMixin:
    """
    Automatically injects tenant into serializer.save().
    """
    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class AuditMixin:
    """
    Injects performed_by / created_by into serializer.save().
    """
    def perform_create(self, serializer):
        kwargs = {"created_by": self.request.user}
        if hasattr(self, "request") and hasattr(self.request, "tenant"):
            kwargs["tenant"] = self.request.tenant
        serializer.save(**kwargs)
