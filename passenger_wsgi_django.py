"""
Real Django Passenger entry — use AFTER diagnostic passenger_wsgi proves OK.

On server:
  cp passenger_wsgi_django.py passenger_wsgi.py
  then Restart Python App
"""
from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
try:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    BOOT_LOG = LOG_DIR / "boot.log"
except Exception:
    BOOT_LOG = BASE_DIR / "boot.log"


def _boot(msg: str) -> None:
    try:
        with BOOT_LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"[{datetime.utcnow().isoformat()}Z] {msg}\n")
            fh.flush()
    except Exception:
        pass


_boot(f"start base={BASE_DIR} py={sys.version.split()[0]}")

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

venv = (os.environ.get("VIRTUAL_ENV") or "").strip()
if venv:
    for site in Path(venv).glob("lib/python*/site-packages"):
        s = str(site)
        if s not in sys.path:
            sys.path.insert(0, s)
            _boot(f"attached {s}")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
force_script = (os.environ.get("FORCE_SCRIPT_NAME") or "").strip()
if force_script:
    os.environ["SCRIPT_NAME"] = force_script

_LOAD_ERROR = None
try:
    from django.core.wsgi import get_wsgi_application

    application = get_wsgi_application()
    _boot("Django OK")
except Exception:
    _LOAD_ERROR = traceback.format_exc()
    _boot("Django FAIL\n" + _LOAD_ERROR)

    def application(environ, start_response):  # type: ignore[no-redef]
        body = (
            "<h1>Django failed to start</h1><pre style='white-space:pre-wrap'>"
            + _LOAD_ERROR
            + "</pre>"
        ).encode("utf-8")
        start_response("500 Internal Server Error", [("Content-Type", "text/html; charset=utf-8")])
        return [body]
