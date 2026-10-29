"""Prove an already-installed Service Worker upgrades to a new build in place.

A persistent Edge profile is first served build A and allowed to take control, then
sw.js is rewritten to build B on disk. The same profile must pick up the new worker,
drop the old shell cache, keep rendering, and still boot while offline.

This is the upgrade-path check PHASES.md lists as "旧 Service Worker 升级到新 build";
it runs entirely against local files, so it proves the client mechanism, not the
Cloudflare deployment.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
SW = DEPLOY / "sw.js"
BUILD_RE = re.compile(r"const BUILD_VERSION = '([^']+)';")


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        # 浏览器在导航/断网时会直接掐连接，这类 reset 是噪声，不该盖住检查结果。
        pass


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DEPLOY), **kwargs)

    def log_message(self, *args):  # 保持输出干净
        pass

    def end_headers(self):
        self.send_header("cache-control", "no-store")
        super().end_headers()


def find_edge() -> str:
    import os
    env = os.environ.get("KY_EDGE")
    if env and Path(env).is_file():
        return env
    for base in (os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                 os.environ.get("ProgramFiles", r"C:\Program Files")):
        candidate = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
        if candidate.is_file():
            return str(candidate)
    raise SystemExit("msedge.exe not found; set KY_EDGE")


def shell_caches(page) -> list[str]:
    try:
        names = page.evaluate("async () => await caches.keys()")
    except Exception as exc:
        return ["<evaluate-error: %s>" % exc]
    return [n for n in names if n.startswith("ky-shell")]


def controller(page) -> str:
    return page.evaluate(
        "() => (navigator.serviceWorker.controller || {}).scriptURL || ''")


def safe_reload(page) -> bool:
    """导航受 SW 接管时有资源可能长时间不结束，DOM 就绪即可继续判断。"""
    try:
        page.reload(wait_until="domcontentloaded", timeout=20000)
        return True
    except Exception:
        return False


def trigger_update(page) -> None:
    """主动向浏览器要一次 sw.js 检查，避免只靠导航频率触发更新。"""
    try:
        page.evaluate("""
        async () => {
          const reg = await navigator.serviceWorker.getRegistration();
          if (reg) { try { await reg.update(); } catch (e) {} }
        }
        """)
    except Exception:
        pass


def wait_active(page, expected_build: str, timeout_ms: int = 30000) -> bool:
    # wait_for_function 不 await async 表达式，传 async 函数会立刻判真；
    # 这里自己轮询 evaluate（它确实会 await）。
    js = """
    async (build) => {
      if (!('serviceWorker' in navigator) || !navigator.serviceWorker.controller) return false;
      const names = await caches.keys();
      if (names.indexOf('ky-shell-' + build) < 0) return false;
      const reg = await navigator.serviceWorker.getRegistration();
      return !!(reg && reg.active);
    }
    """
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        try:
            if page.evaluate(js, expected_build):
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def main() -> int:
    if not SW.is_file():
        sys.exit("deploy/sw.js missing; run python scripts/make_html.py first")
    meta_path = DEPLOY / "build-meta.json"
    if not meta_path.is_file():
        sys.exit("deploy/build-meta.json missing; run python scripts/make_html.py first")
    build_a = json.loads(meta_path.read_text(encoding="utf-8"))["build"]
    current = SW.read_text(encoding="utf-8")
    # 上一次被中断的检查可能留下 probe 后缀；build-meta 才是真值源。
    healed = BUILD_RE.sub(f"const BUILD_VERSION = '{build_a}';", current, count=1)
    if healed != current:
        SW.write_text(healed, encoding="utf-8")
        current = healed
    original = current
    build_b = build_a + "-upgrade-probe"

    server = Server(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d/" % port
    profile = tempfile.mkdtemp(prefix="ky-sw-upgrade-")

    steps = []
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(
                profile, executable_path=find_edge(), headless=True,
                service_workers="allow", locale="zh-CN",
                args=["--no-first-run", "--no-default-browser-check"])
            ctx.set_default_timeout(25000)

            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(base, wait_until="load")
            if not wait_active(page, build_a):
                sys.exit(f"build {build_a} never became active")
            old_caches = shell_caches(page)
            first_word = page.evaluate("() => document.getElementById('word').textContent")
            steps.append({"phase": "build-a-active", "build": build_a,
                          "caches": old_caches, "word": first_word,
                          "controller": controller(page)})
            if build_a not in " ".join(old_caches):
                sys.exit(f"shell cache for {build_a} missing: {old_caches}")
            if not first_word:
                sys.exit("first card empty under build A")

            SW.write_text(original.replace(
                f"const BUILD_VERSION = '{build_a}';",
                f"const BUILD_VERSION = '{build_b}';"), encoding="utf-8")
            steps.append({"phase": "swap-on-disk", "build": build_b})

            safe_reload(page)
            trigger_update(page)
            safe_reload(page)
            upgraded = wait_active(page, build_b, timeout_ms=45000)
            new_caches = shell_caches(page)
            upgraded_word = page.evaluate("() => document.getElementById('word').textContent")
            steps.append({"phase": f"build-{('b' if upgraded else 'still-a')}-state",
                          "caches": new_caches, "word": upgraded_word,
                          "controller": controller(page)})
            if not upgraded:
                sys.exit(f"worker did not upgrade to {build_b}; caches={new_caches}")
            if not upgraded_word:
                sys.exit("page went blank after the worker upgrade")
            # activate 有意保留上一版 shell（运行中的旧页面可能还在用旧 app.<hash>.js），
            # 所以这里校验"不累积"，而不是"立刻清空"。
            stale = [c for c in new_caches if c != f"ky-shell-{build_b}"]
            if len(stale) > 1:
                sys.exit(f"stale shell caches accumulated: {new_caches}")

            # 断网后用新页面启动：在被 SW 接管的旧页面上 reload，
            # 有些请求永远不会结束，会把整个检查挂住。
            ctx.set_offline(True)
            offline_page = ctx.new_page()
            try:
                offline_page.goto(base, wait_until="domcontentloaded", timeout=25000)
            except Exception:
                pass
            time.sleep(1.5)
            try:
                offline_word = offline_page.evaluate(
                    "() => document.getElementById('word').textContent")
            except Exception as exc:
                offline_word = ""
                steps.append({"phase": "offline-evaluate-error", "error": str(exc)[:200]})
            steps.append({"phase": "offline-after-upgrade", "word": offline_word})
            if not offline_word:
                sys.exit("page cannot boot offline after the upgrade")
            ctx.set_offline(False)
            ctx.close()
    finally:
        SW.write_text(original, encoding="utf-8")
        server.shutdown()
        shutil.rmtree(profile, ignore_errors=True)

    print(json.dumps({
        "ok": True, "base_url": base, "build_from": build_a, "build_to": build_b,
        "steps": steps,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
