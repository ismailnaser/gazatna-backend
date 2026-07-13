import os

from decouple import config

from .base import *  # noqa: F403

# ---------------------------------------------------------------------------
# cPanel production environment variables
# ---------------------------------------------------------------------------
# Set these in cPanel before deploying:
#   cPanel → Software → Setup Python App → select your app → Edit
#   → Environment variables (or "Add variable" in the app configuration).
#
# Required:
#   DJANGO_SETTINGS_MODULE=config.settings.prod
#   DB_NAME                   MySQL database name (e.g. cpaneluser_ghazatna)
#   DB_USER                   MySQL username
#   DB_PASSWORD               MySQL password
#   DB_HOST                   Database host (usually "localhost" on cPanel)
#
# Recommended:
#   SECRET_KEY                Long random string for Django
#   CORS_ALLOWED_ORIGINS      https://gzs.edu.ps,https://www.gzs.edu.ps
# ---------------------------------------------------------------------------

DEBUG = False

ALLOWED_HOSTS = ["gzs.edu.ps", "www.gzs.edu.ps"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ["DB_NAME"],
        "USER": os.environ["DB_USER"],
        "PASSWORD": os.environ["DB_PASSWORD"],
        "HOST": os.environ["DB_HOST"],
        "PORT": os.environ.get("DB_PORT", "3306"),
        "OPTIONS": {
            "charset": "utf8mb4",
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}

CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    default="https://gzs.edu.ps,https://www.gzs.edu.ps",
).split(",")

# Common behind reverse proxy / cPanel SSL termination
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
