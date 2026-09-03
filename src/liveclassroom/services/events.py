import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction

from liveclassroom.realtime.postgres import publish_notification

logger = logging.getLogger(__name__)


def notify_session_after_commit(session_id: int, message: dict) -> None:
    """Schedule a session notification only after its database changes commit."""

    def broadcast() -> None:
        outgoing = {"protocol_version": message.get("protocol_version", message.get("protocol", 1)), **message}
        channel_layer = get_channel_layer()
        if channel_layer is not None:
            async_to_sync(channel_layer.group_send)(
                f"lc.session.{session_id}.all", {"type": "session.event", "message": outgoing}
            )
        try:
            publish_notification(session_id, outgoing)
        except Exception:  # pragma: no cover - database/driver failures are environment-specific
            # The database remains authoritative; a relay failure is recoverable by polling.
            logger.warning("LiveClassroom PostgreSQL relay publish failed", exc_info=True)

    transaction.on_commit(broadcast)
