"""
Django settings for the Skyloon AI website + employee portal.

All deployment-specific values come from environment variables, normally
provided through a `.env` file in the project root (see `.env.example`).
Designed to run on cPanel shared hosting: MySQL/MariaDB, Passenger WSGI,
WhiteNoise for static files, database cache, cron for background work.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def env_bool(name: str, default: bool = False) -> bool:
    value = env(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = env(name)
    return int(value) if value is not None else default


def env_list(name: str, default: str = "") -> list[str]:
    return [v.strip() for v in (env(name, default) or "").split(",") if v.strip()]


# ─── Core ────────────────────────────────────────────────────────────────────

DEBUG = env_bool("DEBUG", False)
SECRET_KEY = env("SECRET_KEY") or ("dev-insecure-secret-key-change-me" if DEBUG else None)
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY must be set (see .env.example)")

APP_URL = (env("APP_URL", "http://localhost:8000") or "").rstrip("/")
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", APP_URL)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "apps.core.staticfiles.SkyleonStaticFilesConfig",
    "django.contrib.sitemaps",
    "django.contrib.humanize",
    # Project apps
    "apps.core",
    "apps.accounts",
    "apps.storage",
    "apps.projects",
    "apps.training",
    "apps.assessments",
    "apps.feedback",
    "apps.practice",
    "apps.guides",
    "apps.comms",
    "apps.website",
    "apps.portal",
    "apps.backoffice",
    "apps.clients",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.AreaLanguageMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.SecurityHeadersMiddleware",
    "apps.accounts.middleware.AccountStatusMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.site",
            ],
            "builtins": ["apps.core.templatetags.ui"],
        },
    },
]

# ─── Database (MySQL / MariaDB) ─────────────────────────────────────────────

DB_ENGINE = env("DB_ENGINE", "mysql")

if DB_ENGINE == "sqlite":  # handy for quick local experiments only
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / (env("DB_NAME", "db.sqlite3") or "db.sqlite3"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": env("DB_NAME", "skyleon"),
            "USER": env("DB_USER", "skyleon"),
            "PASSWORD": env("DB_PASSWORD", ""),
            "HOST": env("DB_HOST", "localhost"),
            "PORT": env("DB_PORT", "3306"),
            "CONN_MAX_AGE": env_int("DB_CONN_MAX_AGE", 60),
            "CONN_HEALTH_CHECKS": True,
            "OPTIONS": {
                "charset": "utf8mb4",
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            },
            "TEST": {
                "NAME": env("DB_TEST_NAME", "test_skyleon"),
                "CHARSET": "utf8mb4",
                "COLLATION": "utf8mb4_unicode_ci",
            },
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ─── Cache (database cache — no Redis/Memcached needed on shared hosting) ───

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "skyleon_cache",
        "TIMEOUT": 300,
        "OPTIONS": {"MAX_ENTRIES": 20000},
    }
}

# ─── Authentication ─────────────────────────────────────────────────────────

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["apps.accounts.backends.EmailOrEmployeeIdBackend"]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "accounts:after_login"
LOGOUT_REDIRECT_URL = "website:home"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

PASSWORD_RESET_TIMEOUT = 60 * 60 * 24  # 24h (also used for invite links)

SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14  # 14 days when "remember me" is ticked
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# ─── Security (production) ──────────────────────────────────────────────────

SECURE_HTTPS = env_bool("SECURE_HTTPS", not DEBUG)
SESSION_COOKIE_SECURE = SECURE_HTTPS
CSRF_COOKIE_SECURE = SECURE_HTTPS
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", False)  # cPanel usually redirects via .htaccess
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 0)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"

# ─── Internationalisation ───────────────────────────────────────────────────

LANGUAGE_CODE = "en"
# Employee-facing pages (portal, practice lab, guides, login/signup) are shown in Bangla,
# the admin panel and the public website in English — see apps.core.middleware.AreaLanguageMiddleware.
LANGUAGES = [("en", "English"), ("bn", "বাংলা")]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = env("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

# ─── Static & uploaded files ────────────────────────────────────────────────

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / (env("STATIC_ROOT", "staticfiles") or "staticfiles")
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if not DEBUG
        else "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}
WHITENOISE_MAX_AGE = 60 * 60 * 24 * 30

# Private file storage (videos, CVs, attachments).
#   local → files on the app server under PRIVATE_STORAGE_DIR (outside public_html),
#           streamed through Django with signed, expiring URLs. Fine for small setups.
#   s3    → any S3-compatible object storage (Cloudflare R2, Backblaze B2, Wasabi,
#           AWS S3, Bunny Storage S3, MinIO). Browsers upload/stream directly from
#           the bucket with presigned URLs — recommended for production video.
STORAGE_BACKEND = env("STORAGE_BACKEND", "local")
PRIVATE_STORAGE_DIR = Path(env("PRIVATE_STORAGE_DIR", str(BASE_DIR / "storage")) or BASE_DIR / "storage")
S3_BUCKET = env("S3_BUCKET")
S3_REGION = env("S3_REGION", "auto")
S3_ENDPOINT_URL = env("S3_ENDPOINT_URL")
S3_ACCESS_KEY_ID = env("S3_ACCESS_KEY_ID")
S3_SECRET_ACCESS_KEY = env("S3_SECRET_ACCESS_KEY")
S3_ADDRESSING_STYLE = env("S3_ADDRESSING_STYLE", "auto")
MEDIA_URL_TTL_SECONDS = env_int("MEDIA_URL_TTL_SECONDS", 60 * 60 * 3)
UPLOAD_CHUNK_SIZE = env_int("UPLOAD_CHUNK_SIZE", 5 * 1024 * 1024)  # local driver chunk size
MAX_VIDEO_UPLOAD_MB = env_int("MAX_VIDEO_UPLOAD_MB", 4096)
MAX_DOCUMENT_UPLOAD_MB = env_int("MAX_DOCUMENT_UPLOAD_MB", 15)

DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# ─── Email ──────────────────────────────────────────────────────────────────
# Use the SMTP account created in cPanel → Email Accounts.

EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend" if DEBUG else "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = env("EMAIL_HOST", "localhost")
EMAIL_PORT = env_int("EMAIL_PORT", 465)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", EMAIL_PORT == 465)
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", EMAIL_PORT == 587)
EMAIL_TIMEOUT = env_int("EMAIL_TIMEOUT", 15)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "Skyloon AI <no-reply@localhost>")
SERVER_EMAIL = DEFAULT_FROM_EMAIL
# Send queued emails within the request (True) or leave them for the cron job (False).
EMAIL_SEND_IMMEDIATELY = env_bool("EMAIL_SEND_IMMEDIATELY", True)
ADMIN_NOTIFICATION_EMAILS = env_list("ADMIN_NOTIFICATION_EMAILS")

# ─── Application settings ───────────────────────────────────────────────────

EMPLOYEE_ID_PREFIX = env("EMPLOYEE_ID_PREFIX", "SKY")
# A video counts as watched when at least this % of it has actually been played.
VIDEO_COMPLETION_THRESHOLD = env_int("VIDEO_COMPLETION_THRESHOLD", 90)
CRON_SECRET = env("CRON_SECRET")

# ─── Logging ────────────────────────────────────────────────────────────────

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "[{asctime}] {levelname} {name}: {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": "INFO" if not DEBUG else "INFO"},
    "loggers": {"django.db.backends": {"level": "WARNING"}},
}
