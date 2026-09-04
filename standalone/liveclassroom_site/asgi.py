import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "liveclassroom_site.settings")

django_asgi_app = get_asgi_application()

from liveclassroom.realtime.lifespan import with_liveclassroom_lifespan  # noqa: E402
from liveclassroom.routing import websocket_urlpatterns  # noqa: E402

application = with_liveclassroom_lifespan(ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
    }
))
