# authentication/views.py

from __future__ import annotations

import logging
from typing import Final

from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from django.db import transaction, IntegrityError
from django.db.models import Q
from django.utils import timezone

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from authentication.models import OTPVerification
from authentication.serializers import (
    LoginSerializer,
    OTPSendSerializer,
    OTPVerifySerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RegisterSerializer,
)
from authentication.utils import (
    generate_otp,
    generate_tokens,
    generate_username,
    get_otp_expiry,
    send_otp_email,
)

User = get_user_model()
logger = logging.getLogger(__name__)


# =============================================================================
# O(1) CONSTANTS
# =============================================================================

_MSG_INVALID_CREDENTIALS: Final[str] = "Invalid credentials."
_MSG_ACCOUNT_INACTIVE:    Final[str] = "Account is inactive."
_MSG_OTP_SENT:            Final[str] = "OTP sent successfully."
_MSG_OTP_INVALID:         Final[str] = "Invalid or expired OTP."
_MSG_OTP_VERIFIED:        Final[str] = "Verified successfully."
_MSG_LOGGED_OUT:          Final[str] = "Logged out successfully."
_MSG_PASSWORD_CHANGED:    Final[str] = "Password changed successfully."
_MSG_PASSWORD_RESET:      Final[str] = "Password reset successful."

_PURPOSE_EMAIL_VERIFY:   Final[str] = "email_verify"
_PURPOSE_PHONE_VERIFY:   Final[str] = "phone_verify"
_PURPOSE_PASSWORD_RESET: Final[str] = "password_reset"

_USERNAME_MAX_ATTEMPTS:  Final[int] = 10


# =============================================================================
# PRIVATE HELPERS
# =============================================================================

def _get_user_by_identifier(
    identifier: str,
) -> AbstractBaseUser | None:
    """
    O(1) single query — email | phone | username.
    Fetches only fields needed for login.
    """
    try:
        return User.objects.only(
            "pk", "email", "phone", "username",
            "password", "is_active", "is_verified",
        ).get(
            Q(email__iexact=identifier)    |
            Q(phone=identifier)            |
            Q(username__iexact=identifier)
        )
    except User.DoesNotExist:
        return None
    except User.MultipleObjectsReturned:
        logger.warning("Multiple users — identifier: %s", identifier)
        return None


def _get_user_by_email_or_phone(
    identifier: str,
) -> AbstractBaseUser | None:
    """
    O(1) lookup by email or phone only.
    Used by OTP, password reset — username excluded.
    """
    try:
        return User.objects.only(
            "pk", "email", "phone", "is_active", "is_verified",
        ).get(
            Q(email__iexact=identifier) |
            Q(phone=identifier)
        )
    except User.DoesNotExist:
        return None
    except User.MultipleObjectsReturned:
        logger.warning("Multiple users — identifier: %s", identifier)
        return None


def _generate_unique_username(seed: str) -> str:
    """
    Generate unique username with max attempt guard.
    Raises RuntimeError if max attempts exceeded — should never happen in practice.
    """
    for _ in range(_USERNAME_MAX_ATTEMPTS):
        username = generate_username(seed)
        if not User.objects.filter(username=username).exists():
            return username
    raise RuntimeError(
        f"Username generation failed after {_USERNAME_MAX_ATTEMPTS} attempts."
    )


def _create_otp_record(
    user: AbstractBaseUser,
    purpose: str,
) -> str:

    otp = generate_otp()

    OTPVerification.objects.update_or_create(
        user=user,
        purpose=purpose,
        defaults={
            "code":       otp,
            "expires_at": get_otp_expiry(minutes=10),
            "is_used":    False,
        },
    )

    logger.info("OTP record created — user_id: %s, purpose: %s", user.pk, purpose)
    return otp                                          # ← return otp, send outside atomic


def _consume_otp_atomic(
    user: AbstractBaseUser,
    otp: str,
    purpose: str,
) -> bool:
    """
    Single atomic read + lock + validate + consume.
    Eliminates race condition from double-query pattern.
    Returns True if consumed successfully, False if invalid.
    """
    try:
        with transaction.atomic():
            record = OTPVerification.objects.select_for_update().only(
                "pk", "code", "is_used", "expires_at"
            ).get(
                user=user,
                purpose=purpose,
                is_used=False,
            )

            if not record.is_valid() or record.code != otp:
                return False

            record.consume()
            return True

    except OTPVerification.DoesNotExist:
        return False


# =============================================================================
# REGISTER
# =============================================================================

class SignupView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request: Request) -> Response:
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data: dict[str, str] = serializer.validated_data
        email: str | None = data.get("email")
        phone: str | None = data.get("phone")
        password: str = data["password"]

        verification_channel: str = "email" if email else "phone"
        otp_purpose: str = (
            _PURPOSE_EMAIL_VERIFY if verification_channel == "email" else _PURPOSE_PHONE_VERIFY
        )

        exists_q = Q()
        if email:
            exists_q |= Q(email__iexact=email)
        if phone:
            exists_q |= Q(phone=phone)

        if exists_q and User.objects.filter(exists_q).exists():
            return Response(
                {
                    "detail": "User with this email or phone already exists."
                },
                status=status.HTTP_409_CONFLICT,
            )

        try:
            with transaction.atomic():
                username: str = _generate_unique_username(email or phone)

                user = User.objects.create_user(
                    email=email,
                    phone=phone,
                    username=username,
                    password=password,
                )

                otp: str = _create_otp_record(user, otp_purpose)

                if verification_channel == "email" and email:
                    transaction.on_commit(lambda: send_otp_email(email, otp))

        except RuntimeError as exc:
            logger.error(
                "Signup failed during username generation — email: %s, phone: %s, error: %s",
                email,
                phone,
                str(exc),
            )
            return Response(
                {"detail": "Registration failed. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        except IntegrityError:
            logger.warning(
                "Signup conflict due to integrity constraint — email: %s, phone: %s",
                email,
                phone,
            )
            return Response(
                {"detail": "User with this email or phone already exists."},
                status=status.HTTP_409_CONFLICT,
            )

        except Exception:
            logger.exception(
                "Unexpected signup failure — email: %s, phone: %s",
                email,
                phone,
            )
            return Response(
                {"detail": "Registration failed. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        tokens = generate_tokens(user)

        logger.info(
            "User registered successfully — user_id: %s, username: %s, channel: %s",
            user.pk,
            user.username,
            verification_channel,
        )

        return Response(
            {
                "detail": "Registration successful. Please verify your account.",
                "user_id": user.pk,
                "username": user.username,
                "email": user.email,
                "phone": user.phone,
                "verification_channel": verification_channel,
                "is_verified": user.is_verified,
                "tokens": tokens,
            },
            status=status.HTTP_201_CREATED,
        )

# =============================================================================
# LOGIN
# =============================================================================

class LoginView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        identifier: str = serializer.validated_data["identifier"]
        password:   str = serializer.validated_data["password"]

        user: AbstractBaseUser | None = _get_user_by_identifier(identifier)

        # --- timing attack prevention — always run check_password ---
        if user is None:
            User().check_password(password)
            return Response(
                {"detail": _MSG_INVALID_CREDENTIALS},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not user.check_password(password):
            logger.warning("Invalid password — user_id: %s", user.pk)
            return Response(
                {"detail": _MSG_INVALID_CREDENTIALS},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not user.is_active:
            return Response(
                {"detail": _MSG_ACCOUNT_INACTIVE},
                status=status.HTTP_403_FORBIDDEN,
            )

        # --- O(1) targeted field update — skip full model save ---
        User.objects.filter(pk=user.pk).update(last_login=timezone.now())

        tokens = generate_tokens(user)
        logger.info("User logged in — user_id: %s", user.pk)

        return Response(
            {
                "user_id":     user.pk,
                "username":    user.username,
                "is_verified": user.is_verified,
                "tokens":      tokens,
            },
            status=status.HTTP_200_OK,
        )


# =============================================================================
# LOGOUT
# =============================================================================

class LogoutView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        refresh_token: str | None = request.data.get("refresh")

        if not refresh_token:
            return Response(
                {"detail": "Refresh token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            RefreshToken(refresh_token).blacklist()
        except TokenError:
            return Response(
                {"detail": "Invalid or expired token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        logger.info("User logged out — user_id: %s", request.user.pk)
        return Response(
            {"detail": _MSG_LOGGED_OUT},
            status=status.HTTP_200_OK,
        )


# =============================================================================
# OTP SEND
# =============================================================================

class OTPSendView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request: Request) -> Response:
        serializer = OTPSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        identifier: str = serializer.validated_data["identifier"]
        purpose:    str = serializer.validated_data["purpose"]

        user: AbstractBaseUser | None = _get_user_by_email_or_phone(identifier)

        # --- silent — never reveal if identifier exists ---
        if user is None:
            return Response(
                {"detail": _MSG_OTP_SENT},
                status=status.HTTP_200_OK,
            )

        otp: str | None = None

        try:
            with transaction.atomic():
                otp = _create_otp_record(user, purpose)
        except Exception:
            logger.exception("OTP record failed — user_id: %s", user.pk)
            return Response(
                {"detail": "Failed to send OTP. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # --- send AFTER atomic commits ---
        if user.email and otp:
            send_otp_email(user.email, otp)

        return Response(
            {"detail": _MSG_OTP_SENT},
            status=status.HTTP_200_OK,
        )


# =============================================================================
# OTP VERIFY
# =============================================================================

class OTPVerifyView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request: Request) -> Response:
        serializer = OTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        identifier: str = serializer.validated_data["identifier"]
        otp:        str = serializer.validated_data["otp"]
        purpose:    str = serializer.validated_data["purpose"]

        user: AbstractBaseUser | None = _get_user_by_email_or_phone(identifier)

        if user is None:
            return Response(
                {"detail": _MSG_OTP_INVALID},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # --- single atomic read + lock + validate + consume ---
        consumed = _consume_otp_atomic(user, otp, purpose)

        if not consumed:
            return Response(
                {"detail": _MSG_OTP_INVALID},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # --- update user flags per purpose ---
        match purpose:
            case "email_verify" | "phone_verify":
                User.objects.filter(pk=user.pk).update(is_verified=True)
            case _:
                pass                                    # password_reset handled in confirm

        logger.info("OTP verified — user_id: %s, purpose: %s", user.pk, purpose)
        return Response(
            {"detail": _MSG_OTP_VERIFIED},
            status=status.HTTP_200_OK,
        )


# =============================================================================
# EMAIL VERIFY
# =============================================================================

class EmailVerifyView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request: Request) -> Response:
        data = request.data.copy()
        data["purpose"] = _PURPOSE_EMAIL_VERIFY        # inject purpose

        serializer = OTPVerifySerializer(data=data)
        serializer.is_valid(raise_exception=True)

        identifier: str = serializer.validated_data["identifier"]
        otp:        str = serializer.validated_data["otp"]
        purpose:    str = serializer.validated_data["purpose"]

        user: AbstractBaseUser | None = _get_user_by_email_or_phone(identifier)

        if user is None:
            return Response(
                {"detail": _MSG_OTP_INVALID},
                status=status.HTTP_400_BAD_REQUEST,
            )

        consumed = _consume_otp_atomic(user, otp, purpose)

        if not consumed:
            return Response(
                {"detail": _MSG_OTP_INVALID},
                status=status.HTTP_400_BAD_REQUEST,
            )

        User.objects.filter(pk=user.pk).update(is_verified=True)

        logger.info("Email verified — user_id: %s", user.pk)
        return Response(
            {"detail": _MSG_OTP_VERIFIED},
            status=status.HTTP_200_OK,
        )


# =============================================================================
# PHONE VERIFY
# =============================================================================

class PhoneVerifyView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request: Request) -> Response:
        data = request.data.copy()
        data["purpose"] = _PURPOSE_PHONE_VERIFY        # inject purpose

        serializer = OTPVerifySerializer(data=data)
        serializer.is_valid(raise_exception=True)

        identifier: str = serializer.validated_data["identifier"]
        otp:        str = serializer.validated_data["otp"]
        purpose:    str = serializer.validated_data["purpose"]

        user: AbstractBaseUser | None = _get_user_by_email_or_phone(identifier)

        if user is None:
            return Response(
                {"detail": _MSG_OTP_INVALID},
                status=status.HTTP_400_BAD_REQUEST,
            )

        consumed = _consume_otp_atomic(user, otp, purpose)

        if not consumed:
            return Response(
                {"detail": _MSG_OTP_INVALID},
                status=status.HTTP_400_BAD_REQUEST,
            )

        User.objects.filter(pk=user.pk).update(is_verified=True)

        logger.info("Phone verified — user_id: %s", user.pk)
        return Response(
            {"detail": _MSG_OTP_VERIFIED},
            status=status.HTTP_200_OK,
        )


# =============================================================================
# PASSWORD CHANGE
# =============================================================================

class PasswordChangeView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        serializer = PasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user: AbstractBaseUser = request.user

        if not user.check_password(serializer.validated_data["old_password"]):
            return Response(
                {"detail": "Old password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with transaction.atomic():
                user.set_password(serializer.validated_data["new_password"])
                user.save(update_fields=["password", "updated_at"])
        except Exception:
            logger.exception("Password change failed — user_id: %s", user.pk)
            return Response(
                {"detail": "Password change failed. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
            
        tokens = generate_tokens(user)

        logger.info("Password changed — user_id: %s", user.pk)
        return Response(
            {
                "detail": _MSG_PASSWORD_CHANGED,
                "tokens": tokens['access']
            },
            status=status.HTTP_200_OK,
        )


# =============================================================================
# PASSWORD RESET REQUEST
# =============================================================================

class PasswordResetRequestView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request: Request) -> Response:
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        identifier: str = serializer.validated_data["identifier"]

        user: AbstractBaseUser | None = _get_user_by_email_or_phone(identifier)

        # --- silent — never reveal if identifier exists ---
        if user is None:
            return Response(
                {"detail": _MSG_OTP_SENT},
                status=status.HTTP_200_OK,
            )

        otp: str | None = None

        try:
            with transaction.atomic():
                otp = _create_otp_record(user, _PURPOSE_PASSWORD_RESET)
        except Exception:
            logger.exception("Password reset OTP failed — user_id: %s", user.pk)
            return Response(
                {"detail": "Failed to send OTP. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # --- send AFTER atomic commits ---
        if user.email and otp:
            send_otp_email(user.email, otp)

        return Response(
            {"detail": _MSG_OTP_SENT},
            status=status.HTTP_200_OK,
        )


# =============================================================================
# PASSWORD RESET CONFIRM
# =============================================================================

class PasswordResetConfirmView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request: Request) -> Response:
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        identifier:   str = serializer.validated_data["identifier"]
        otp:          str = serializer.validated_data["otp"]
        new_password: str = serializer.validated_data["new_password"]

        user: AbstractBaseUser | None = _get_user_by_email_or_phone(identifier)

        if user is None:
            return Response(
                {"detail": _MSG_OTP_INVALID},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # --- single atomic read + lock + validate + consume + reset ---
        consumed = _consume_otp_atomic(user, otp, _PURPOSE_PASSWORD_RESET)

        if not consumed:
            return Response(
                {"detail": _MSG_OTP_INVALID},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with transaction.atomic():
                user_obj = User.objects.select_for_update().get(pk=user.pk)
                user_obj.set_password(new_password)
                user_obj.save(update_fields=["password", "updated_at"])
        except Exception:
            logger.exception("Password reset failed — user_id: %s", user.pk)
            return Response(
                {"detail": "Password reset failed. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        token = generate_tokens(user)
        
        logger.info("Password reset — user_id: %s", user.pk)
        return Response(
            {"detail": _MSG_PASSWORD_RESET,
             "tokens": token['access']},
            status=status.HTTP_200_OK,
        )