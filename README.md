# 🚀 Django Realtime Backend Template

A production-ready backend template built with **Django (ASGI)**, **Socket.IO**, **Redis**, **Celery**, and **JWT Authentication**.

This project is designed to support:

* 🔐 Scalable authentication system
* 💬 Realtime chat using Socket.IO
* ⚡ Background task processing (Celery)
* 🧠 Redis-powered pub/sub & caching
* 📦 Production deployment with Gunicorn + Uvicorn

---

# 📌 Project Goal

This template provides a **clean, scalable, and production-ready architecture** for building:

* Chat applications
* Social platforms
* Realtime dashboards
* Scalable SaaS backends

---

# 🧱 Tech Stack

* Django 5 (ASGI)
* Django REST Framework
* Socket.IO (python-socketio)
* Redis (Pub/Sub + Cache + Channels)
* Celery (worker + beat)
* PostgreSQL (PostGIS ready)
* JWT Authentication
* Gunicorn + Uvicorn Worker

---

# 📁 Project Structure

```
core/
 ├── asgi.py              # ASGI routing (Django + Socket.IO)
 ├── settings.py          # Environment-based settings
 ├── urls.py

chat/
 ├── sio_server.py        # Socket.IO server

authentication/
 ├── views.py
 ├── serializers.py

.env                      # Environment variables
```

---

# ⚙️ Environment Setup

## 1. Clone & Setup

```bash
git clone <repo-url>
cd project
python -m venv env
source env/bin/activate
pip install -r requirements.txt
```

---

## 2. Create `.env` file

```
SECRET_KEY=your-secret-key
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost

DATABASE_URL=postgres://user:password@localhost:5432/dbname

EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-password
```

---

## 3. Apply Migrations

```bash
python manage.py migrate
```

---

# 🔥 Running the Project (Development)

## 1. Start Redis

```bash
redis-server --port 6379
```

Verify:

```bash
redis-cli ping
# Expected: PONG
```

---

## 2. Run Celery Worker

```bash
source env/bin/activate
celery -A core worker -l info
```

---

## 3. Run Celery Beat

```bash
source env/bin/activate
celery -A core beat -l info
```

---

## 4. Run Backend (ASGI)

```bash
gunicorn core.asgi:application \
  -k uvicorn.workers.UvicornWorker \
  --workers 4 \
  --threads 2 \
  --bind 0.0.0.0:8004 \
  --timeout 60 \
  --graceful-timeout 30 \
  --keep-alive 5 \
  --max-requests 2000 \
  --max-requests-jitter 200 \
  --access-logfile - \
  --error-logfile - \
  --log-level info
```

---

# 🔌 Realtime (Socket.IO)

### Endpoint

```
http://localhost:8004
```

### Socket Path

```
/socket.io
```

### Architecture

```python
if path.startswith("/socket.io"):
    await socket_app(scope, receive, send)
```

👉 Routes Socket.IO traffic separately from Django REST 

---

# 🧪 Testing

## REST APIs

Use:

* Postman
* Apidog
* Swagger (`/api/schema/` if enabled)

## Socket.IO

Use:

* Apidog (Socket.IO mode)
* Postman WebSocket
* Node / Python client

---

# 🔐 Authentication System

Supports:

* Email / Phone / Username login
* OTP verification
* Password reset
* JWT (Access + Refresh)

### Example Login Payload

```json
{
  "identifier": "user@example.com",
  "password": "StrongPass@123"
}
```

---

# 💬 Chat Features

* Realtime messaging
* Typing indicator
* Read receipts
* Reactions
* Presence tracking
* Idempotent messaging

---

# 🧠 Redis Usage

* Channel Layers (WebSocket scaling)
* Socket.IO Pub/Sub
* Django cache
* Celery broker

```python
CHANNEL_LAYERS = {
  "default": {
    "BACKEND": "channels_redis.core.RedisChannelLayer",
    "CONFIG": {"hosts": [("127.0.0.1", 6379)]},
  },
}
```

---

# ⚡ Celery Usage

* OTP sending
* Background jobs
* Scheduled tasks (via beat)

---

# 🛠️ Useful Commands

## Check running port

```bash
sudo lsof -t -i:8004
```

## Kill port

```bash
sudo kill -9 <pid>
```

---

# 🚀 Production Notes

* Set `DEBUG=False`
* Use real domain in `ALLOWED_HOSTS`
* Replace JWT signing key with `SECRET_KEY`
* Use managed Redis (AWS Elasticache / etc.)
* Use Nginx reverse proxy

---

# ⚠️ Common Issues

### ❌ Socket.IO not connecting

* Check `/socket.io` path
* Ensure ASGI is used (not `runserver`)

### ❌ Redis not working

* Ensure Redis is running
* Check port 6379

### ❌ Celery not processing

* Worker not running
* Broker URL mismatch

---

# 🎯 Final Notes

This template follows:

* Clean architecture
* Production-grade patterns
* Scalable realtime design

You can directly build:

* Chat apps
* Social apps
* SaaS platforms

---

# 🤝 Contribution

Feel free to fork, improve, and extend this template.

---

# 👨‍💻 Maintained by

**Abrar Fahim**
Backend Developer (Python)

Under Development: Push Notification apps functionalities integrated soon....
