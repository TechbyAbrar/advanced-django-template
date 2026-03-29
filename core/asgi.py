#core/asgi.py
import os
import django
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()

from django.conf import settings

# Import AFTER django.setup() so models are ready
from chat.sio_server import socket_app


def _make_application():
    """
    Route:
      /socket.io/  → Socket.IO ASGI app
      everything else → Django ASGI app
    """
    django_app = get_asgi_application()

    async def application(scope, receive, send):
        path = scope.get("path", "")
        if path.startswith("/socket.io"):
            await socket_app(scope, receive, send)
        else:
            await django_app(scope, receive, send)

    return application


application = _make_application()