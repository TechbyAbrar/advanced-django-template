import random
import string
import logging
import math
from datetime import timedelta

import requests
from PIL import Image
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.mail import send_mail, BadHeaderError
from django.utils import timezone

from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.response import Response
from rest_framework import status


from typing import Any, Dict, Mapping, Optional

logger = logging.getLogger(__name__)


# ---------------------------
# OTP / Email Utilities
# ---------------------------
def generate_otp(length: int = 6) -> str:
    """Generate a numeric OTP of specified length."""
    range_start = 10**(length - 1)
    range_end = (10**length) - 1
    return str(random.randint(range_start, range_end))


def get_otp_expiry(minutes: int = 30):
    return timezone.now() + timedelta(minutes=minutes)


def send_otp_email(recipient_email: str, otp: str) -> None:
    from_email = getattr(settings, "EMAIL_HOST_USER", None) or getattr(
        settings, "DEFAULT_FROM_EMAIL", None
    )
    if not from_email:
        raise ImproperlyConfigured(
            "Sender email not configured. Set EMAIL_HOST_USER or DEFAULT_FROM_EMAIL in settings."
        )

    subject = "Verify Your Email"
    message = f"Your One-Time Password (OTP) is: {otp}"

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=[recipient_email],
            fail_silently=False,
        )
        logger.info(f"OTP email sent to {recipient_email}")
    except BadHeaderError:
        logger.error("Invalid header found while sending email.")
    except Exception as e:
        logger.exception(f"Error sending OTP email to {recipient_email}: {e}")


# ---------------------------
# Token Utilities
# ---------------------------
def generate_tokens_for_user(user) -> Dict[str, str]:
    refresh = RefreshToken.for_user(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


# ---------------------------
# Image Utilities
# ---------------------------
def validate_image(image) -> None:
    if image:
        max_size = 2 * 1024 * 1024  # 2MB
        allowed_formats = ["JPEG", "PNG", "GIF"]
        if image.size > max_size:
            raise ValidationError("Image file too large (max 2MB).")
        img = Image.open(image)
        if img.format not in allowed_formats:
            raise ValidationError(
                f"Unsupported image format: {img.format}. "
                f"Allowed formats: {allowed_formats}"
            )


# ---------------------------   
# Username Utility
# ---------------------------
def generate_username(email: str) -> str:
    base = email.split("@")[0][:8]  # first 8 chars before @
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f"{base}{suffix}"



# ---------------------------
# Social Token Validation
# ---------------------------
def validate_facebook_token(access_token: str) -> Optional[Dict[str, Any]]:
    try:
        url = f"https://graph.facebook.com/me?fields=id,name,email&access_token={access_token}"
        response = requests.get(url)
        data = response.json()
        print("Facebook response:", data)
        if "error" in data:
            return None
        return data
    except Exception as e:
        print("Facebook token validation failed:", str(e))
        return None


def validate_google_token(id_token: str) -> Optional[Dict[str, Any]]:
    try:
        response = requests.get(
            f"https://www.googleapis.com/oauth2/v3/tokeninfo?id_token={id_token}"
        )
        data = response.json()
        print("Google response:", data)
        if "error_description" in data or "email" not in data:
            return None
        return data
    except Exception as e:
        print("Google token validation failed:", str(e))
        return None


