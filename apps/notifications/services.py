import logging
from django.db import transaction

logger = logging.getLogger("inventra.notifications")


class NotificationService:

    @classmethod
    def create(
        cls,
        *,
        tenant,
        title: str,
        body: str,
        notification_type: str = "system",
        reference_id: str = "",
        reference_type: str = "",
        recipient=None,
    ):
        """
        Create a notification and push it via WebSocket.
        recipient=None → delivered to all owner/manager role members of the tenant.
        """
        from apps.notifications.models import Notification
        from apps.accounts.models import TenantMembership

        recipients = []
        if recipient:
            recipients = [recipient]
        else:
            # Broadcast to owners and managers
            memberships = TenantMembership.objects.filter(
                tenant=tenant,
                is_active=True,
                role__name__in=["owner", "manager"],
            ).select_related("user")
            recipients = [m.user for m in memberships]

        notifications = []
        for user in recipients:
            notification = Notification.objects.create(
                tenant=tenant,
                title=title,
                body=body,
                notification_type=notification_type,
                reference_id=reference_id,
                reference_type=reference_type,
                recipient=user,
            )
            notifications.append(notification)

            # Push via WebSocket (non-blocking)
            cls._push_ws(tenant, user, notification)

        logger.info(
            f"[NOTIFY] {notification_type} → {len(recipients)} recipients | Tenant: {tenant.slug}"
        )
        return notifications

    @staticmethod
    def _push_ws(tenant, user, notification):
        """Push notification to user's WebSocket channel."""
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync

            channel_layer = get_channel_layer()
            group_name = f"user_{user.id}"

            async_to_sync(channel_layer.group_send)(
                group_name,
                {
                    "type": "notification.send",
                    "data": {
                        "id": str(notification.id),
                        "title": notification.title,
                        "body": notification.body,
                        "type": notification.notification_type,
                        "reference_id": notification.reference_id,
                        "created_at": notification.created_at.isoformat(),
                    },
                },
            )
        except Exception as e:
            logger.warning(f"WebSocket push failed: {e}")

    @classmethod
    def mark_all_read(cls, tenant, user):
        from apps.notifications.models import Notification
        from django.utils import timezone
        Notification.objects.filter(
            tenant=tenant, recipient=user, is_read=False
        ).update(is_read=True, read_at=timezone.now())

    @classmethod
    def unread_count(cls, tenant, user) -> int:
        from apps.notifications.models import Notification
        return Notification.objects.filter(
            tenant=tenant, recipient=user, is_read=False
        ).count()
