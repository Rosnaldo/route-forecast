from django.contrib.auth.base_user import BaseUserManager


class UserManager(BaseUserManager):
    """Custom manager because the User logs in with email, not username."""

    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra):
        if not email:
            raise ValueError("Email is required")
        user = self.model(email=self.normalize_email(email), **extra)
        user.set_password(password)  # hashes; never store raw passwords
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra):
        extra |= {"is_staff": True, "is_superuser": True}
        return self._create_user(email, password, **extra)
