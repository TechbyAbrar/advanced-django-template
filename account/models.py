# account/models.py — reusable account profile boilerplate
import logging

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from authentication.models import UserAuth  # adjust to your import path

logger = logging.getLogger(__name__)

class Gender(models.TextChoices):
    MALE       = "male",       _("Male")
    FEMALE     = "female",     _("Female")
    NON_BINARY = "non_binary", _("Non-Binary")
    PREFER_NOT = "prefer_not", _("Prefer Not to Say")


# ── Default factory ────────────────────────────────────────────────────────
# Callable → Django calls it per row, so every Account gets its own dict.
# schema_version lets you migrate the blob's shape safely in the future.
# Extend this in your project: add "notifications", "theme", etc.

def default_preferences() -> dict:
    return {"schema_version": 1}

class Account(models.Model):
    user = models.OneToOneField(
        UserAuth,
        on_delete=models.CASCADE,
        related_name="account",
        db_index=False,         
    )


    first_name   = models.CharField(max_length=64,  blank=True, default="")
    last_name    = models.CharField(max_length=64,  blank=True, default="")
    display_name = models.CharField(max_length=100, blank=True, default="", db_index=True)
    
    profile_pic = models.ImageField(upload_to="avatars/%Y/%m/", null=True, blank=True,)
    avatar_url   = models.URLField(max_length=512,  blank=True, default="")
    bio          = models.TextField(max_length=500, blank=True, default="")

    gender        = models.CharField(max_length=12, choices=Gender.choices, blank=True, default="")
    date_of_birth = models.DateField(null=True, blank=True)
    country       = models.CharField(max_length=64, blank=True, default="")

    language = models.CharField(max_length=10, default="en")
    timezone = models.CharField(max_length=64, default="UTC")

    preferences = models.JSONField(default=default_preferences)

    # ── Soft delete ────────────────────────────────────────────────────────

    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    # ── Meta ───────────────────────────────────────────────────────────────

    class Meta:
        verbose_name        = _("Account")
        verbose_name_plural = _("Accounts")
        ordering            = ["-created_at"]
        indexes = [
            # Covers the common "list active accounts" query pattern
            models.Index(
                fields=["is_deleted", "created_at"],
                name="idx_acct_deleted_created",
            ),
        ]
        constraints = [
            # DB-level coherence: deleted_at must be stamped when is_deleted=True
            models.CheckConstraint(
                condition=(
                    models.Q(is_deleted=False)
                    | models.Q(is_deleted=True, deleted_at__isnull=False)
                ),
                name="chk_acct_deleted_at_set",
            ),
        ]

    # ── Dunder ─────────────────────────────────────────────────────────────

    def __str__(self) -> str:
        return self.display_name or f"Account<{self.user_id}>"

    # ── Normalization ──────────────────────────────────────────────────────

    def clean(self) -> None:
        self.first_name  = self.first_name.strip().title()
        self.last_name   = self.last_name.strip().title()
        self.language    = self.language.lower().strip()
        self.country     = self.country.strip().title()

        if not self.display_name:
            self.display_name = f"{self.first_name} {self.last_name}".strip()

    def save(self, *args, **kwargs) -> None:
        self.clean()
        super().save(*args, **kwargs)


    def soft_delete(self) -> None:
        if self.is_deleted:
            return
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at", "updated_at"])
        logger.info("Account soft-deleted — id=%s", self.pk)

    def restore(self) -> None:
        if not self.is_deleted:
            return
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=["is_deleted", "deleted_at", "updated_at"])
        logger.info("Account restored — id=%s", self.pk)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def is_active(self) -> bool:
        return not self.is_deleted