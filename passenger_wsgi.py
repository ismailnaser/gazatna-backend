"""
cPanel / Phusion Passenger entry point for Django.
"""
import os
import sys
import traceback
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
ERROR_LOG = LOG_DIR / "passenger_error.log"


def _log(msg: str) -> None:
    try:
        with ERROR_LOG.open("a", encoding="utf-8") as fh:
            fh.write(msg.rstrip() + "\n")
    except OSError:
        pass


def _attach_virtualenv() -> None:
    """Prepend cPanel virtualenv site-packages so Passenger finds Django."""
    attached = []

    def add_site(site: Path) -> None:
        site_str = str(site)
        if site.is_dir() and site_str not in sys.path:
            sys.path.insert(0, site_str)
            attached.append(site_str)

    venv = os.environ.get("VIRTUAL_ENV", "").strip()
    if venv:
        for site in Path(venv).glob("lib/python*/site-packages"):
            add_site(site)

    # cPanel usually stores envs under ~/virtualenv/...
    home = Path.home()
    roots = [home / "virtualenv", BASE_DIR.parent / "virtualenv"]
    for root in roots:
        if not root.exists():
            continue
        # Prefer paths mentioning this project name
        matches = sorted(root.rglob("site-packages"), key=lambda p: ("gazatna-backend" not in str(p), len(str(p))))
        for site in matches[:8]:
            add_site(site)

    if attached:
        _log("Attached site-packages:\n  - " + "\n  - ".join(attached))
    else:
        _log("WARNING: no virtualenv site-packages attached; relying on Passenger env")


if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

_attach_virtualenv()

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

force_script = os.environ.get("FORCE_SCRIPT_NAME", "").strip()
if force_script:
    os.environ["SCRIPT_NAME"] = force_script

try:
    from django.core.wsgi import get_wsgi_application

    application = get_wsgi_application()
    _log("Django WSGI application loaded OK")
except Exception:
    _log("FAILED to start Django WSGI:\n" + traceback.format_exc())
    raise
