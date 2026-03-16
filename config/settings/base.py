import os
from pathlib import Path

from config.versioning import read_version

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value is not None else default


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value is not None else default


def env_list(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-secret-key-change-me")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1", "testserver"])
CSRF_TRUSTED_ORIGINS = env_list(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    [
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ],
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "accounts",
    "backoffice",
    "library",
    "reader",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "config.context_processors.app_meta",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "zh-hant"
TIME_ZONE = "Asia/Taipei"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

AUTH_USER_MODEL = "accounts.User"
APP_VERSION = read_version(BASE_DIR)
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
]

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# anti7ocr / watermark settings
ANTI_OCR_FONT_PATHS = env_list(
    "ANTI_OCR_FONT_PATH",
    [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "C:/Windows/Fonts/msjh.ttc",
        "C:/Windows/Fonts/msjhbd.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/mingliu.ttc",
        "C:/Windows/Fonts/simsun.ttc",
    ],
)
WATERMARK_PASSWORD_IMG = env_int("WATERMARK_PASSWORD_IMG", 2580)
WATERMARK_PASSWORD_WM = env_int("WATERMARK_PASSWORD_WM", 4307)
WATERMARK_FIXED_LENGTH = env_int("WATERMARK_FIXED_LENGTH", 32)
VISIBLE_WATERMARK_DELTA_L = env_int("VISIBLE_WATERMARK_DELTA_L", 0)
VISIBLE_WATERMARK_DELTA_A = env_int("VISIBLE_WATERMARK_DELTA_A", 7)
VISIBLE_WATERMARK_DELTA_B = env_int("VISIBLE_WATERMARK_DELTA_B", -7)
VISIBLE_WATERMARK_BACKGROUND_THRESHOLD = env_int("VISIBLE_WATERMARK_BACKGROUND_THRESHOLD", 145)
VISIBLE_WATERMARK_DESKTOP_FONT_SIZE = env_int("VISIBLE_WATERMARK_DESKTOP_FONT_SIZE", 19)
VISIBLE_WATERMARK_MOBILE_FONT_SIZE = env_int("VISIBLE_WATERMARK_MOBILE_FONT_SIZE", 16)
VISIBLE_WATERMARK_DESKTOP_ROW_SPACING = env_int("VISIBLE_WATERMARK_DESKTOP_ROW_SPACING", 56)
VISIBLE_WATERMARK_MOBILE_ROW_SPACING = env_int("VISIBLE_WATERMARK_MOBILE_ROW_SPACING", 48)
VISIBLE_WATERMARK_TEXT_GAP = env_int("VISIBLE_WATERMARK_TEXT_GAP", 44)
VISIBLE_WATERMARK_MASK_OPACITY = env_float("VISIBLE_WATERMARK_MASK_OPACITY", 0.18)
VISIBLE_WATERMARK_MASK_BLUR = env_float("VISIBLE_WATERMARK_MASK_BLUR", 1.0)
VISIBLE_WATERMARK_CARRIER_BLOCK = env_int("VISIBLE_WATERMARK_CARRIER_BLOCK", 2)
VISIBLE_WATERMARK_BLUE_BITS = env_int("VISIBLE_WATERMARK_BLUE_BITS", 3)
VISIBLE_WATERMARK_GREEN_BITS = env_int("VISIBLE_WATERMARK_GREEN_BITS", 2)
VISIBLE_WATERMARK_ROTATION = env_int("VISIBLE_WATERMARK_ROTATION", 28)
DAILY_CACHE_RETENTION_DAYS = env_int("DAILY_CACHE_RETENTION_DAYS", 3)
READER_IMAGE_TOKEN_MAX_AGE = env_int("READER_IMAGE_TOKEN_MAX_AGE", 900)
LOGIN_FAILURE_WINDOW_SECONDS = env_int("LOGIN_FAILURE_WINDOW_SECONDS", 900)
LOGIN_FAILURE_COOLDOWN_SECONDS = env_int("LOGIN_FAILURE_COOLDOWN_SECONDS", 300)
ACCOUNT_LOCK_SECONDS = env_int("ACCOUNT_LOCK_SECONDS", 1800)

# Celery
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BEAT_SCHEDULE = {
    "cleanup-daily-cache": {
        "task": "library.tasks.cleanup_daily_cache_task",
        "schedule": 60 * 60 * 24,
    },
}

# DRF
REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Who-Is-Rat API",
    "VERSION": APP_VERSION,
    "DESCRIPTION": "Chinese novel content protection platform API",
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "structured": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "structured",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {"level": "WARNING"},
        "celery": {"level": "INFO"},
    },
}
