from channels.generic.websocket import AsyncJsonWebsocketConsumer


class SessionConsumer(AsyncJsonWebsocketConsumer):
    """Minimal notification channel for one live session.

    Commands deliberately remain HTTP endpoints.  Future services persist a
    change inside a database transaction and then use ``session_event`` to
    notify this group after commit.
    """

    async def connect(self):
        self.session_id = self.scope["url_route"]["kwargs"]["session_id"]
        self.group_name = f"lc.session.{self.session_id}.all"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json({"type": "connection.ready", "session_id": self.session_id})

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        # Persistence-changing messages are intentionally not accepted here.
        await self.send_json({"type": "error", "detail": "Use the HTTP API for commands."})

    async def session_event(self, event):
        await self.send_json(event["message"])
