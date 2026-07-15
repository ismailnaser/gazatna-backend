"""
DIAGNOSTIC passenger entry for cPanel.

Goal: prove whether Passenger is actually loading THIS file.
It does NOT import Django. It only:
  1) writes PASSENGER_HIT.txt next to this file
  2) returns a clear HTML page

After you confirm the page says PASSENGER OK:
  replace this file with the real passenger_wsgi (or set
  GHAZATNA_PASSENGER_DIAG=0 and restore full app).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
HIT_FILE = BASE_DIR / "PASSENGER_HIT.txt"
TMP_HIT = Path("/tmp") / "ghazatna_passenger_hit.txt"


def _write(path: Path, text: str) -> str:
    try:
        path.write_text(text, encoding="utf-8")
        return f"OK wrote {path}"
    except Exception as exc:
        return f"FAIL {path}: {exc}"


stamp = datetime.utcnow().isoformat() + "Z"
payload = "\n".join(
    [
        f"time={stamp}",
        f"file={__file__}",
        f"base={BASE_DIR}",
        f"cwd={os.getcwd()}",
        f"python={sys.version}",
        f"DJANGO_ENV={os.environ.get('DJANGO_ENV', '')!r}",
        f"VIRTUAL_ENV={os.environ.get('VIRTUAL_ENV', '')!r}",
        f"PASSENGER_APP_ENV={os.environ.get('PASSENGER_APP_ENV', '')!r}",
    ]
)

write_results = [
    _write(HIT_FILE, payload + "\n"),
    _write(TMP_HIT, payload + "\n"),
]


def application(environ, start_response):
    host = environ.get("HTTP_HOST", "")
    uri = environ.get("SCRIPT_NAME", "") + environ.get("PATH_INFO", "")
    body = f"""<!doctype html>
<html lang="ar" dir="rtl">
<head><meta charset="utf-8"><title>PASSENGER OK</title></head>
<body style="font-family:sans-serif;padding:24px">
  <h1 style="color:green">PASSENGER OK</h1>
  <p>إذا شايف هالرسالة، ملف <code>passenger_wsgi.py</code> شغّال على السيرفر.</p>
  <ul>
    <li><b>HTTP_HOST:</b> {host}</li>
    <li><b>URI:</b> {uri}</li>
    <li><b>BASE_DIR:</b> {BASE_DIR}</li>
    <li><b>__file__:</b> {__file__}</li>
    <li><b>python:</b> {sys.version.split()[0]}</li>
  </ul>
  <h2>كتابة الملف</h2>
  <pre>{chr(10).join(write_results)}</pre>
  <p>شوف كمان ملف <code>PASSENGER_HIT.txt</code> جنب passenger_wsgi.py في File Manager.</p>
</body></html>
""".encode("utf-8")
    start_response(
        "200 OK",
        [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(body)))],
    )
    return [body]
