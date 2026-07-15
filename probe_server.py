"""
cPanel diagnostic script — run from Setup Python App "Execute python script"
or: python probe_server.py

Does NOT print secret values — only whether env vars exist, and whether Django imports.
"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

print("=== Ghazatna backend probe ===")
print("python:", sys.version)
print("base:", BASE_DIR)
print("cwd:", os.getcwd())
print()

keys = [
    "DJANGO_ENV",
    "DJANGO_SETTINGS_MODULE",
    "DJANGO_DEBUG",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "DB_HOST",
    "DB_PORT",
    "SECRET_KEY",
    "ALLOWED_HOSTS",
    "CORS_ALLOWED_ORIGINS",
    "VIRTUAL_ENV",
]
print("--- env presence ---")
for k in keys:
    print(f"{k}: {'SET' if os.environ.get(k) else 'MISSING'}")

print()
print("--- import django ---")
try:
    import django

    print("django version:", django.get_version())
except Exception:
    print("FAILED to import django:")
    print(traceback.format_exc())
    raise SystemExit(1)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
print("DJANGO_SETTINGS_MODULE ->", os.environ.get("DJANGO_SETTINGS_MODULE"))

print()
print("--- django.setup() ---")
try:
    django.setup()
    from django.conf import settings

    print("DEBUG:", settings.DEBUG)
    print("IS production hosts:", getattr(settings, "ALLOWED_HOSTS", None))
    print("DATABASE ENGINE:", settings.DATABASES["default"]["ENGINE"])
    print("DATABASE NAME set:", bool(settings.DATABASES["default"].get("NAME")))
    print("OK: django.setup() succeeded")
except Exception:
    print("FAILED django.setup():")
    print(traceback.format_exc())
    raise SystemExit(2)

print()
print("--- database connection ---")
try:
    from django.db import connection

    connection.ensure_connection()
    print("OK: database connection works")
except Exception:
    print("FAILED database connection:")
    print(traceback.format_exc())
    raise SystemExit(3)

print()
print("=== ALL CHECKS PASSED ===")
