"""Local load test against the running Django API (port 8001).

Does not brute-force login (login is throttled at 15/min). Logs in once,
then issues concurrent GETs and writes latency stats to stdout as JSON.
"""
from __future__ import annotations

import json
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

BASE = "http://127.0.0.1:8001"
LOGIN_USER = "ismail"
LOGIN_PASSWORD = "123456"
WORKERS = 20
REQUESTS_PER_ENDPOINT = 15


def request_json(method: str, path: str, token: str | None = None, body: dict | None = None, timeout: float = 20.0):
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            payload = res.read()
            elapsed_ms = (time.perf_counter() - started) * 1000
            return {
                "ok": 200 <= res.status < 400,
                "status": res.status,
                "ms": round(elapsed_ms, 1),
                "bytes": len(payload),
                "path": path,
            }
    except urllib.error.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        return {
            "ok": False,
            "status": exc.code,
            "ms": round(elapsed_ms, 1),
            "bytes": len(exc.read() or b""),
            "path": path,
        }
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        return {
            "ok": False,
            "status": 0,
            "ms": round(elapsed_ms, 1),
            "bytes": 0,
            "path": path,
            "error": str(exc),
        }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    times = [r["ms"] for r in rows]
    times.sort()
    n = len(times) or 1

    def pct(p: float) -> float:
        idx = min(n - 1, max(0, int(round((p / 100) * (n - 1)))))
        return times[idx]

    ok = sum(1 for r in rows if r["ok"])
    return {
        "count": len(rows),
        "ok": ok,
        "errors": len(rows) - ok,
        "error_rate_pct": round(100 * (len(rows) - ok) / n, 2),
        "min_ms": min(times) if times else 0,
        "p50_ms": pct(50),
        "p95_ms": pct(95),
        "p99_ms": pct(99),
        "max_ms": max(times) if times else 0,
        "mean_ms": round(statistics.fmean(times), 1) if times else 0,
        "rps": round(len(rows) / (sum(times) / 1000 / WORKERS), 1) if times else 0,
    }


def run_batch(token: str | None, path: str, workers: int, count: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(request_json, "GET", path, token) for _ in range(count)]
        for fut in as_completed(futs):
            rows.append(fut.result())
    return rows


def main() -> None:
    login = request_json("POST", "/api/auth/login/", body={"username": LOGIN_USER, "password": LOGIN_PASSWORD})
    if not login["ok"]:
        raise SystemExit(f"login failed: {login}")

    token_req = urllib.request.Request(
        f"{BASE}/api/auth/login/",
        data=json.dumps({"username": LOGIN_USER, "password": LOGIN_PASSWORD}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(token_req, timeout=20) as res:
        token = json.loads(res.read().decode())["access"]

    scenarios = [
        ("public_site_settings", None, "/api/site-settings/"),
        ("public_news", None, "/api/content/news/"),
        ("admin_grades", token, "/api/admin/grades/"),
        ("admin_classes", token, "/api/admin/classes/"),
        ("admin_schedules", token, "/api/admin/schedules/?type=class"),
        ("admin_analytics_meta", token, "/api/admin/analytics/?section=meta"),
        ("auth_me", token, "/api/auth/me/"),
    ]

    results = []
    wall_start = time.perf_counter()
    for name, auth, path in scenarios:
        rows = run_batch(auth, path, WORKERS, REQUESTS_PER_ENDPOINT)
        stats = summarize(rows)
        stats["name"] = name
        stats["path"] = path
        statuses = {}
        for row in rows:
            key = str(row["status"])
            statuses[key] = statuses.get(key, 0) + 1
        stats["statuses"] = statuses
        results.append(stats)
        print(f"{name}: p50={stats['p50_ms']}ms p95={stats['p95_ms']}ms errors={stats['errors']}", flush=True)

    mixed_paths = [
        "/api/site-settings/",
        "/api/admin/grades/",
        "/api/admin/classes/",
        "/api/admin/schedules/?type=class",
        "/api/auth/me/",
    ]
    mixed_rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = []
        for i in range(WORKERS * 5):
            path = mixed_paths[i % len(mixed_paths)]
            auth = None if path.startswith("/api/site-settings") else token
            futs.append(pool.submit(request_json, "GET", path, auth))
        for fut in as_completed(futs):
            mixed_rows.append(fut.result())
    mixed = summarize(mixed_rows)
    mixed["name"] = "mixed_authenticated_burst"
    mixed["path"] = "mixed"
    results.append(mixed)

    report = {
        "base": BASE,
        "workers": WORKERS,
        "requests_per_endpoint": REQUESTS_PER_ENDPOINT,
        "wall_seconds": round(time.perf_counter() - wall_start, 2),
        "scenarios": results,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
