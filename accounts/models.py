from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

reader_id_validator = RegexValidator(
    regex=r"^[A-Za-z0-9_.-]{1,16}$",
    message="帳號僅可使用英數字與 _.-，長度 1 到 16 字。",
)


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, username, password, **extra_fields):
        if not username:
            raise ValueError("帳號不可為空")
        username = self.model.normalize_username(username).lower()
        user = self.model(username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, username, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("role", User.Role.READER)
        return self._create_user(username, password, **extra_fields)

    def create_superuser(self, username, password, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.ADMIN)
        extra_fields.setdefault("is_active", True)
        return self._create_user(username, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "管理員"
        READER = "reader", "閱讀者"

    first_name = None
    last_name = None
    email = None
    username = models.CharField(
        "帳號",
        max_length=16,
        unique=True,
        validators=[reader_id_validator],
        help_text="僅可使用英數字與 _.-，長度 1 到 16 字。",
    )
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.READER)
    password_changed_at = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    class Meta:
        ordering = ["username"]
        verbose_name = "帳號"
        verbose_name_plural = "帳號"

    def save(self, *args, **kwargs):
        if self.username:
            self.username = self.username.lower()
        if self.role == self.Role.ADMIN:
            self.is_staff = True
        super().save(*args, **kwargs)

    @property
    def reader_id(self) -> str:
        return self.username

    def __str__(self) -> str:
        return self.username
