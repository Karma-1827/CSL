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
CSRF_FAILURE_VIEW = "accounts.views.csrf_failure"

# How many reverse-proxy hops in front of this app add their own trustworthy
# X-Forwarded-For value (docs/VULNERABILITY_SCAN_IMPROVEMENTS.md batch 5). Defaults to 0
# ("don't trust X-Forwarded-For at all, use the real socket peer") so a bare local dev
# server or a misconfigured deployment can't have its throttle/audit-log IPs spoofed by a
# client-supplied header. Production sets this to 1 once deploy/nginx/mpts.conf.example is
# in place, since that config overwrites (not appends to) X-Forwarded-For with the real
# client IP as the single trusted hop. See accounts/forms.py::client_ip().
TRUSTED_PROXY_COUNT = int(os.getenv("DJANGO_TRUSTED_PROXY_COUNT", "0"))

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

# PostgreSQL-backed cache (docs/VULNERABILITY_SCAN_IMPROVEMENTS.md batch 5): Django's
# LocMemCache default is per-process, so login/recovery/roster-lookup throttle counts
# wouldn't be shared across Gunicorn workers and would reset on every worker restart —
# exactly the gap the plan calls out. PostgreSQL is already the only supported database
# (see CLAUDE.md), so reusing it here avoids standing up Redis for a single low-volume
# use case. The backing table is created by accounts/migrations/0016_create_cache_table.py
# via `createcachetable`, so a fresh `migrate` sets it up with no extra manual step.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache_table",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "accounts.password_validation.BilingualUserAttributeSimilarityValidator"},
    {"NAME": "accounts.password_validation.BilingualMinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "accounts.password_validation.BilingualCommonPasswordValidator"},
    {"NAME": "accounts.password_validation.BilingualNumericPasswordValidator"},
    {"NAME": "accounts.password_validation.BilingualPasswordComplexityValidator"},
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
# 2026-09-10 弱點掃描 Batch D (P1-2 item 3,使用者明確決定採用):讓 session cookie 變成
# 瀏覽器自行管理的「session cookie」(不帶 Max-Age/Expires),完全關閉瀏覽器後就會被
# 瀏覽器捨棄,下次要重新登入。伺服器端仍以上面的 SESSION_COOKIE_AGE(30 分鐘閒置)為準,
# 不受這個設定影響——兩者是疊加關係,不是取代。**已知的實際限制**:部分瀏覽器/裝置的
# 「回復先前分頁」或行動版瀏覽器背景保留機制,不會真的在「關閉」時清掉 session cookie,
# 這是瀏覽器自己的行為,Django 端無法強制生效,只能提供這個訊號給瀏覽器參考。
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
# 2026-09-10 弱點掃描 Batch D (P1-2 item 1,使用者明確決定採用 Strict):使用者已知悉並
# 接受這個取捨——已登入的使用者從外部頁面(LINE、Email 等分享的連結)點入本站時,瀏覽器
# 不會帶上這兩個 cookie,會被當成未登入導去登入頁,即使 session 其實仍然有效;使用者需
# 再次點擊站內連結或重新登入即可恢復正常,不會遺失資料或真的被登出。換來的安全提升是
# 額外一層跨站防護,疊加在既有的 Django CSRF token 檢查與 Lax 本來就會擋下的跨站 POST
# 之上。
SESSION_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_SAMESITE = "Strict"
# 2026-09-10 弱點掃描 Batch D (P1-2 item 2): flash messages used Django's default
# FallbackStorage, which tries a client-side `messages` cookie before falling back to
# the session — this is what the scan flagged as an extra cookie carrying application
# state. SessionStorage keeps messages entirely server-side (the session is already
# saved every request via SESSION_SAVE_EVERY_REQUEST above), so the `messages` cookie
# no longer exists at all; no other behavior changes for callers of django.contrib.messages.
MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"
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
