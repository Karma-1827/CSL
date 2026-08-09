import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# Only ever used when DJANGO_SECRET_KEY is unset. The fail-closed check below refuses to
# start with DEBUG=False if this literal value is still in effect, so it can never reach
# a production deployment even by accident.
DEV_SECRET_KEY_FALLBACK = "dev-only-change-before-deployment-csl-tutoring-system"

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", DEV_SECRET_KEY_FALLBACK)
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "tutoring",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.PrivateNoStoreMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "accounts.middleware.ContentSecurityPolicyMiddleware",
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
                "accounts.context_processors.class_documents_menu",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "qiangqiang"),
        "USER": os.getenv("POSTGRES_USER", "qiangqiang"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", ""),
        "HOST": os.getenv("POSTGRES_HOST", ""),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "zh-hant"
TIME_ZONE = "Asia/Taipei"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "accounts:dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"

# 30 分鐘閒置逾時自動登出(資通系統防護基準檢核表「中級」第 5、6 項);
# SESSION_SAVE_EVERY_REQUEST 讓有操作的使用者每次請求都重新計時，只有真正閒置才會逾時。
SESSION_COOKIE_AGE = 60 * 30
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
FILE_UPLOAD_MAX_MEMORY_SIZE = 1_500_000
DATA_UPLOAD_MAX_MEMORY_SIZE = 2_000_000

if not DEBUG:
    # Fail closed (docs/VULNERABILITY_SCAN_IMPROVEMENTS.md batch 2): refuse to start rather
    # than silently run production with dev-grade secrets, credentials, or host settings.
    if not os.getenv("DJANGO_SECRET_KEY") or SECRET_KEY == DEV_SECRET_KEY_FALLBACK:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be set to a real, unique production secret when "
            "DJANGO_DEBUG=0; the development fallback key is not permitted."
        )
    if not DATABASES["default"]["PASSWORD"]:
        raise ImproperlyConfigured("POSTGRES_PASSWORD must not be blank when DJANGO_DEBUG=0.")
    _effective_hosts = {host.lower() for host in ALLOWED_HOSTS}
    if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS or _effective_hosts <= {"localhost", "127.0.0.1"}:
        raise ImproperlyConfigured(
            "DJANGO_ALLOWED_HOSTS must list real production hostnames when DJANGO_DEBUG=0; "
            "it cannot be empty, '*', or only localhost/127.0.0.1."
        )

    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31_536_000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    # Trustworthy only if the reverse proxy strips any client-supplied X-Forwarded-Proto
    # before setting its own (see docs/DEPLOY.md); Django has no way to verify this itself.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
