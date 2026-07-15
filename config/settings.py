import os
from datetime import timedelta
from pathlib import Path

from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# بيئة التشغيل: local (افتراضي) أو production
# ---------------------------------------------------------------------------
# محلياً: لا تحتاج تعيين شي — SQLite + DEBUG=True
#
# على cPanel (السيرفر):
#   cPanel → Software → Setup Python App → Edit → Environment variables
#
#   DJANGO_ENV=production
#   DB_NAME=...
#   DB_USER=...
#   DB_PASSWORD=...
#   DB_HOST=localhost
#   SECRET_KEY=...
#   CORS_ALLOWED_ORIGINS=https://gzs.edu.ps,https://www.gzs.edu.ps
# ---------------------------------------------------------------------------

DJANGO_ENV = os.environ.get("DJANGO_ENV", "local").strip().lower()
IS_PRODUCTION = DJANGO_ENV in ("production", "prod")

# Temporary diagnosis on cPanel: set DJANGO_DEBUG=1 in Environment variables
# (turn off after fixing — never leave debug on public production).
DEBUG = not IS_PRODUCTION or os.environ.get("DJANGO_DEBUG", "").strip() in ("1", "true", "True")

SECRET_KEY = config("SECRET_KEY", default="django-insecure-ghazatna-dev-key-change-in-production")
if IS_PRODUCTION and SECRET_KEY.startswith("django-insecure-"):
    # Fail loudly in logs rather than silently using the insecure default.
    pass

INSTALLED_APPS = [
    "config.apps.ProjectConfig",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "accounts",
    "academics",
    "staff",
    "assignments",
    "finance",
    "content",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
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
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

if IS_PRODUCTION:
    raw_hosts = config(
        "ALLOWED_HOSTS",
        default="gzs.edu.ps,www.gzs.edu.ps,api.gzs.edu.ps,.edu.ps,localhost,127.0.0.1",
    )
    ALLOWED_HOSTS = [h.strip() for h in raw_hosts.split(",") if h.strip()]
    # Emergency override for diagnosis only: ALLOWED_HOSTS=*
    if ALLOWED_HOSTS == ["*"]:
        ALLOWED_HOSTS = ["*"]

    def _required_env(name: str) -> str:
        value = os.environ.get(name, "").strip()
        if not value:
            raise RuntimeError(
                f"Missing required environment variable {name}. "
                "Set it in Setup Python App → Environment variables, then Restart."
            )
        return value

    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": _required_env("DB_NAME"),
            "USER": _required_env("DB_USER"),
            "PASSWORD": _required_env("DB_PASSWORD"),
            "HOST": _required_env("DB_HOST"),
            "PORT": os.environ.get("DB_PORT", "3306"),
            "OPTIONS": {
                "charset": "utf8mb4",
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }
    CORS_ALLOWED_ORIGINS = [
        o.strip()
        for o in config(
            "CORS_ALLOWED_ORIGINS",
            default="https://gzs.edu.ps,https://www.gzs.edu.ps",
        ).split(",")
        if o.strip()
    ]
    CSRF_TRUSTED_ORIGINS = [
        o.strip()
        for o in config(
            "CSRF_TRUSTED_ORIGINS",
            default="https://gzs.edu.ps,https://www.gzs.edu.ps",
        ).split(",")
        if o.strip()
    ]
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
else:
    ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1").split(",")
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
    CORS_ALLOWED_ORIGINS = config(
        "CORS_ALLOWED_ORIGINS",
        default="http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000,http://127.0.0.1:3001",
    ).split(",")
    CORS_ALLOW_ALL_ORIGINS = True

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ar"
TIME_ZONE = "Asia/Gaza"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "static"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Ensure writable dirs exist on cPanel (avoids 500 from cache/file backends)
(BASE_DIR / "cache").mkdir(exist_ok=True)
(BASE_DIR / "logs").mkdir(exist_ok=True)
(BASE_DIR / "media").mkdir(exist_ok=True)

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": BASE_DIR / "cache",
        "TIMEOUT": 300,
        "OPTIONS": {"MAX_ENTRIES": 5000},
    }
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "file": {
            "class": "logging.FileHandler",
            "filename": str(BASE_DIR / "logs" / "django.log"),
            "formatter": "verbose",
        },
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["file", "console"],
        "level": "INFO",
    },
    "loggers": {
        "django.request": {
            "handlers": ["file", "console"],
            "level": "ERROR",
            "propagate": False,
        },
        "django.security": {
            "handlers": ["file", "console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=12),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
}

CORS_ALLOW_CREDENTIALS = True
