import asyncio
import json
from unittest.mock import AsyncMock, Mock

import pytest
from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer
from django.db import connection, connections
from django.test import override_settings

from liveclassroom.realtime.consumers import SessionConsumer
from liveclassroom.realtime.lifespan import LiveClassroomLifespan
from liveclassroom.realtime.postgres import (
    NOTIFY_CHANNEL,
    PersistedNotification,
    _notification_from_message,
    publish_notification,
)


def test_notification_contains_only_state_identifiers():
    notification = PersistedNotification(7, 12, 99)

    assert notification.as_payload() == {"session_id": 7, "version": 12, "event_id": 99}
    assert "answer" not in json.dumps(notification.as_payload())


def test_notification_rejects_missing_version():
    with pytest.raises(ValueError, match="integer version"):
        _notification_from_message(7, {"type": "state.changed"})


def test_sqlite_does_not_publish_postgres_notification():
    assert publish_notification(7, {"version": 12}) is False
    assert NOTIFY_CHANNEL == "liveclassroom_events"


@pytest.mark.asyncio
async def test_consumer_suppresses_duplicate_or_older_state_notifications():
    consumer = SessionConsumer()
    consumer._last_event_version = -1
    consumer.send_json = AsyncMock()

    await consumer.session_event({"message": {"version": 4, "type": "state.changed"}})
    await consumer.session_event({"message": {"version": 4, "type": "state.changed"}})
    await consumer.session_event({"message": {"version": 3, "type": "state.changed"}})
    await consumer.session_event({"message": {"version": 5, "type": "state.changed"}})

    assert consumer.send_json.await_count == 2
    assert consumer.send_json.await_args_list[0].args[0]["version"] == 4
    assert consumer.send_json.await_args_list[1].args[0]["version"] == 5


@pytest.mark.asyncio
@override_settings(DATABASES={"default": {"ENGINE": "django.db.backends.postgresql", "NAME": "liveclassroom"}})
async def test_lifespan_starts_and_stops_one_postgres_relay_per_worker():
    lifecycle_messages = [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]
    sent = []
    relay = type("Relay", (), {"start": Mock(), "stop": AsyncMock()})()

    async def receive():
        return lifecycle_messages.pop(0)

    async def send(message):
        sent.append(message)

    async def unused_application(scope, receive, send):
        raise AssertionError("lifespan should not reach the wrapped router")

    application = LiveClassroomLifespan(unused_application, relay_factory=lambda layer: relay)
    await application({"type": "lifespan"}, receive, send)

    assert relay.start.call_count == 1
    assert relay.stop.await_count == 1
    assert sent == [{"type": "lifespan.startup.complete"}, {"type": "lifespan.shutdown.complete"}]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_real_postgres_relay_forwards_a_committed_notification():
    if connection.vendor != "postgresql":
        pytest.skip("requires the optional PostgreSQL test settings")
    layer = get_channel_layer()
    channel_name = await layer.new_channel("lc.postgres.acceptance")
    await layer.group_add("lc.session.42.all", channel_name)
    from liveclassroom.realtime.postgres import PostgresNotificationRelay

    relay = PostgresNotificationRelay(layer, retry_seconds=0.05)
    relay.start()
    try:
        await asyncio.sleep(0.1)
        published = await sync_to_async(publish_notification)(42, {"version": 7, "event_id": 9})
        await sync_to_async(connections.close_all)()
        assert published
        event = await asyncio.wait_for(layer.receive(channel_name), timeout=5)
    finally:
        await relay.stop()
        await layer.group_discard("lc.session.42.all", channel_name)

    assert event["message"] == {
        "protocol": 1,
        "session_id": 42,
        "version": 7,
        "type": "state.changed",
        "payload": {"event_id": 9},
    }
