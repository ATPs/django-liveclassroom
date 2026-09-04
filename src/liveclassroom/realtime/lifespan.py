"""ASGI lifespan support for the optional PostgreSQL notification relay."""

from __future__ import annotations

from typing import Any

from channels.layers import get_channel_layer
from django.conf import settings

from .postgres import PostgresNotificationRelay


class LiveClassroomLifespan:
    """Start one relay for this worker without changing HTTP or WebSocket routing."""

    def __init__(self, application, *, relay_factory=PostgresNotificationRelay) -> None:
        self.application = application
        self.relay_factory = relay_factory

    async def __call__(self, scope: dict[str, Any], receive, send):
        if scope["type"] != "lifespan":
            return await self.application(scope, receive, send)

        relay = None
        while True:
            message = await receive()
            message_type = message["type"]
            if message_type == "lifespan.startup":
                if settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":
                    channel_layer = get_channel_layer()
                    if channel_layer is not None:
                        relay = self.relay_factory(channel_layer)
                        relay.start()
                await send({"type": "lifespan.startup.complete"})
            elif message_type == "lifespan.shutdown":
                if relay is not None:
                    await relay.stop()
                await send({"type": "lifespan.shutdown.complete"})
                return


def with_liveclassroom_lifespan(application):
    """Wrap a host ASGI application with the package's worker lifecycle hook."""
    return LiveClassroomLifespan(application)
