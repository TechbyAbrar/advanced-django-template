import logging

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .managers import UserManager
from .utils import normalize_phone  

logger = logging.getLogger(__name__)


class UserAuth(AbstractBaseUser, PermissionsMixin):

    user_id  = models.BigAutoField(primary_key=True)
    email    = models.EmailField(unique=True, null=True, blank=True, db_index=True)
    phone    = models.CharField(
        max_length=15,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        validators=[RegexValidator(r"^\+?\d{9,15}$", message="Phone number must be valid")]
    )
    username = models.CharField(max_length=50, unique=True, null=True, blank=True, db_index=True)

    is_verified  = models.BooleanField(default=False)
    is_active    = models.BooleanField(default=True)
    is_staff     = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    is_online    = models.BooleanField(default=False)

    last_login    = models.DateTimeField(blank=True, null=True)
    last_activity = models.DateTimeField(blank=True, null=True)
    created_at    = models.DateTimeField(default=timezone.now)
    updated_at    = models.DateTimeField(auto_now=True)

    USERNAME_FIELD  = "email"
    REQUIRED_FIELDS = ["username"]

    objects = UserManager()

    class Meta:
        verbose_name        = _("User Auth")
        verbose_name_plural = _("User Auths")
        ordering            = ["-created_at"]
        indexes = [
            models.Index(fields=["email"],      name="idx_ua_email"),
            models.Index(fields=["phone"],      name="idx_ua_phone"),
            models.Index(fields=["username"],   name="idx_ua_username"),
            models.Index(fields=["created_at"], name="idx_ua_created_at"),
        ]

    def __str__(self) -> str:
        return self.username or self.email or self.phone or f"User-{self.pk}"

    # --- Normalization ---

    def clean(self) -> None:
        if self.email:
            self.email = self.__class__.objects.normalize_email(self.email)
        if self.username:
            self.username = self.username.lower().strip()
        if self.phone:
            self.phone = normalize_phone(self.phone) 

    def save(self, *args, **kwargs) -> None:
        self.clean()
        super().save(*args, **kwargs)



class OTPVerification(models.Model):

    class Purpose(models.TextChoices):
        EMAIL_VERIFY   = "email_verify",   _("Email Verification")
        PHONE_VERIFY   = "phone_verify",   _("Phone Verification")
        PASSWORD_RESET = "password_reset", _("Password Reset")
        TWO_FACTOR     = "two_factor",     _("Two Factor Auth")

    user       = models.ForeignKey(
        UserAuth,
        on_delete=models.CASCADE,
        related_name="otp_records",
    )
    code       = models.CharField(max_length=6)
    purpose    = models.CharField(
        max_length=20,
        choices=Purpose.choices,
    )
    is_used    = models.BooleanField(default=False)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = _("OTP Verification")
        verbose_name_plural = _("OTP Verifications")
        unique_together     = ("user", "purpose")
        indexes = [
            models.Index(
                fields=["user", "purpose", "is_used"],
                name="idx_otp_user_purpose_used",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} — {self.purpose}"

    def is_valid(self) -> bool:
        return not self.is_used and timezone.now() < self.expires_at

    def consume(self) -> None:
        self.is_used = True
        self.save(update_fields=["is_used"])
        logger.debug("OTP consumed — user_id: %s, purpose: %s", self.user_id, self.purpose)