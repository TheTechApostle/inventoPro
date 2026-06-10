"""
Audit app.
Tracks all create/update/delete actions across the platform.
Stores who did what, when, on which object.
"""
import json
import logging
from django.db import models
from django.utils import timezone
from core.models import BaseModel

logger = logging.getLogger("inventra.audit")


class AuditLog(BaseModel):
    """Immutable audit trail record."""

    class Action(models.TextChoices):
        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        DELETE = "delete", "Delete"
        LOGIN = "login", "Login"
        LOGOUT = "logout", "Logout"
        EXPORT = "export", "Export"
        IMPORT = "import", "Import"
        APPROVE = "approve", "Approve"
        REJECT = "reject", "Reject"

    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.CASCADE,
        null=True, blank=True, related_name="audit_logs"
    )
    user = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="audit_logs"
    )
    action = models.CharField(max_length=20, choices=Action.choices, db_index=True)
    model_name = models.CharField(max_length=100, db_index=True)
    object_id = models.CharField(max_length=100, blank=True, db_index=True)
    object_repr = models.CharField(max_length=300, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    endpoint = models.CharField(max_length=500, blank=True)
    method = models.CharField(max_length=10, blank=True)
    response_status = models.PositiveIntegerField(null=True, blank=True)
    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "audit_logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "user", "-created_at"]),
            models.Index(fields=["tenant", "model_name", "-created_at"]),
            models.Index(fields=["tenant", "action", "-created_at"]),
        ]

    def __str__(self):
        return f"[{self.action}] {self.model_name}:{self.object_id} by {self.user}"


# ── Middleware ────────────────────────────────────────────────────────────────

AUDIT_EXEMPT_PATHS = [
    "/admin/",
    "/api/v1/schema/",
    "/api/v1/docs/",
    "/api/v1/analytics/",  # read-only, high volume
    "/api/v1/notifications/",
]

AUDITED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class AuditMiddleware:
    """
    Lightweight request-level audit logging.
    Only logs mutating requests (POST/PUT/PATCH/DELETE).
    Heavy audit (field-level changes) is done at service layer.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if (
            request.method in AUDITED_METHODS
            and not any(request.path.startswith(p) for p in AUDIT_EXEMPT_PATHS)
            and hasattr(request, "user")
            and request.user.is_authenticated
        ):
            try:
                self._log(request, response)
            except Exception as e:
                logger.warning(f"Audit log failed: {e}")

        return response

    def _log(self, request, response):
        from apps.audit.models import AuditLog
        ip = self._get_ip(request)
        AuditLog.objects.create(
            tenant=getattr(request, "tenant", None),
            user=request.user,
            action=self._method_to_action(request.method),
            model_name="",
            endpoint=request.path[:500],
            method=request.method,
            ip_address=ip,
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
            response_status=response.status_code,
        )

    @staticmethod
    def _method_to_action(method: str) -> str:
        return {
            "POST": "create",
            "PUT": "update",
            "PATCH": "update",
            "DELETE": "delete",
        }.get(method, "update")

    @staticmethod
    def _get_ip(request) -> str:
        x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded:
            return x_forwarded.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "")


# ── Views & URLs ──────────────────────────────────────────────────────────────

from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from core.permissions import TenantPermission, CanManageSettings
from django.urls import path, include


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
