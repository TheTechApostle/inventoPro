from rest_framework import serializers, viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.routers import DefaultRouter
from core.permissions import TenantPermission
from core.mixins import TenantQuerysetMixin
from .models import Notification
from .services import NotificationService


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        exclude = ["tenant", "recipient"]
        read_only_fields = ["id", "is_read", "read_at", "created_at"]


class NotificationViewSet(TenantQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    """
    GET  /api/v1/notifications/           — list user's notifications
    GET  /api/v1/notifications/unread/    — unread only
    POST /api/v1/notifications/{id}/read/ — mark single read
    POST /api/v1/notifications/read_all/  — mark all read
    GET  /api/v1/notifications/count/     — unread count
    """
    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated, TenantPermission]
    filterset_fields = ["is_read", "notification_type"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return Notification.objects.filter(
            tenant=self.request.tenant,
            recipient=self.request.user,
        ).order_by("-created_at")

    @action(detail=False, methods=["get"])
    def unread(self, request):
        qs = self.get_queryset().filter(is_read=False)
        return Response({"success": True, "data": NotificationSerializer(qs, many=True).data})

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        notification = self.get_object()
        notification.mark_read()
        return Response({"success": True})

    @action(detail=False, methods=["post"], url_path="read_all")
    def read_all(self, request):
        NotificationService.mark_all_read(tenant=request.tenant, user=request.user)
        return Response({"success": True, "message": "All notifications marked as read."})

    @action(detail=False, methods=["get"])
    def count(self, request):
        count = NotificationService.unread_count(tenant=request.tenant, user=request.user)
        return Response({"success": True, "unread_count": count})


router = DefaultRouter()
router.register("", NotificationViewSet, basename="notifications")

urlpatterns = router.urls
