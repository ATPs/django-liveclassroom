from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction


def notify_session_after_commit(session_id: int, message: dict) -> None:
    """Schedule a session notification only after its database changes commit."""

    def broadcast() -> None:
        channel_layer = get_channel_layer()
        if channel_layer is not None:
            async_to_sync(channel_layer.group_send)(
                f"lc.session.{session_id}.all", {"type": "session.event", "message": message}
            )

    transaction.on_commit(broadcast)
