"""Defensive security checks against the local API — no exploit payloads."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8001"
FRONT = "http://127.0.0.1:3001"


def fetch(url: str, method="GET", headers=None, body=None, timeout=12):
    data = None if body is None else json.dumps(body).encode("utf-8")
    hdrs = {"Accept": "application/json"}
    if body is not None:
        hdrs["Content-Type"] = "application/json"
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return {
                "status": res.status,
                "headers": {k.lower(): v for k, v in res.headers.items()},
                "body": res.read()[:4000].decode("utf-8", "replace"),
            }
    except urllib.error.HTTPError as exc:
        return {
            "status": exc.code,
            "headers": {k.lower(): v for k, v in exc.headers.items()},
            "body": exc.read()[:4000].decode("utf-8", "replace"),
        }
    except Exception as exc:
        return {"status": 0, "headers": {}, "body": str(exc)}


def login(username: str, password: str) -> str | None:
    res = fetch(f"{BASE}/api/auth/login/", "POST", body={"username": username, "password": password})
    if res["status"] != 200:
        return None
    try:
        return json.loads(res["body"]).get("access")
    except json.JSONDecodeError:
        return None


def main() -> None:
    findings = []

    settings = fetch(f"{BASE}/api/site-settings/")
    findings.append(
        {
            "id": "public-site-settings",
            "severity": "info",
            "title": "إعدادات الموقع عامة بدون مصادقة",
            "detail": f"GET /api/site-settings/ -> {settings['status']}",
            "pass": settings["status"] == 200,
        }
    )

    students = fetch(f"{BASE}/api/admin/students/")
    findings.append(
        {
            "id": "admin-unauth",
            "severity": "high" if students["status"] not in (401, 403) else "info",
            "title": "قائمة الطلاب بدون توكن",
            "detail": f"GET /api/admin/students/ -> {students['status']}",
            "pass": students["status"] in (401, 403),
        }
    )

    parent_token = login("2026001", "123456")
    parent_admin = fetch(
        f"{BASE}/api/admin/students/",
        headers={"Authorization": f"Bearer {parent_token}"} if parent_token else None,
    )
    findings.append(
        {
            "id": "parent-cannot-admin",
            "severity": "high" if parent_admin["status"] not in (401, 403) else "info",
            "title": "ولي الأمر لا يصل لإدارة الطلاب",
            "detail": f"parent GET /api/admin/students/ -> {parent_admin['status']}",
            "pass": bool(parent_token) and parent_admin["status"] in (401, 403),
        }
    )

    teacher_token = login("guide_teacher", "123456")
    teacher_parent = fetch(
        f"{BASE}/api/parent/fees/",
        headers={"Authorization": f"Bearer {teacher_token}"} if teacher_token else None,
    )
    findings.append(
        {
            "id": "teacher-cannot-parent",
            "severity": "high" if teacher_parent["status"] not in (401, 403) else "info",
            "title": "المعلم لا يصل لمالية ولي الأمر",
            "detail": f"teacher GET /api/parent/fees/ -> {teacher_parent['status']}",
            "pass": bool(teacher_token) and teacher_parent["status"] in (401, 403),
        }
    )

    django_headers = fetch(f"{BASE}/api/site-settings/")["headers"]
    next_headers = fetch(f"{FRONT}/login")["headers"]
    interesting = [
        "x-frame-options",
        "x-content-type-options",
        "content-security-policy",
        "strict-transport-security",
        "referrer-policy",
        "permissions-policy",
        "access-control-allow-origin",
    ]
    header_report = {
        "django": {k: django_headers.get(k) for k in interesting},
        "next": {k: next_headers.get(k) for k in interesting},
    }

    findings.append(
        {
            "id": "x-frame-options",
            "severity": "medium" if "x-frame-options" not in django_headers else "info",
            "title": "X-Frame-Options على الباكند",
            "detail": django_headers.get("x-frame-options") or "مفقود",
            "pass": "x-frame-options" in django_headers,
        }
    )
    findings.append(
        {
            "id": "nosniff",
            "severity": "medium" if "x-content-type-options" not in django_headers else "info",
            "title": "X-Content-Type-Options",
            "detail": django_headers.get("x-content-type-options") or "مفقود محلياً (يُفعَّل في الإنتاج)",
            "pass": "x-content-type-options" in django_headers,
        }
    )
    findings.append(
        {
            "id": "csp",
            "severity": "medium",
            "title": "Content-Security-Policy",
            "detail": next_headers.get("content-security-policy")
            or django_headers.get("content-security-policy")
            or "not set on either side",
            "pass": False,
        }
    )

    anon_media = fetch(f"{BASE}/media/students/documents/not-a-real-file.pdf")
    findings.append(
        {
            "id": "anon-private-media",
            "severity": "high" if anon_media["status"] == 200 else "info",
            "title": "Private student document without auth",
            "detail": f"GET /media/students/documents/not-a-real-file.pdf -> {anon_media['status']}",
            "pass": anon_media["status"] in (403, 404),
        }
    )

    print(json.dumps({"findings": findings, "headers": header_report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
