"""
WebSocket consumer for real-time notifications.
Clients connect to: ws://app.inventra.io/ws/notifications/?token=<jwt>
"""
import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

logger = logging.getLogger("inventra.notifications.ws")


class NotificationConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.close(code=4001)
            return

        self.user = user
        self.group_name = f"user_{user.id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # Send unread count on connect
        count = await self._get_unread_count()
        await self.send(text_data=json.dumps({
            "type": "connection_established",
            "unread_count": count,
        }))
        logger.info(f"[WS] Connected: {user.email}")

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        logger.info(f"[WS] Disconnected: {getattr(self, 'user', 'unknown')}")

    async def receive(self, text_data):
        """Handle messages from client (e.g. mark-read commands)."""
        try:
            data = json.loads(text_data)
            action = data.get("action")
            if action == "mark_read":
                notification_id = data.get("notification_id")
                if notification_id:
                    await self._mark_notification_read(notification_id)
            elif action == "mark_all_read":
                await self._mark_all_read()
                count = await self._get_unread_count()
                await self.send(text_data=json.dumps({
                    "type": "unread_count",
                    "count": count,
                }))
        except json.JSONDecodeError:
            pass

    async def notification_send(self, event):
        """Called by channel layer when a notification is pushed."""
        await self.send(text_data=json.dumps({
            "type": "notification",
            **event["data"],
        }))

    @database_sync_to_async
    def _get_unread_count(self):
        from apps.notifications.models import Notification
        return Notification.objects.filter(
            recipient=self.user, is_read=False
        ).count()

    @database_sync_to_async
    def _mark_notification_read(self, notification_id):
        from apps.notifications.models import Notification
        Notification.objects.filter(
            id=notification_id, recipient=self.user
        ).update(is_read=True)

    @database_sync_to_async
    def _mark_all_read(self):
        from apps.notifications.models import Notification
        from django.utils import timezone
        Notification.objects.filter(
            recipient=self.user, is_read=False
        ).update(is_read=True, read_at=timezone.now())
