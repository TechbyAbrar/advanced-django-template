# import os

# from django.core.asgi import get_asgi_application

# os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

# application = get_asgi_application()



"""
asgi.py
=======
ASGI entry point that mounts the Socket.IO ASGI app alongside Django.

URL routing:
  /socket.io/*   → python-socketio (Socket.IO engine)
  /*             → Django (REST API, admin, static)

Run with uvicorn:
  uvicorn config.asgi:application --host 0.0.0.0 --port 8000 --workers 4

For production with gunicorn + uvicorn workers:
  gunicorn config.asgi:application \
      -k uvicorn.workers.UvicornWorker \
      --workers 4 \
      --bind 0.0.0.0:8000 \
      --timeout 120
"""

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