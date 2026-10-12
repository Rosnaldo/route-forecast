from django.contrib.auth.models import AbstractUser
from django.db import models

from .managers import UserManager


class User(AbstractUser):
    """
    Minimal custom user (email login), used by the Django admin.

    Kept even without authentication features: swapping AUTH_USER_MODEL after
    migrations exist is very painful, while a custom model costs nothing now
    and can gain fields later.
    """

    username = None
    email = models.EmailField(unique=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    def __str__(self) -> str:
        return self.email
