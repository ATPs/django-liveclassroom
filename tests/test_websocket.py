import pytest
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model

from liveclassroom.models import LiveSession
from liveclassroom.routing import websocket_urlpatterns


@pytest.fixture
def websocket_session(db):
    user = get_user_model().objects.create_user(username="socket-teacher")
    session = LiveSession.objects.create(teacher=user, title="Socket test")
    return session, user


class ScopeMiddleware:
    def __init__(self, app, *, user, session=None):
        self.app = app
        self.user = user
        self.session = session or {}

    async def __call__(self, scope, receive, send):
        scope = {**scope, "user": self.user, "session": self.session}
        return await self.app(scope, receive, send)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_session_consumer_rejects_unknown_or_anonymous_connection():
    communicator = WebsocketCommunicator(URLRouter(websocket_urlpatterns), "/ws/liveclassroom/sessions/42/")
    connected, _ = await communicator.connect()

    assert not connected


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_session_consumer_accepts_authorized_staff(websocket_session):
    session, teacher = websocket_session
    application = ScopeMiddleware(URLRouter(websocket_urlpatterns), user=teacher)
    communicator = WebsocketCommunicator(application, f"/ws/liveclassroom/sessions/{session.id}/")
    connected, _ = await communicator.connect()

    assert connected
    assert await communicator.receive_json_from() == {"type": "connection.ready", "session_id": session.id}
    await communicator.disconnect()
