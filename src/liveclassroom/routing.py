from django.urls import path

from .realtime.consumers import SessionConsumer

websocket_urlpatterns = [
    path("ws/liveclassroom/sessions/<int:session_id>/", SessionConsumer.as_asgi()),
]
