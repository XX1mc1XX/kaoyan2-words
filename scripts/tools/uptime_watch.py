"""Poll the production deployment and shout when it degrades.

Checks the same surfaces deploy.py verifies at release time, but on a loop: health,
build-meta identity, the shell HTML, and the app asset. Designed for a local cron or
a Task Scheduler job; set KY_ALERT_WEBHOOK to POST failures anywhere that accepts JSON.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "https://kaoyan2-words.pages.dev/"


def fetch(url: str, timeout: int = 25, retries: int = 2) -> tuple[int, bytes, dict]:
    # 生产上首页偶发读超时（实测 3 次里 2 次 45s 超时、第 3 次 1.6s 返回），
    # 单次失败就告警会天天误报，所以同一 URL 先重试再判死。
    last: tuple[int, bytes, dict] = (0, b"", {})
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers={
            "user-agent": "ky-uptime/1.0",
            "cache-control": "no-cache",
            "connection": "close",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as e:
            last = (e.code, e.read(), dict(e.headers))
            if e.code < 500:
                return last
        except Exception as exc:
            last = (0, str(exc).encode(), {})
        if attempt < retries:
            time.sleep(2)
    return last


def probe(base: str) -> dict:
    base = base.rstrip("/") + "/"
    problems: list[str] = []
    detail: dict = {}

    st, body, _ = fetch(base + "api/health")
    detail["health_status"] = st
    try:
        health = json.loads(body.decode("utf-8", "replace")) if st == 200 else {}
    except json.JSONDecodeError:
        health = {}
    detail["health"] = health
    if st != 200 or not health.get("ok") or not health.get("database"):
        problems.append("health")

    st, body, _ = fetch(base + "build-meta.json")
    meta = {}
    if st == 200:
        try:
            meta = json.loads(body.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            meta = {}
    detail["build"] = meta.get("build")
    detail["app_asset"] = meta.get("app_asset")
    if st != 200 or not meta.get("build") or not meta.get("app_asset"):
        problems.append("build-meta")

    st, body, _ = fetch(base)
    html = body.decode("utf-8", "replace") if st == 200 else ""
    detail["index_status"] = st
    detail["index_bytes"] = len(html)
    if st != 200 or "<html" not in html.lower():
        problems.append("index")

    app = (meta.get("app_asset") or "").lstrip("./")
    if app:
        st, body, _ = fetch(base + app)
        detail["app_status"] = st
        detail["app_bytes"] = len(body)
        if st != 200 or len(body) < 10000:
            problems.append("app-asset")

    return {"ok": not problems, "problems": problems, "detail": detail}


def alert(payload: dict) -> None:
    hook = os.environ.get("KY_ALERT_WEBHOOK")
    if not hook:
        return
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(hook, data=data, headers={"content-type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as exc:
        print("webhook failed: %s" % exc, file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get("KY_UPTIME_BASE", DEFAULT_BASE))
    ap.add_argument("--interval", type=int, default=300, help="seconds between probes")
    ap.add_argument("--once", action="store_true", help="single probe, then exit")
    ap.add_argument("--fail-after", type=int, default=3, help="consecutive failures before alerting")
    args = ap.parse_args()

    streak = 0
    while True:
        result = probe(args.base_url)
        result["at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        result["base_url"] = args.base_url
        if result["ok"]:
            print(json.dumps({"ok": True, "at": result["at"],
                              "build": result["detail"].get("build")}, ensure_ascii=False))
            streak = 0
        else:
            streak += 1
            result["streak"] = streak
            print(json.dumps(result, ensure_ascii=False))
            if streak >= args.fail_after:
                alert(result)
        if args.once:
            return 0 if result["ok"] else 1
        time.sleep(max(30, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
