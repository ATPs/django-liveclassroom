"""PostgreSQL notification relay for cross-worker classroom wake-ups."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import connection

NOTIFY_CHANNEL = "liveclassroom_events"
_MAX_PAYLOAD_BYTES = 7_500


@dataclass(frozen=True)
class PersistedNotification:
    """The safe identifiers sent through PostgreSQL and local WebSocket groups."""

    session_id: int
    version: int
    event_id: int | None = None

    def as_payload(self) -> dict[str, int]:
        """Return a JSON-safe payload containing no classroom content."""
        payload: dict[str, int] = {"session_id": self.session_id, "version": self.version}
        if self.event_id is not None:
            payload["event_id"] = self.event_id
        return payload


def _notification_from_message(session_id: int, message: dict[str, Any]) -> PersistedNotification:
    """Extract identifiers from a service message and reject malformed versions."""
    try:
        version = int(message["version"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("A realtime message needs an integer version") from exc
    event_id = message.get("event_id")
    if event_id is not None:
        try:
            event_id = int(event_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("A realtime message event_id must be an integer") from exc
    session_id = int(session_id)
    if session_id <= 0 or version < 0 or (event_id is not None and event_id < 0):
        raise ValueError("A realtime notification contains an invalid identifier or version")
    return PersistedNotification(session_id, version, event_id)


def publish_notification(session_id: int, message: dict[str, Any]) -> bool:
    """Publish one small PostgreSQL notification when the default database supports it."""
    if connection.vendor != "postgresql":
        return False
    notification = _notification_from_message(session_id, message)
    payload = json.dumps(notification.as_payload(), separators=(",", ":"))
    if len(payload.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        raise ValueError("LiveClassroom realtime notification is too large")
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_notify(%s, %s)", [NOTIFY_CHANNEL, payload])
    return True


def _connection_kwargs() -> dict[str, Any]:
    """Translate Django's default PostgreSQL settings to psycopg keyword arguments."""
    database = settings.DATABASES["default"]
    if database.get("ENGINE") != "django.db.backends.postgresql":
        raise RuntimeError("PostgreSQL realtime relay requires a PostgreSQL default database")
    kwargs: dict[str, Any] = {
        "dbname": database.get("NAME") or None,
        "user": database.get("USER") or None,
        "password": database.get("PASSWORD") or None,
        "host": database.get("HOST") or None,
        "port": database.get("PORT") or None,
    }
    options = database.get("OPTIONS") or {}
    for key in ("sslmode", "sslcert", "sslkey", "sslrootcert", "connect_timeout"):
        if key in options:
            kwargs[key] = options[key]
    return {key: value for key, value in kwargs.items() if value is not None}


class PostgresNotificationRelay:
    """Forward PostgreSQL notifications to this ASGI worker's channel layer."""

    def __init__(self, channel_layer: Any, *, retry_seconds: float = 2.0) -> None:
        self.channel_layer = channel_layer
        self.retry_seconds = retry_seconds
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    def start(self) -> asyncio.Task[None]:
        """Start one listener task for the current ASGI worker."""
        if self._task is None or self._task.done():
            self._stopping.clear()
            self._task = asyncio.create_task(self.run(), name="liveclassroom-postgres-relay")
        return self._task

    async def stop(self) -> None:
        """Stop the listener task and release its database connection."""
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def run(self) -> None:
        """Listen with bounded reconnects and forward only safe state identifiers."""
        try:
            from psycopg import AsyncConnection
        except ImportError:
            return

        while not self._stopping.is_set():
            try:
                async with await AsyncConnection.connect(**_connection_kwargs(), autocommit=True) as database:
                    await database.execute(f"LISTEN {NOTIFY_CHANNEL}")
                    async for notification in database.notifies():
                        if self._stopping.is_set():
                            return
                        payload = json.loads(notification.payload)
                        session_id = int(payload["session_id"])
                        await self.channel_layer.group_send(
                            f"lc.session.{session_id}.all",
                            {
                                "type": "session.event",
                                "message": {
                                    "protocol": 1,
                                    "session_id": session_id,
                                    "version": int(payload["version"]),
                                    "type": "state.changed",
                                    "payload": {"event_id": payload.get("event_id")},
                                },
                            },
                        )
            except asyncio.CancelledError:
                raise
            except (OSError, RuntimeError, KeyError, TypeError, ValueError):
                await asyncio.sleep(self.retry_seconds)
