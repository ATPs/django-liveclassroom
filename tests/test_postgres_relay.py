import json

import pytest

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
