import pytest
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator

from liveclassroom.routing import websocket_urlpatterns


@pytest.mark.asyncio
async def test_session_consumer_accepts_connection():
    communicator = WebsocketCommunicator(URLRouter(websocket_urlpatterns), "/ws/liveclassroom/sessions/42/")
    connected, _ = await communicator.connect()

    assert connected
    assert await communicator.receive_json_from() == {"type": "connection.ready", "session_id": 42}
    await communicator.disconnect()
