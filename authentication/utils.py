# authentication/utils.py

import logging
import random
import re
import string
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import BadHeaderError, send_mail
from django.utils import timezone

from rest_framework_simplejwt.tokens import RefreshToken

logger = logging.getLogger(__name__)


# =============================================================================
# OTP
# =============================================================================

def generate_otp(length: int = 6) -> str:
    import secrets
    return "".join(secrets.choice(string.digits) for _ in range(length))


def get_otp_expiry(minutes: int = 10) -> timezone.datetime:
    return timezone.now() + timedelta(minutes=minutes)


# =============================================================================
# EMAIL
# =============================================================================

def _get_from_email() -> str:
    from_email = (
        getattr(settings, "EMAIL_HOST_USER", None)
        or getattr(settings, "DEFAULT_FROM_EMAIL", None)
    )
    if not from_email:
        raise ImproperlyConfigured(
            "Sender email not configured. "
            "Set EMAIL_HOST_USER or DEFAULT_FROM_EMAIL in settings."
        )
    return from_email


def send_otp_email(recipient_email: str, otp: str) -> bool:
    try:
        send_mail(
            subject="Your Verification Code",
            message=f"Your OTP is: {otp}\nThis code expires in 10 minutes. Do not share it.",
            from_email=_get_from_email(),
            recipient_list=[recipient_email],
            fail_silently=False,
        )
        logger.info("OTP email sent — recipient: %s", recipient_email)
        return True
    except BadHeaderError:
        logger.error("Bad header detected — recipient: %s", recipient_email)
        return False
    except Exception:
        logger.exception("Failed to send OTP email — recipient: %s", recipient_email)
        return False


# =============================================================================
# JWT TOKENS
# =============================================================================

def generate_tokens(user) -> dict[str, str]:
    refresh = RefreshToken.for_user(user)
    return {
        "access":  str(refresh.access_token),
        "refresh": str(refresh),
    }


# =============================================================================
# USERNAME
# =============================================================================

def generate_username(email: str) -> str:
    import secrets
    base   = re.sub(r"[^a-z0-9]", "", email.split("@")[0].lower())[:8]
    suffix = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(4))
    return f"{base}_{suffix}"


# =============================================================================
# PHONE
# =============================================================================

def normalize_phone(phone: str) -> str:
    phone = re.sub(r"[\s\-\(\)]", "", phone.strip())
    return phone if phone.startswith("+") else f"+{phone}"
