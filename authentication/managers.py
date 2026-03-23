import logging

from django.contrib.auth.base_user import BaseUserManager, AbstractBaseUser
from django.utils.translation import gettext_lazy as _

from authentication.utils import normalize_phone  # ← single source of truth

logger = logging.getLogger(__name__)


class UserManager(BaseUserManager):

    # --- Internal Normalizers ---

    @staticmethod
    def _normalize_username(username: str) -> str:
        return username.lower().strip()

    # --- Core Creator ---

    def _create_user(
        self,
        email: str,
        password: str | None = None,
        **extra_fields,
    ) -> AbstractBaseUser:
        match email:
            case None | "":
                raise ValueError(_("The Email field must be set."))

        email = self.normalize_email(email)

        if username := extra_fields.get("username"):
            extra_fields["username"] = self._normalize_username(username)

        if phone := extra_fields.get("phone"):
            extra_fields["phone"] = normalize_phone(phone)     # ← from utils

        extra_fields.setdefault("is_online", False)

        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)

        logger.debug("User created — email: %s", email)
        return user

    # --- Public Creators ---

    def create_user(
        self,
        email: str,
        password: str | None = None,
        **extra_fields,
    ) -> AbstractBaseUser:
        extra_fields = {
            "is_staff":     False,
            "is_superuser": False,
            "is_verified":  False,
        } | extra_fields

        return self._create_user(email, password, **extra_fields)

    def create_superuser(
        self,
        email: str,
        password: str | None = None,
        **extra_fields,
    ) -> AbstractBaseUser:
        extra_fields = {
            "is_staff":     True,
            "is_superuser": True,
            "is_verified":  True,
        } | extra_fields

        match extra_fields:
            case {"is_staff": False}:
                raise ValueError(_("Superuser must have is_staff=True."))
            case {"is_superuser": False}:
                raise ValueError(_("Superuser must have is_superuser=True."))

        return self._create_user(email, password, **extra_fields)

    def create_staffuser(
        self,
        email: str,
        password: str | None = None,
        **extra_fields,
    ) -> AbstractBaseUser:
        extra_fields = {
            "is_staff":     True,
            "is_superuser": False,
            "is_verified":  True,
        } | extra_fields

        match extra_fields:
            case {"is_staff": False}:
                raise ValueError(_("Staff user must have is_staff=True."))

        return self._create_user(email, password, **extra_fields)