"""Push near-limit sync payloads through a running local Worker and check the 512 KiB edge.

Assumes `wrangler pages dev deploy --port <p>` is already serving; start it yourself or
pass --base-url. Registers a throwaway account, then walks payload sizes up to the limit.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

LIMIT = 512 * 1024


def request(base: str, path: str, body: dict | None = None,
            cookie: str | None = None, timeout: int = 120):
    url = base.rstrip("/") + path
    data = None
    headers = {"accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["content-type"] = "application/json"
    if cookie:
        headers["cookie"] = cookie
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, raw, resp.headers.get("set-cookie")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), e.headers.get("set-cookie")


def build_payload(target_bytes: int) -> dict:
    # 词进度在 state 下；顶层放 words 会被共享合并当成未知键丢掉。
    state = {}
    i = 0
    while i < 60000:
        state["soak%05d" % i] = {"w": i % 5, "t": 1700000000000 + i}
        i += 1
        if i % 200 == 0:
            size = len(json.dumps({"state": state}, ensure_ascii=False).encode("utf-8"))
            if size >= target_bytes:
                break
    return {"state": state, "conf": {"deck": "core"}, "progressAt": int(time.time() * 1000)}


def word_keys(payload: dict) -> list[str]:
    return sorted((payload.get("state") or {}).keys())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8799")
    args = ap.parse_args()
    base = args.base_url

    status, raw, _ = request(base, "/api/health")
    if status != 200:
        sys.exit(f"health failed: {status} {raw[:200]}")

    user = "soak%d" % int(time.time())
    status, raw, cookie = request(
        base, "/api/register", {"username": user, "password": "soak-pass-123"})
    if status != 200:
        sys.exit(f"register failed: {status} {raw[:200]}")
    cookie = (cookie or "").split(";")[0]
    if not cookie:
        sys.exit("register returned no session cookie")

    results = []
    for label, target in (("quarter", 128 * 1024), ("half", 256 * 1024),
                          ("near", 480 * 1024), ("over", 560 * 1024)):
        payload = build_payload(target)
        raw_len = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        body = {"payload": payload, "expectedUsername": user,
                "mode": "clear", "operationId": "soak-" + label}
        t0 = time.time()
        st, text, _ = request(base, "/api/state/sync", body, cookie)
        elapsed = (time.time() - t0) * 1000
        expect_ok = raw_len <= LIMIT
        results.append({
            "label": label, "bytes": raw_len, "status": st,
            "ms": round(elapsed, 1), "ok": (st == 200) if expect_ok else (st == 413),
        })
        if expect_ok and st != 200:
            sys.exit(f"{label}: {raw_len} B should sync, got {st} {text[:200]}")
        if not expect_ok and st != 413:
            sys.exit(f"{label}: {raw_len} B should be rejected, got {st} {text[:200]}")

    payload = build_payload(256 * 1024)
    body = {"payload": payload, "expectedUsername": user, "mode": "clear"}
    st, text, _ = request(base, "/api/state/sync", body, cookie)
    if st != 200:
        sys.exit(f"repeat sync failed: {st} {text[:200]}")
    first = json.loads(text).get("payload") or {}
    st, text, _ = request(base, "/api/state/sync", body, cookie)
    if st != 200:
        sys.exit(f"second repeat sync failed: {st} {text[:200]}")
    second = json.loads(text).get("payload") or {}
    keys_a = word_keys(first)
    keys_b = word_keys(second)
    if keys_a != keys_b:
        sys.exit("repeat sync changed the stored key set")

    st, text, _ = request(base, "/api/state?expectedUsername=" + user, cookie=cookie)
    if st != 200:
        sys.exit(f"state read failed: {st} {text[:200]}")
    readback = json.loads(text).get("payload") or {}
    read_keys = word_keys(readback)
    if read_keys != keys_a:
        sys.exit(f"readback mismatch: {len(read_keys)} vs {len(keys_a)} keys")

    print(json.dumps({
        "ok": True, "base_url": base, "limit_bytes": LIMIT, "user": user,
        "sizes": results, "stable_keys": len(keys_a),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
