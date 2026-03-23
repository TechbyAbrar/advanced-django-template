# authentication/serializers.py

from __future__ import annotations

import re
from typing import Any

from rest_framework import serializers

from authentication.utils import normalize_phone

# =============================================================================
# CONSTANTS
# =============================================================================

_PHONE_REGEX = re.compile(r"^\+\d{9,15}$")             # compiled once at import

_OTP_PURPOSE_CHOICES: tuple[tuple[str, str], ...] = (
    ("email_verify",   "Email Verification"),
    ("phone_verify",   "Phone Verification"),
    ("password_reset", "Password Reset"),
    ("two_factor",     "Two Factor Auth"),
)

# pre-compiled phone detection — starts with + or contains only digits/spaces/dashes
_PHONE_DETECT_REGEX = re.compile(r"^[\+\d\s\-\(\)\.]+$")


# =============================================================================
# PRIVATE HELPERS
# =============================================================================

def _validate_password_strength(value: str) -> str:
    """
    Shared password strength validator.
    Used by Register, PasswordChange, PasswordResetConfirm.
    """
    if value.isdigit():
        raise serializers.ValidationError(
            "Password cannot be entirely numeric."
        )
    if len(set(value)) < 3:
        raise serializers.ValidationError(
            "Password is too simple."
        )
    return value


def _validate_phone_format(value: str) -> str:
    """
    Normalize then validate.
    Never validate raw input — always normalize first.
    """
    normalized = normalize_phone(value)
    if not _PHONE_REGEX.match(normalized):
        raise serializers.ValidationError(
            "Phone number must be valid (e.g. +8801711000000)."
        )
    return normalized


def _normalize_identifier(value: str) -> str:
    """
    Normalize identifier at serializer boundary before hitting backend.

    Detection order:
    1. Matches phone pattern  → normalize_phone()
    2. Contains @             → email  → lowercase + strip
    3. Anything else          → username → lowercase + strip

    This ensures Q(phone=identifier) exact match always works in views.
    """
    stripped = value.strip()

    if _PHONE_DETECT_REGEX.match(stripped):             # ✅ fixed phone detection
        try:
            normalized = normalize_phone(stripped)
            if _PHONE_REGEX.match(normalized):          # only if valid E.164
                return normalized
        except Exception:
            pass                                        # fall through to email/username

    return stripped.lower()                             # email or username


# =============================================================================
# REGISTER
# =============================================================================

class RegisterSerializer(serializers.Serializer):
    email    = serializers.EmailField(
        required=False,
    )
    phone    = serializers.CharField(
        required=False,
        max_length=16,
        trim_whitespace=True,
    )
    password = serializers.CharField(
        write_only=True,
        min_length=8,
        max_length=128,
        trim_whitespace=False,                          # never trim passwords
    )

    def validate_phone(self, value: str) -> str:
        return _validate_phone_format(value)

    def validate_password(self, value: str) -> str:
        return _validate_password_strength(value)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not attrs.get("email") and not attrs.get("phone"):
            raise serializers.ValidationError(
                "At least one of email or phone is required."
            )
        return attrs


# =============================================================================
# LOGIN
# =============================================================================

class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField(
        max_length=255,
        trim_whitespace=True,
    )
    password   = serializers.CharField(
        write_only=True,
        max_length=128,
        trim_whitespace=False,
    )

    def validate_identifier(self, value: str) -> str:
        return _normalize_identifier(value)


# =============================================================================
# OTP
# =============================================================================

class OTPSendSerializer(serializers.Serializer):
    identifier = serializers.CharField(
        max_length=255,
        trim_whitespace=True,
    )
    purpose    = serializers.ChoiceField(choices=_OTP_PURPOSE_CHOICES)

    def validate_identifier(self, value: str) -> str:
        return _normalize_identifier(value)


class OTPVerifySerializer(serializers.Serializer):
    identifier = serializers.CharField(
        max_length=255,
        trim_whitespace=True,
    )
    otp        = serializers.CharField(
        min_length=6,
        max_length=6,
        trim_whitespace=True,
    )
    purpose    = serializers.ChoiceField(choices=_OTP_PURPOSE_CHOICES)

    def validate_identifier(self, value: str) -> str:
        return _normalize_identifier(value)

    def validate_otp(self, value: str) -> str:
        if not value.isdigit():
            raise serializers.ValidationError("OTP must be numeric.")
        return value


# =============================================================================
# PASSWORD
# =============================================================================

class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(
        write_only=True,
        max_length=128,
        trim_whitespace=False,
    )
    new_password = serializers.CharField(
        write_only=True,
        min_length=8,
        max_length=128,
        trim_whitespace=False,
    )

    def validate_new_password(self, value: str) -> str:
        return _validate_password_strength(value)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs.get("old_password") == attrs.get("new_password"):
            raise serializers.ValidationError(
                "New password must be different from old password."
            )
        return attrs


class PasswordResetRequestSerializer(serializers.Serializer):
    identifier = serializers.CharField(
        max_length=255,
        trim_whitespace=True,
    )

    def validate_identifier(self, value: str) -> str:
        return _normalize_identifier(value)


class PasswordResetConfirmSerializer(serializers.Serializer):
    identifier   = serializers.CharField(
        max_length=255,
        trim_whitespace=True,
    )
    otp          = serializers.CharField(
        min_length=6,
        max_length=6,
        trim_whitespace=True,
    )
    new_password = serializers.CharField(
        write_only=True,
        min_length=8,
        max_length=128,
        trim_whitespace=False,
    )

    def validate_identifier(self, value: str) -> str:
        return _normalize_identifier(value)

    def validate_otp(self, value: str) -> str:
        if not value.isdigit():
            raise serializers.ValidationError("OTP must be numeric.")
        return value

    def validate_new_password(self, value: str) -> str:
        return _validate_password_strength(value)