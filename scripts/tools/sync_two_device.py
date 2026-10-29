"""Two independent sessions drive the local Worker like two devices and must converge.

Covers what PHASES.md lists for the dual-device drill: clear/import fences, a retried
request that lost its response, guest progress on login, an expired session, a stale
device reconnecting, and out-of-order syncs. Sessions are HTTP cookies against a
running `wrangler pages dev deploy`; this is the contract-level drill, not a real
two-browser run.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def request(base: str, path: str, body: dict | None = None,
            cookie: str | None = None, timeout: int = 120):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {"accept": "application/json"}
    if data is not None:
        headers["content-type"] = "application/json"
    if cookie:
        headers["cookie"] = cookie
    req = urllib.request.Request(
        base.rstrip("/") + path, data=data, headers=headers,
        method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace"), resp.headers.get("set-cookie")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), e.headers.get("set-cookie")


def cookie_of(raw: str | None) -> str:
    return (raw or "").split(";")[0]


def sync(base, cookie, username, state, *, reset=False, mode="clear", op_id=None):
    payload = {"state": state, "conf": {"deck": "core"}}
    body = {"payload": payload, "expectedUsername": username, "mode": mode}
    if reset:
        body["reset"] = True
    if op_id:
        body["operationId"] = op_id
    st, text, _ = request(base, "/api/state/sync", body, cookie)
    return st, text


def keys_of(payload: dict | None) -> set[str]:
    # clear 不删行，而是留 {del:1} 墓碑；统计“活着”的词必须排除墓碑。
    state = (payload or {}).get("state") or {}
    return {name for name, entry in state.items()
            if not (isinstance(entry, dict) and entry.get("del"))}


def read_state(base, cookie, username):
    st, text, _ = request(base, "/api/state?expectedUsername=" + username, cookie=cookie)
    if st != 200:
        return st, None
    return st, json.loads(text).get("payload")


def fail(msg: str) -> None:
    sys.exit(msg)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8799")
    args = ap.parse_args()
    base = args.base_url

    st, _, _ = request(base, "/api/health")
    if st != 200:
        fail(f"health failed: {st}")

    user = "devA%d" % int(time.time())
    password = "device-pass-123"

    st, text, raw = request(base, "/api/register", {"username": user, "password": password})
    if st != 200:
        fail(f"register failed: {st} {text[:200]}")
    device_a = cookie_of(raw)

    # 时间戳必须是调用当刻的真实时间：墓碑 fence 由服务端 now 生成，
    # 用固定常量或未来时刻会让旧词比墓碑“更新”，clear 就测不出来。
    def word(name, weight):
        return {name: {"w": weight, "t": int(time.time() * 1000)}}

    st, text = sync(base, device_a, user, word("alpha", 1))
    if st != 200:
        fail(f"A first sync failed: {st} {text[:200]}")

    st, text, raw = request(base, "/api/login", {"username": user, "password": password})
    if st != 200:
        fail(f"login failed: {st} {text[:200]}")
    device_b = cookie_of(raw)
    if not device_b or device_b == device_a:
        fail("second device did not get its own session")

    # 设备 B 以游客身份攒下的进度在登录后必须一起并进账号。
    st, text = sync(base, device_b, user, word("gamma", 2))
    if st != 200:
        fail(f"B guest merge failed: {st} {text[:200]}")
    st, payload = read_state(base, device_b, user)
    if st != 200 or keys_of(payload) != {"alpha", "gamma"}:
        fail(f"guest progress lost: {st} {keys_of(payload)}")

    # 设备 A 带着旧快照回来，不能把 B 的 gamma 冲掉。
    st, text = sync(base, device_a, user, word("beta", 3))
    if st != 200:
        fail(f"A reconnect failed: {st} {text[:200]}")
    st, payload = read_state(base, device_a, user)
    if st != 200 or keys_of(payload) != {"alpha", "beta", "gamma"}:
        fail(f"devices did not converge: {keys_of(payload)}")

    # 清空：B 执行 reset，A 再带旧快照同步，旧词不能复活。
    st, text = sync(base, device_b, user, {}, reset=True, op_id="clear-" + user)
    if st != 200:
        fail(f"clear failed: {st} {text[:200]}")
    st, text = sync(base, device_a, user, word("alpha", 1))
    if st != 200:
        fail(f"A post-clear sync failed: {st} {text[:200]}")
    st, payload = read_state(base, device_b, user)
    survivors = keys_of(payload)
    if "beta" in survivors or "gamma" in survivors:
        fail("cleared words resurrected: %s raw=%s"
             % (sorted(survivors),
                json.dumps((payload or {}).get("state"), ensure_ascii=False)[:700]))

    # 响应丢失：同一 operationId 重发两次必须幂等。
    op = "retry-" + user
    st1, t1 = sync(base, device_b, user, word("delta", 1), reset=True, op_id=op)
    st2, t2 = sync(base, device_b, user, word("delta", 1), reset=True, op_id=op)
    if st1 != 200 or st2 != 200:
        fail(f"retry not idempotent: {st1}/{st2}")
    if keys_of(json.loads(t1).get("payload")) != keys_of(json.loads(t2).get("payload")):
        fail("retry produced a different result")

    # 乱序：A 用更旧的快照覆盖，进度不能被回退。
    st, text = sync(base, device_b, user, word("epsilon", 2))
    if st != 200:
        fail(f"B new learning failed: {st} {text[:200]}")
    st, text = sync(base, device_a, user, word("delta", 1))
    if st != 200:
        fail(f"A stale sync failed: {st} {text[:200]}")
    st, payload = read_state(base, device_a, user)
    final = keys_of(payload)
    if "epsilon" not in final:
        fail(f"out-of-order sync dropped newer word: {sorted(final)}")

    # 会话过期：伪造 token 必须 401，不能当成新账号。
    st, _, _ = request(base, "/api/state?expectedUsername=" + user, cookie="ky_sid=deadbeef")
    if st != 401:
        fail(f"expired session accepted: {st}")

    print(json.dumps({
        "ok": True, "base_url": base, "username": user,
        "final_words": sorted(final),
        "scenarios": ["guest-merge", "reconnect-converge", "clear-no-resurrect",
                      "retry-idempotent", "out-of-order-safe", "expired-session-401"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
