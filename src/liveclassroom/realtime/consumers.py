from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from liveclassroom.models import LiveSession, Participant
from liveclassroom.services.classroom import can_view_session, mark_participant_connected, mark_participant_disconnected


class SessionConsumer(AsyncJsonWebsocketConsumer):
    """Minimal notification channel for one live session.

    Commands deliberately remain HTTP endpoints.  Future services persist a
    change inside a database transaction and then use ``session_event`` to
    notify this group after commit.
    """

    async def connect(self):
        self.session_id = self.scope["url_route"]["kwargs"]["session_id"]
        self.participant_id = await self._authorized_participant_id()
        if self.participant_id is None and not await self._authorized_staff():
            await self.close(code=4403)
            return
        self.group_name = f"lc.session.{self.session_id}.all"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        if self.participant_id is not None:
            await self._mark_connected(self.participant_id)
        await self.send_json({"type": "connection.ready", "session_id": self.session_id})

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        if getattr(self, "participant_id", None) is not None:
            await self._mark_disconnected(self.participant_id)

    async def receive_json(self, content, **kwargs):
        # Persistence-changing messages are intentionally not accepted here.
        await self.send_json({"type": "error", "detail": "Use the HTTP API for commands."})

    async def session_event(self, event):
        await self.send_json(event["message"])

    @database_sync_to_async
    def _authorized_staff(self) -> bool:
        session = LiveSession.objects.filter(pk=self.session_id).first()
        user = self.scope.get("user")
        return bool(session and user and can_view_session(user, session))

    @database_sync_to_async
    def _authorized_participant_id(self) -> int | None:
        session = LiveSession.objects.filter(pk=self.session_id).first()
        if session is None:
            return None
        session_data = self.scope.get("session")
        participant_id = session_data.get(f"liveclassroom.participant.{self.session_id}") if session_data else None
        if not participant_id:
            return None
        participant = Participant.objects.filter(
            pk=participant_id,
            session=session,
            admission_state=Participant.AdmissionState.ADMITTED,
        ).first()
        return participant.id if participant else None

    @database_sync_to_async
    def _mark_connected(self, participant_id: int) -> None:
        participant = Participant.objects.get(pk=participant_id)
        mark_participant_connected(participant=participant)

    @database_sync_to_async
    def _mark_disconnected(self, participant_id: int) -> None:
        participant = Participant.objects.filter(pk=participant_id).first()
        if participant is not None:
            mark_participant_disconnected(participant=participant)
