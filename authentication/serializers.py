# authentication/serializers.py

from __future__ import annotations

import re
from typing import Any

from rest_framework import serializers

from authentication.utils import normalize_phone

# =============================================================================
# CONSTANTS
# =============================================================================

_OTP_PURPOSE_CHOICES: tuple[str, ...] = (
    "email_verify",
    "phone_verify",
    "password_reset",
    "two_factor",
)

_PHONE_REGEX = re.compile(r"^\+\d{9,15}$")


# =============================================================================
# PRIVATE HELPERS
# =============================================================================

def _validate_password_strength(value: str) -> str:
    """
    Shared password strength validator.
    Used across Register, PasswordChange, PasswordResetConfirm.
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
    Normalize then validate phone.
    Shared across any serializer that accepts phone input.
    """
    normalized = normalize_phone(value)
    if not _PHONE_REGEX.match(normalized):
        raise serializers.ValidationError(
            "Phone number must be valid (e.g. +8801711000000)."
        )
    return normalized


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
        trim_whitespace=False,                  # never trim passwords
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


# =============================================================================
# OTP
# =============================================================================

class OTPSendSerializer(serializers.Serializer):
    identifier = serializers.CharField(
        max_length=255,
        trim_whitespace=True,
    )
    purpose    = serializers.ChoiceField(choices=_OTP_PURPOSE_CHOICES)


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
        if attrs["old_password"] == attrs["new_password"]:
            raise serializers.ValidationError(
                "New password must be different from old password."
            )
        return attrs


class PasswordResetRequestSerializer(serializers.Serializer):
    identifier = serializers.CharField(
        max_length=255,
        trim_whitespace=True,
    )


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

    def validate_new_password(self, value: str) -> str:
        return _validate_password_strength(value)
