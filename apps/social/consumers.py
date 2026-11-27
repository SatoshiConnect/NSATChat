import json
from datetime import timedelta

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.db import transaction
from django.utils import timezone

from .models import LiveStream, LiveStreamViewer
from .views import _can_join_live


class LiveStreamConsumer(AsyncJsonWebsocketConsumer):
    """Authenticated viewer membership and interaction fan-out for an SFU live room."""

    async def connect(self):
        self.user = self.scope["user"]
        if self.user.is_anonymous:
            await self.close(code=4001)
            return
        self.stream_id = int(self.scope["url_route"]["kwargs"]["stream_id"])
        self.group_name = f"social_live_{self.stream_id}"
        context = await self.join_stream()
        if not context:
            await self.close(code=4404)
            return
        self.is_host = context["is_host"]
        self.joined_viewer = not self.is_host
        if context.get("full"):
            await self.close(code=4409)
            return
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json({"type": "ready", "payload": {"is_host": self.is_host, "viewer_count": context["viewer_count"]}})
        if not self.is_host:
            await self.channel_layer.group_send(self.group_name, {
                "type": "live.event", "event": "viewer_joined",
                "payload": {"viewer_count": context["viewer_count"]},
            })

    async def disconnect(self, close_code):
        if not hasattr(self, "group_name"):
            return
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        if getattr(self, "joined_viewer", False):
            viewer_count = await self.leave_stream()
            await self.channel_layer.group_send(self.group_name, {
                "type": "live.event", "event": "viewer_left",
                "payload": {"viewer_count": viewer_count},
            })

    async def receive_json(self, content, **kwargs):
        if not isinstance(content, dict):
            return
        if len(json.dumps(content, separators=(",", ":"))) > 32_000:
            return
        message_type = content.get("type")
        if message_type == "heartbeat":
            if self.is_host:
                await self.touch_stream()
            else:
                await self.touch_viewer()
            return

    async def live_event(self, event):
        await self.send_json({"type": event["event"], "payload": event["payload"]})

    @database_sync_to_async
    def join_stream(self):
        stream = (
            LiveStream.objects.filter(pk=self.stream_id, status=LiveStream.LIVE)
            .select_related("host", "host__profile").first()
        )
        if not stream or stream.last_heartbeat < timezone.now() - timedelta(minutes=2):
            return None
        if not _can_join_live(self.user, stream):
            return None
        if stream.host_id == self.user.id:
            return {"is_host": True, "viewer_count": stream.viewers.count()}
        with transaction.atomic():
            stream = LiveStream.objects.select_for_update().get(pk=self.stream_id, status=LiveStream.LIVE)
            stream.viewers.filter(last_seen__lt=timezone.now() - timedelta(minutes=2)).delete()
            viewer, _ = LiveStreamViewer.objects.get_or_create(stream=stream, user=self.user)
            viewer.last_seen = timezone.now()
            viewer.save(update_fields=("last_seen",))
            count = stream.viewers.count()
            if count > stream.viewer_limit:
                viewer.delete()
                return {"full": True}
        return {"is_host": False, "viewer_count": count}

    @database_sync_to_async
    def leave_stream(self):
        LiveStreamViewer.objects.filter(stream_id=self.stream_id, user=self.user).delete()
        return LiveStreamViewer.objects.filter(stream_id=self.stream_id).count()

    @database_sync_to_async
    def touch_stream(self):
        return LiveStream.objects.filter(pk=self.stream_id, host=self.user, status=LiveStream.LIVE).update(last_heartbeat=timezone.now())

    @database_sync_to_async
    def touch_viewer(self):
        return LiveStreamViewer.objects.filter(stream_id=self.stream_id, user=self.user).update(last_seen=timezone.now())
