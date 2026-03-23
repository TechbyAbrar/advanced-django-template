#auth/backends.py
import logging

from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from django.db.models import Q
from django.http import HttpRequest

User = get_user_model()
logger = logging.getLogger(__name__)


class EmailPhoneUsernameBackend(ModelBackend):
    def authenticate(
        self,
        request: HttpRequest | None,
        username: str | None = None,
        password: str | None = None,
        **kwargs,
    ) -> AbstractBaseUser | None:
        if username is None or password is None:
            return None

        try:
            user: AbstractBaseUser = User.objects.get(
                Q(email__iexact=username) | Q(phone=username) | Q(username__iexact=username)
            )
        except User.DoesNotExist:
            User().check_password(password)
            logger.warning("Login failed — no user found for identifier: %s", username)
            return None
        except User.MultipleObjectsReturned:
            logger.warning("Login failed — multiple users found for identifier: %s", username)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user

        logger.warning("Login failed — invalid password for identifier: %s", username)
        return None