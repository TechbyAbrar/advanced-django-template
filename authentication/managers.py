import logging

from django.contrib.auth.base_user import BaseUserManager, AbstractBaseUser
from django.utils.translation import gettext_lazy as _

from authentication.utils import normalize_phone

logger = logging.getLogger(__name__)


class UserManager(BaseUserManager):
    @staticmethod
    def _normalize_username(username: str) -> str:
        return username.lower().strip()

    def _create_user(
        self,
        email: str | None = None,
        password: str | None = None,
        **extra_fields,
    ) -> AbstractBaseUser:
        email = self.normalize_email(email) if email else None

        if username := extra_fields.get("username"):
            extra_fields["username"] = self._normalize_username(username)

        if phone := extra_fields.get("phone"):
            extra_fields["phone"] = normalize_phone(phone)

        if not email and not extra_fields.get("phone"):
            raise ValueError(_("Either email or phone must be set."))

        extra_fields.setdefault("is_online", False)

        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)

        logger.debug(
            "User created — email: %s, phone: %s",
            email,
            extra_fields.get("phone"),
        )
        return user

    def create_user(
        self,
        email: str | None = None,
        password: str | None = None,
        **extra_fields,
    ) -> AbstractBaseUser:
        extra_fields = {
            "is_staff": False,
            "is_superuser": False,
            "is_verified": False,
        } | extra_fields

        return self._create_user(email=email, password=password, **extra_fields)

    def create_superuser(
        self,
        email: str,
        password: str | None = None,
        **extra_fields,
    ) -> AbstractBaseUser:
        if not email:
            raise ValueError(_("Superuser must have an email address."))

        extra_fields = {
            "is_staff": True,
            "is_superuser": True,
            "is_verified": True,
        } | extra_fields

        if extra_fields.get("is_staff") is not True:
            raise ValueError(_("Superuser must have is_staff=True."))
        if extra_fields.get("is_superuser") is not True:
            raise ValueError(_("Superuser must have is_superuser=True."))

        return self._create_user(email=email, password=password, **extra_fields)

    def create_staffuser(
        self,
        email: str | None = None,
        password: str | None = None,
        **extra_fields,
    ) -> AbstractBaseUser:
        extra_fields = {
            "is_staff": True,
            "is_superuser": False,
            "is_verified": True,
        } | extra_fields

        if extra_fields.get("is_staff") is not True:
            raise ValueError(_("Staff user must have is_staff=True."))

        return self._create_user(email=email, password=password, **extra_fields)