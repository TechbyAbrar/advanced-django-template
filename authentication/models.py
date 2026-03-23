import logging

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .managers import UserManager

logger = logging.getLogger(__name__)


class UserAuth(AbstractBaseUser, PermissionsMixin):

    user_id  = models.AutoField(primary_key=True)
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
    is_active    = models.BooleanField(default=True, db_index=True)
    is_staff     = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    is_online    = models.BooleanField(default=False, db_index=True)

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
            models.Index(fields=["email"],    name="idx_userauth_email"),
            models.Index(fields=["phone"],    name="idx_userauth_phone"),
            models.Index(fields=["username"], name="idx_userauth_username"),
            models.Index(fields=["is_active"], name="idx_userauth_is_active"),
            models.Index(fields=["is_online"], name="idx_userauth_is_online"),
            models.Index(fields=["is_staff", "is_active"], name="idx_userauth_staff_active"),
            models.Index(fields=["last_activity"], name="idx_userauth_last_activity"),
            models.Index(fields=["created_at"],    name="idx_userauth_created_at"),
            models.Index(fields=["is_active", "is_online", "last_activity"], name="idx_userauth_active_online_activity"),
        ]

    def __str__(self) -> str:
        return self.username or self.email or self.phone or f"User-{self.pk}"

    # --- Normalization ---

    def clean(self) -> None:
        """Normalize all identifiers before validation."""
        if self.email:
            self.email = self.__class__.objects.normalize_email(self.email)

        if self.username:
            self.username = self.username.lower().strip()

        if self.phone:
            self.phone = self._normalize_phone(self.phone)

    def save(self, *args, **kwargs) -> None:
        """Always run clean() before saving."""
        self.clean()
        super().save(*args, **kwargs)

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        import re
        phone = re.sub(r"[\s\-\(\)]", "", phone.strip())
        if not phone.startswith("+"):
            phone = "+" + phone
        return phone