"""cPanel / CloudLinux Passenger entrypoint.

Do not spawn subprocesses, threads, or watchdog loops here.
Passenger loads this module once per worker process.
"""

import os
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from config.wsgi import application  # noqa: E402
