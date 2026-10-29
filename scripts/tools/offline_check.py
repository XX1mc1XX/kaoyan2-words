# -*- coding: utf-8 -*-
"""端到端离线验收：真实 Edge + Service Worker + Cache Storage。

用法：
    python scripts/tools/offline_check.py
    python scripts/tools/offline_check.py --json

脚本使用全新的临时浏览器 profile，在线完成以下行为后关闭本地 HTTP 服务并
切换到浏览器离线模式，再重新加载页面复验：
  * SW 控制当前页面
  * 四本词库完整加载
  * 第一章 200 词、切章、词表
  * 详情分片、中英文音频缓存命中
  * 断网后词库、切章、词表、详情、中英文音频仍可用

输出始终是结构化 JSON。退出码 0 表示全部通过，1 表示失败。
"""
from __future__ import annotations

import argparse
import datetime as dt
import functools
import http.server
import io
import json
import math
import os
import re
import shutil
import struct
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse
import wave
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEPLOY = os.path.join(ROOT, "deploy")
SHELL_PREFIX = "ky-shell-"
AUDIO_CACHE = "ky-audio-v2"
DECK_KEYS = ("core", "derivative", "foundation", "insurance")
DECK_IDS = {
    "core": "words",
    "derivative": "derivatives",
    "foundation": "basic",
    "insurance": "insurance",
}


class CheckFailure(RuntimeError):
    def __init__(self, key: str, reason: str):
        super().__init__(reason)
        self.key = key
        self.reason = reason


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def find_edge() -> str:
    candidates = [
        os.environ.get("KY_EDGE", ""),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("PROGRAMFILES", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return ""


def add_check(
    result: dict[str, Any],
    key: str,
    name: str,
    ok: bool,
    reason: str | None = None,
    details: Any = None,
) -> bool:
    item: dict[str, Any] = {"key": key, "name": name, "ok": bool(ok)}
    if not ok and reason:
        item["reason"] = reason
    if details is not None:
        item["details"] = details
    result["checks"].append(item)
    if not ok:
        result["failures"].append({"key": key, "name": name, "reason": reason or "检查未通过"})
    return bool(ok)


def require_check(
    result: dict[str, Any],
    key: str,
    name: str,
    ok: bool,
    reason: str | None = None,
    details: Any = None,
) -> None:
    if not add_check(result, key, name, ok, reason, details):
        raise CheckFailure(key, reason or name)


def extract_json_block(html: str, block_id: str) -> Any:
    pattern = r'<script[^>]*id="%s"[^>]*>(.*?)</script>' % re.escape(block_id)
    match = re.search(pattern, html, re.S)
    if not match:
        raise ValueError("页面缺少 JSON 数据块 %s" % block_id)
    return json.loads(match.group(1))


def resolve_deploy_asset(asset: str) -> str:
    rel = asset[2:] if asset.startswith("./") else asset.lstrip("/")
    path = os.path.realpath(os.path.join(DEPLOY, rel))
    deploy_real = os.path.realpath(DEPLOY)
    if os.path.commonpath([deploy_real, path]) != deploy_real:
        raise ValueError("词库资源路径越界：%s" % asset)
    return path


def load_deployment() -> dict[str, Any]:
    index_path = os.path.join(DEPLOY, "index.html")
    build_path = os.path.join(DEPLOY, "build-meta.json")
    if not os.path.isfile(index_path):
        raise ValueError("deploy/index.html 不存在，请先构建")
    if not os.path.isfile(build_path):
        raise ValueError("deploy/build-meta.json 不存在，请先构建")

    with io.open(index_path, encoding="utf-8") as fh:
        html = fh.read()
    with io.open(build_path, encoding="utf-8") as fh:
        build_meta = json.load(fh)
    page_meta = extract_json_block(html, "ky-deck-meta")
    if not page_meta.get("web"):
        raise ValueError("deploy/index.html 不是按需加载的网页版数据")
    if not isinstance(build_meta.get("build"), str) or not build_meta["build"]:
        raise ValueError("build-meta.json 缺少 build 版本")

    assets = page_meta.get("assets") or {}
    decks: dict[str, Any] = {}
    for key in DECK_KEYS:
        deck_id = DECK_IDS[key]
        asset = assets.get(deck_id)
        if not asset:
            raise ValueError("DATA_META 缺少词库资源 %s" % deck_id)
        path = resolve_deploy_asset(asset)
        if not os.path.isfile(path):
            raise ValueError("词库资源不存在：%s" % asset)
        with io.open(path, encoding="utf-8") as fh:
            rows = json.load(fh)
        ids = [row.get("id") for row in rows] if isinstance(rows, list) else []
        contiguous = bool(ids) and ids == list(range(1, len(rows) + 1))
        decks[key] = {
            "id": deck_id,
            "asset": asset,
            "path": os.path.relpath(path, ROOT).replace("\\", "/"),
            "count": len(rows) if isinstance(rows, list) else 0,
            "ids_contiguous": contiguous,
        }
        declared = (page_meta.get("deck_sizes") or {}).get(deck_id)
        if declared != decks[key]["count"]:
            raise ValueError("%s 声明 %s 词，实际文件 %s 词" % (deck_id, declared, decks[key]["count"]))
        if not contiguous:
            raise ValueError("%s 的 id 不是连续的 1..N" % deck_id)

    details = assets.get("details") or {}
    if not isinstance(details, dict) or len(details) < 2:
        raise ValueError("DATA_META 缺少详情分片")
    return {
        "index": index_path,
        "build_meta": build_meta,
        "page_meta": page_meta,
        "decks": decks,
        "details": details,
    }


def make_wav() -> bytes:
    buffer = io.BytesIO()
    rate = 8000
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        frames = bytearray()
        for i in range(rate // 12):
            sample = int(1200 * math.sin(2 * math.pi * 660 * i / rate))
            frames.extend(struct.pack("<h", sample))
        out.writeframes(bytes(frames))
    return buffer.getvalue()


AUDIO_WAV = make_wav()


class LocalHandler(http.server.SimpleHTTPRequestHandler):
    server_version = "ky-offline-check/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        pass

    def record(self) -> None:
        self.server.record_request(self.path)  # type: ignore[attr-defined]

    def do_HEAD(self) -> None:
        self.record()
        if urllib.parse.urlsplit(self.path).path == "/api/audio":
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(AUDIO_WAV)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        super().do_HEAD()

    def do_GET(self) -> None:
        self.record()
        if urllib.parse.urlsplit(self.path).path == "/api/audio":
            self.serve_audio()
            return
        super().do_GET()

    def serve_audio(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        word = (query.get("word") or [""])[0]
        lang = (query.get("lang") or ["en"])[0]
        if not word or lang not in ("en", "zh"):
            body = b'{"error":"missing word or invalid lang"}'
            self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(AUDIO_WAV)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Test-Audio-Lang", lang)
        self.end_headers()
        self.wfile.write(AUDIO_WAV)


class LocalServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], handler: Any):
        super().__init__(address, handler)
        self.request_counts: dict[str, int] = {}
        self.request_lock = threading.Lock()

    def record_request(self, path: str) -> None:
        with self.request_lock:
            self.request_counts[path] = self.request_counts.get(path, 0) + 1

    def audio_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        with self.request_lock:
            paths = list(self.request_counts.items())
        for raw_path, count in paths:
            parsed = urllib.parse.urlsplit(raw_path)
            if parsed.path != "/api/audio":
                continue
            query = urllib.parse.parse_qs(parsed.query)
            word = (query.get("word") or [""])[0]
            lang = (query.get("lang") or ["en"])[0]
            if word:
                out[lang + ":" + word] = out.get(lang + ":" + word, 0) + count
        return out


def start_server() -> LocalServer:
    handler = functools.partial(LocalHandler, directory=DEPLOY)
    server = LocalServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="offline-check-http")
    thread.start()
    setattr(server, "_check_thread", thread)
    return server


def stop_server(server: LocalServer | None) -> None:
    if server is None:
        return
    try:
        server.shutdown()
    except Exception:
        pass
    try:
        server.server_close()
    except Exception:
        pass
    thread = getattr(server, "_check_thread", None)
    if thread is not None:
        thread.join(timeout=3)


def wait_js(page: Any, expression: str, arg: Any = None, timeout: int = 30000) -> bool:
    try:
        if arg is None:
            page.wait_for_function(expression, timeout=timeout)
        else:
            page.wait_for_function(expression, arg=arg, timeout=timeout)
        return True
    except Exception:
        return False


def page_state(page: Any) -> dict[str, Any]:
    return page.evaluate("""() => ({
      controller: navigator.serviceWorker && navigator.serviceWorker.controller
        ? navigator.serviceWorker.controller.scriptURL : '',
      online: navigator.onLine,
      ready: Object.fromEntries(DECK_KEYS.map(k => [k, deckDataReady(k)])),
      counts: Object.fromEntries(DECK_KEYS.map(k => [k, deckJson(DECK_IDS[k]).length])),
      expected: Object.fromEntries(DECK_KEYS.map(k => [k, DATA_META.deck_sizes[DECK_IDS[k]]])),
      queue: typeof queue === 'undefined' ? -1 : queue.length,
      chapter: typeof curChapter === 'undefined' ? -1 : curChapter,
      position: (document.getElementById('position')?.textContent || '').replace(/\\s+/g, ' ').trim(),
      word: (document.getElementById('word')?.textContent || '').trim(),
      chapter_options: document.getElementById('chapterSelect')?.options.length || 0,
      deck_meta: (document.getElementById('deckMeta')?.textContent || '').trim()
    })""")


def inspect_shell_cache(page: Any, build: str, expected: dict[str, Any]) -> dict[str, Any]:
    expected_payload = {
        key: {"id": data["id"], "asset": data["asset"], "count": data["count"]}
        for key, data in expected.items()
    }
    return page.evaluate("""async ({build, expected}) => {
      const names = await caches.keys();
      const shellName = 'ky-shell-' + build;
      const result = {cache_names: names, shell_name: shellName, shell_found: names.includes(shellName), decks: {}};
      if (!names.includes(shellName)) return result;
      const cache = await caches.open(shellName);
      for (const key of DECK_KEYS) {
        const want = expected[key];
        const absolute = new URL(want.asset, location.href).href;
        const response = await cache.match(absolute);
        let rowCount = -1;
        let idsContiguous = false;
        if (response) {
          try {
            const rows = await response.clone().json();
            rowCount = Array.isArray(rows) ? rows.length : -1;
            idsContiguous = Array.isArray(rows) && rows.length > 0
              && rows.every((row, i) => Number(row && row.id) === i + 1);
          } catch (_) {}
        }
        result.decks[key] = {
          asset: want.asset,
          cached: !!response,
          count: rowCount,
          expected: want.count,
          ids_contiguous: idsContiguous
        };
      }
      return result;
    }""", {"build": build, "expected": expected_payload})


def all_decks_via_app(page: Any) -> dict[str, Any]:
    return page.evaluate("""async () => {
      const errors = [];
      for (const key of DECK_KEYS) {
        try { await ensureDeckData(key); }
        catch (err) { errors.push(key + ': ' + (err && err.message ? err.message : String(err))); }
      }
      const decks = {};
      for (const key of DECK_KEYS) {
        const rows = deckJson(DECK_IDS[key]);
        decks[key] = {
          ready: deckDataReady(key),
          count: rows.length,
          expected: DATA_META.deck_sizes[DECK_IDS[key]],
          ids_contiguous: rows.length > 0 && rows.every((row, i) => Number(row && row.id) === i + 1)
        };
      }
      return {decks, errors, ready_all: allDecksReady()};
    }""")


def deck_check_ok(data: dict[str, Any], expected: dict[str, Any]) -> tuple[bool, str]:
    errors = data.get("errors") or []
    if errors:
        return False, "；".join(errors)
    for key in DECK_KEYS:
        row = (data.get("decks") or {}).get(key) or {}
        want = expected[key]["count"]
        if not row.get("ready"):
            return False, "%s 尚未就绪" % key
        if row.get("count") != want or row.get("expected") != want:
            return False, "%s 词数=%s，声明=%s，实际文件=%s" % (
                key, row.get("count"), row.get("expected"), want
            )
        if not row.get("ids_contiguous"):
            return False, "%s 词 id 不连续" % key
    if not data.get("ready_all"):
        return False, "四本词库未全部进入 ready 状态"
    return True, ""


def switch_deck_ui(page: Any, expected: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in DECK_KEYS:
        want = expected[key]["count"]
        page.locator("#deckSelect").select_option(key)
        ok = wait_js(
            page,
            "key => activeDeck === key && deckDataReady(key) && deckJson(DECK_IDS[key]).length > 0",
            arg=key,
            timeout=20000,
        )
        state = page_state(page)
        out[key] = {
            "ok": ok and state.get("deck_meta") == "%d 词" % want,
            "active": page.evaluate("() => activeDeck"),
            "meta": state.get("deck_meta"),
            "queue": state.get("queue"),
            "word": state.get("word"),
        }
    return out


def chapter_snapshot(page: Any, chapter: int) -> dict[str, Any]:
    return page.evaluate("""chapter => {
      const all = deckWords();
      const expected = all.slice(chapter * CHAPTER_SIZE, (chapter + 1) * CHAPTER_SIZE).map(w => w.word);
      const actual = queue.map(w => w.word);
      const missing = expected.filter(w => !actual.includes(w));
      const extra = actual.filter(w => !expected.includes(w));
      return {
        chapter: curChapter,
        queue: queue.length,
        expected: expected.length,
        position: (document.getElementById('position')?.textContent || '').replace(/\\s+/g, ' ').trim(),
        chapter_options: document.getElementById('chapterSelect')?.options.length || 0,
        first_word: actual[0] || '',
        first_expected: expected[0] || '',
        unique: new Set(actual).size,
        missing: missing.slice(0, 5),
        extra: extra.slice(0, 5)
      };
    }""", chapter)


def list_snapshot(page: Any) -> dict[str, Any]:
    return page.evaluate("""() => {
      const nodes = [...document.querySelectorAll('#wordList > li')];
      const words = nodes.map(li => (li.querySelector('.list-word')?.textContent || '').trim()).filter(Boolean);
      const expected = deckWords().slice(0, words.length).map(w => w.word);
      const mismatches = [];
      for (let i = 0; i < words.length; i++) {
        if (words[i] !== expected[i]) { mismatches.push({index: i, actual: words[i], expected: expected[i]}); if (mismatches.length >= 5) break; }
      }
      return {
        visible: !document.getElementById('viewList').classList.contains('hidden'),
        count: nodes.length,
        words: words.length,
        more: !!document.querySelector('#wordList .list-more'),
        first: words[0] || '',
        last: words[words.length - 1] || '',
        mismatches,
        expected_first: expected[0] || ''
      };
    }""")


def detail_snapshot(page: Any, open_it: bool = True) -> dict[str, Any]:
    return page.evaluate("""async open_it => {
      const word = queue[idx];
      if (!word) return {ok: false, reason: '当前没有词卡'};
      if (open_it) await openDetail(word);
      const shardKey = detailShardKey(word.word);
      const assets = (DATA_META.assets && DATA_META.assets.details) || {};
      const url = assets[shardKey] ? new URL(assets[shardKey], location.href).href : '';
      const cacheNames = await caches.keys();
      let cached = false;
      let cachedHasWord = false;
      for (const name of cacheNames.filter(n => n.startsWith('ky-shell-'))) {
        const cache = await caches.open(name);
        const response = url ? await cache.match(url) : null;
        if (response) {
          cached = true;
          try { cachedHasWord = !!(await response.clone().json())[word.word]; } catch (_) {}
          break;
        }
      }
      const mask = document.getElementById('detailMask');
      return {
        ok: !!mask && !mask.classList.contains('hidden'),
        word: word.word,
        shard_key: shardKey,
        shard_url: url,
        cached,
        cached_has_word: cachedHasWord,
        detail_word: (document.getElementById('detailWord')?.textContent || '').trim(),
        phonetic: (document.getElementById('detailPhonetic')?.textContent || '').trim(),
        detail_dict: (document.getElementById('detailDict')?.textContent || '').trim(),
        failure_text: (document.getElementById('detailDict')?.textContent || '').includes('详情加载失败')
      };
    }""", open_it)


def audio_online_snapshot(page: Any, targets: list[dict[str, str]]) -> dict[str, Any]:
    return page.evaluate("""async targets => {
      const cache = await caches.open('ky-audio-v2');
      const out = {};
      for (const target of targets) {
        const cacheUrl = new URL(offlineAudioUrl(target.text, target.lang), location.href).href;
        const preexistingResponse = await cache.match(cacheUrl);
        const first = await fetchOfflineAudio(target.text, target.lang);
        const firstHeader = first.headers.get('x-ky-cache');
        const firstBlob = await first.blob();
        const second = await fetchOfflineAudio(target.text, target.lang);
        const secondHeader = second.headers.get('x-ky-cache');
        const secondBlob = await second.blob();
        const cachedResponse = await cache.match(cacheUrl);
        let cachedBlob = null;
        if (cachedResponse) cachedBlob = await cachedResponse.blob();
        out[target.label] = {
          text: target.text,
          lang: target.lang,
          cache_url: cacheUrl,
          first_header: firstHeader,
          second_header: secondHeader,
          preexisting: !!preexistingResponse,
          first_size: firstBlob.size,
          second_size: secondBlob.size,
          first_type: firstBlob.type,
          cached: !!cachedResponse,
          cached_size: cachedBlob ? cachedBlob.size : 0,
          cached_type: cachedBlob ? cachedBlob.type : ''
        };
      }
      return {cache_name: 'ky-audio-v2', cache_entries: (await cache.keys()).length, results: out, online: navigator.onLine};
    }""", targets)


def audio_offline_snapshot(page: Any, targets: list[dict[str, str]]) -> dict[str, Any]:
    return page.evaluate("""async targets => {
      const cache = await caches.open('ky-audio-v2');
      const out = {};
      for (const target of targets) {
        const response = await fetchOfflineAudio(target.text, target.lang);
        const header = response.headers.get('x-ky-cache');
        const blob = await response.blob();
        const cacheUrl = new URL(offlineAudioUrl(target.text, target.lang), location.href).href;
        const cachedResponse = await cache.match(cacheUrl);
        out[target.label] = {
          header,
          size: blob.size,
          type: blob.type,
          cache_url: cacheUrl,
          cached: !!cachedResponse
        };
      }
      return {cache_entries: (await cache.keys()).length, results: out, online: navigator.onLine};
    }""", targets)


def cache_snapshot(page: Any, build: str) -> dict[str, Any]:
    return page.evaluate("""async build => {
      const names = await caches.keys();
      const shellName = 'ky-shell-' + build;
      const shell = names.includes(shellName) ? await caches.open(shellName) : null;
      const audio = names.includes('ky-audio-v2') ? await caches.open('ky-audio-v2') : null;
      return {
        names,
        shell_name: shellName,
        shell_keys: shell ? (await shell.keys()).map(r => r.url) : [],
        audio_keys: audio ? (await audio.keys()).map(r => r.url) : []
      };
    }""", build)


def run_check() -> dict[str, Any]:
    started = time.monotonic()
    result: dict[str, Any] = {
        "ok": False,
        "status": "failed",
        "started_at": now_iso(),
        "duration_ms": 0,
        "profile": {"temporary": True, "fresh": True, "engine": "Edge headless via Playwright"},
        "checks": [],
        "failures": [],
        "browser_errors": [],
    }
    server: LocalServer | None = None
    temp_profile = ""
    context = None
    server_stopped = False
    completed = False

    try:
        deployment = load_deployment()
        result["build"] = {
            "build": deployment["build_meta"].get("build"),
            "app_asset": deployment["build_meta"].get("app_asset"),
            "decks": deployment["decks"],
            "detail_assets": len(deployment["details"]),
        }
        add_check(result, "deploy_ready", "部署产物与四本词库文件完整", True)

        edge = find_edge()
        require_check(result, "edge_available", "发现 Microsoft Edge", bool(edge), "找不到 msedge.exe，可用 KY_EDGE 指定路径")
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            require_check(result, "playwright_available", "Playwright 可用", False, "无法导入 Playwright：%s" % exc)
            raise CheckFailure("playwright_available", "无法导入 Playwright：%s" % exc)

        server = start_server()
        port = server.server_address[1]
        base_url = "http://127.0.0.1:%d/" % port
        result["server"] = {"base_url": base_url, "audio_fixture": "valid 0.083s PCM WAV", "local_only": True}
        temp_profile = tempfile.mkdtemp(prefix="ky-offline-profile-")

        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                temp_profile,
                executable_path=edge,
                headless=True,
                service_workers="allow",
                locale="zh-CN",
                viewport={"width": 1280, "height": 900},
                args=[
                    "--disable-features=Translate",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
            )
            context.set_default_timeout(20000)
            # 禁止页面在 requestIdleCallback 时自动批量下载 800 条音频，确保本检查只测
            # 自己触发的缓存路径，避免请求计数和缓存状态被后台任务扰动。
            context.add_init_script("""
              try { localStorage.setItem('ky_auto_offline_v2', 'done'); } catch (_) {}
            """)
            page = context.pages[0] if context.pages else context.new_page()
            page.on("pageerror", lambda exc: result["browser_errors"].append("pageerror: " + str(exc)))
            page.on("console", lambda msg: result["browser_errors"].append("console.%s: %s" % (msg.type, msg.text)) if msg.type == "error" else None)

            browser_version = ""
            try:
                browser_version = context.browser.version if context.browser else ""
            except Exception:
                pass
            result["browser"] = {"executable": edge, "version": browser_version}

            try:
                page.goto(base_url, wait_until="load", timeout=60000)
            except Exception as exc:
                require_check(result, "initial_page_load", "联网首次打开页面", False, "页面加载失败：%s" % exc)
            loaded = wait_js(
                page,
                "() => typeof queue !== 'undefined' && document.getElementById('word') && document.getElementById('word').textContent.trim()",
                timeout=30000,
            )
            require_check(result, "initial_page_load", "联网首次打开并渲染词卡", loaded,
                          "30 秒内未完成应用启动", page_state(page) if loaded else None)

            controlled = wait_js(
                page,
                "() => navigator.serviceWorker && navigator.serviceWorker.controller && navigator.serviceWorker.controller.scriptURL.endsWith('/sw.js')",
                timeout=30000,
            )
            control_details = page.evaluate("""async () => {
              const reg = await navigator.serviceWorker.getRegistration();
              return {
                controller: navigator.serviceWorker.controller ? navigator.serviceWorker.controller.scriptURL : '',
                controller_state: navigator.serviceWorker.controller ? navigator.serviceWorker.controller.state : '',
                active: reg && reg.active ? reg.active.state : '',
                scope: reg ? reg.scope : '',
                secure: window.isSecureContext
              };
            }""")
            require_check(result, "service_worker_controls_page", "Service Worker 已激活并控制当前页面", controlled,
                          "页面未被 SW 控制：%s" % json.dumps(control_details, ensure_ascii=False),
                          control_details)

            build = deployment["build_meta"]["build"]
            expected_assets = {key: {"asset": row["asset"]} for key, row in deployment["decks"].items()}
            cache_ready = wait_js(
                page,
                """async ({build, expected}) => {
                  const names = await caches.keys();
                  const shellName = 'ky-shell-' + build;
                  if (!names.includes(shellName)) return false;
                  const cache = await caches.open(shellName);
                  for (const key of DECK_KEYS) {
                    if (!await cache.match(new URL(expected[key].asset, location.href).href)) return false;
                  }
                  return true;
                }""",
                arg={"build": build, "expected": expected_assets},
                timeout=35000,
            )
            shell = inspect_shell_cache(page, build, deployment["decks"])
            cache_ok = cache_ready and shell.get("shell_found")
            cache_reason = ""
            for key in DECK_KEYS:
                row = (shell.get("decks") or {}).get(key) or {}
                if row.get("count") != deployment["decks"][key]["count"] or not row.get("ids_contiguous"):
                    cache_ok = False
                    cache_reason = "%s 缓存词数=%s，期望=%s，id连续=%s" % (
                        key, row.get("count"), deployment["decks"][key]["count"], row.get("ids_contiguous")
                    )
                    break
            require_check(result, "cache_storage_decks", "四本词库响应确实来自 Cache Storage", cache_ok,
                          cache_reason or "未等到完整的 ky-shell-%s 缓存" % build, shell)
            result["cache_before_offline"] = cache_snapshot(page, build)

            first_ok = wait_js(
                page,
                "() => typeof queue !== 'undefined' && activeDeck === 'core' && deckDataReady('core') && queue.length === 200",
                timeout=35000,
            )
            first_state = page_state(page)
            first_reason = ""
            if not first_ok:
                first_reason = "第一章未补齐：queue=%s，position=%s，word=%s" % (
                    first_state.get("queue"), first_state.get("position"), first_state.get("word")
                )
            elif first_state.get("position") != "第 1 / 200 个":
                first_ok = False
                first_reason = "第一章位置显示为 %r" % first_state.get("position")
            require_check(result, "first_chapter_200", "第一章完整加载 200 词", first_ok, first_reason, first_state)

            all_decks = all_decks_via_app(page)
            decks_ok, decks_reason = deck_check_ok(all_decks, deployment["decks"])
            require_check(result, "four_decks_complete", "四本词库完整加载", decks_ok, decks_reason, all_decks)

            switched = switch_deck_ui(page, deployment["decks"])
            switch_ok = all(row.get("ok") for row in switched.values())
            require_check(result, "deck_switching", "四本词库均可通过顶栏切换", switch_ok,
                          "切库结果异常：%s" % json.dumps(switched, ensure_ascii=False), switched)

            page.locator("#deckSelect").select_option("core")
            wait_js(page, "() => activeDeck === 'core' && deckDataReady('core')", timeout=15000)
            if page.locator("#chapterSelect").count():
                page.locator("#chapterSelect").select_option("1")
                chapter_ok = wait_js(page, "() => curChapter === 1 && queue.length === 200", timeout=20000)
                chapter = chapter_snapshot(page, 1)
                chapter_reason = ""
                if not chapter_ok:
                    chapter_reason = "切到第 2 章后 chapter=%s queue=%s" % (chapter.get("chapter"), chapter.get("queue"))
                elif chapter.get("missing") or chapter.get("extra") or chapter.get("unique") != 200:
                    chapter_ok = False
                    chapter_reason = "第 2 章队列与词库切片不一致"
                require_check(result, "chapter_switch", "切章后加载完整 200 词", chapter_ok, chapter_reason, chapter)

            page.locator("#chapterSelect").select_option("0")
            wait_js(page, "() => curChapter === 0 && queue.length === 200", timeout=15000)
            page.locator("#tabList").click()
            list_first_ok = wait_js(page, "() => !document.getElementById('viewList').classList.contains('hidden') && document.querySelectorAll('#wordList > li').length === 100", timeout=20000)
            list_initial = list_snapshot(page)
            if page.locator("#wordList .list-more").count():
                page.locator("#wordList .list-more").click()
                wait_js(page, "() => document.querySelectorAll('#wordList > li').length >= 200", timeout=10000)
            list_data = list_snapshot(page)
            list_ok = list_first_ok and list_data.get("count") == 200 and not list_data.get("mismatches")
            list_reason = ""
            if not list_ok:
                list_reason = "词表初始=%s，展开后=%s，错位=%s" % (
                    list_initial.get("count"), list_data.get("count"), list_data.get("mismatches")
                )
            require_check(result, "word_list", "词表在线可用且前 200 条与词库一致", list_ok, list_reason, list_data)
            page.locator("#tabStudy").click()

            page.evaluate("() => loadChapter(0, 'natural', 0, deckJson('words')[0].word)")
            wait_js(page, "() => curChapter === 0 && queue[idx] && queue[idx].word === deckJson('words')[0].word", timeout=10000)
            detail = detail_snapshot(page, open_it=True)
            if detail.get("shard_url"):
                wait_js(
                    page,
                    """async url => {
                      for (const name of (await caches.keys()).filter(n => n.startsWith('ky-shell-'))) {
                        const cache = await caches.open(name);
                        if (await cache.match(url)) return true;
                      }
                      return false;
                    }""",
                    arg=detail["shard_url"],
                    timeout=10000,
                )
                detail = detail_snapshot(page, open_it=False)
            detail_ok = bool(
                detail.get("ok") and detail.get("word") == detail.get("detail_word")
                and not detail.get("failure_text") and detail.get("cached")
                and detail.get("cached_has_word") and detail.get("phonetic")
            )
            require_check(result, "detail_shard", "详情分片在线加载并写入 Cache Storage", detail_ok,
                          "详情结果异常：%s" % json.dumps(detail, ensure_ascii=False), detail)
            page.evaluate("() => closeDetail()")

            current = page.evaluate("""() => {
              const item = queue[queue.length - 1];
              return {word: item.word, meaning: meaningForSpeech(item)};
            }""")
            targets = [
                {"label": "english", "text": current["word"], "lang": "en"},
                {"label": "chinese", "text": current["meaning"], "lang": "zh"},
            ]
            result["audio_targets"] = targets
            audio_before = server.audio_counts()
            audio_online = audio_online_snapshot(page, targets)
            audio_after = server.audio_counts()
            audio_delta = {key: audio_after.get(key, 0) - audio_before.get(key, 0) for key in set(audio_before) | set(audio_after)}
            audio_ok = True
            audio_reason = ""
            stored_count = 0
            for target in targets:
                row = (audio_online.get("results") or {}).get(target["label"]) or {}
                key = target["lang"] + ":" + target["text"]
                first_header = row.get("first_header")
                if first_header not in ("stored", "hit"):
                    audio_ok = False
                    audio_reason = "%s?????? x-ky-cache=%r??? stored ? hit" % (target["label"], first_header)
                    break
                if first_header == "hit" and not row.get("preexisting"):
                    audio_ok = False
                    audio_reason = "%s????????????? Cache Storage ??????" % target["label"]
                    break
                if first_header == "stored":
                    stored_count += 1
                if row.get("second_header") != "hit":
                    audio_ok = False
                    audio_reason = "%s??????? x-ky-cache=%r??? hit" % (target["label"], row.get("second_header"))
                    break
                if not row.get("cached") or row.get("cached_size", 0) <= 0 or not str(row.get("cached_type", "")).startswith("audio/"):
                    audio_ok = False
                    audio_reason = "%s???? Cache Storage ???????" % target["label"]
                    break
                delta = audio_delta.get(key, 0)
                if first_header == "stored" and delta != 1:
                    audio_ok = False
                    audio_reason = "%s????????????????????????=%s" % (target["label"], delta)
                    break
                if first_header == "hit" and delta != 0:
                    audio_ok = False
                    audio_reason = "%s????????????????? %s ?" % (target["label"], delta)
                    break
            if audio_ok and stored_count == 0:
                audio_ok = False
                audio_reason = "?????????????????????????????????"
            audio_details = {"page": audio_online, "server_delta": audio_delta}
            require_check(result, "audio_cache_hits", "中英文音频首次写入且第二次命中 Cache Storage", audio_ok, audio_reason, audio_details)

            result["cache_before_offline"] = cache_snapshot(page, build)

            # 让断网重载从第一章开始，便于验证首章完整性。
            page.locator("#deckSelect").select_option("core")
            wait_js(page, "() => activeDeck === 'core'", timeout=10000)
            page.locator("#chapterSelect").select_option("0")
            wait_js(page, "() => curChapter === 0 && queue.length === 200", timeout=15000)

            stop_server(server)
            server_stopped = True
            server = None
            context.set_offline(True)
            result["network_after_shutdown"] = {"http_server": "stopped", "browser_offline": True}

            reload_ok = False
            reload_error = ""
            try:
                page.reload(wait_until="domcontentloaded", timeout=60000)
                reload_ok = wait_js(
                    page,
                    "() => typeof queue !== 'undefined' && navigator.onLine === false && !!navigator.serviceWorker.controller",
                    timeout=30000,
                )
            except PlaywrightError as exc:
                reload_error = str(exc)
            except Exception as exc:
                reload_error = str(exc)
            offline_state = page_state(page) if reload_ok else {}
            require_check(result, "offline_reload", "断网后页面可由 Service Worker 重新打开", reload_ok,
                          "断网重载失败：%s" % (reload_error or json.dumps(offline_state, ensure_ascii=False)),
                          offline_state)

            offline_first = wait_js(
                page,
                "() => navigator.onLine === false && activeDeck === 'core' && deckDataReady('core') && queue.length === 200",
                timeout=30000,
            )
            offline_first_state = page_state(page)
            require_check(result, "offline_first_chapter", "断网后第一章仍为 200 词", offline_first,
                          "断网后 queue=%s，position=%s" % (offline_first_state.get("queue"), offline_first_state.get("position")),
                          offline_first_state)

            page.locator("#chapterSelect").select_option("1")
            offline_chapter_ok = wait_js(page, "() => curChapter === 1 && queue.length === 200", timeout=20000)
            offline_chapter = chapter_snapshot(page, 1)
            if offline_chapter_ok and (offline_chapter.get("missing") or offline_chapter.get("extra") or offline_chapter.get("unique") != 200):
                offline_chapter_ok = False
            require_check(result, "offline_chapter_switch", "断网后仍可切章", offline_chapter_ok,
                          "断网切章后 chapter=%s queue=%s missing=%s extra=%s" % (
                              offline_chapter.get("chapter"), offline_chapter.get("queue"),
                              offline_chapter.get("missing"), offline_chapter.get("extra")
                          ), offline_chapter)

            page.locator("#tabList").click()
            offline_list_first = wait_js(page, "() => !document.getElementById('viewList').classList.contains('hidden') && document.querySelectorAll('#wordList > li').length === 100", timeout=20000)
            if page.locator("#wordList .list-more").count():
                page.locator("#wordList .list-more").click()
                wait_js(page, "() => document.querySelectorAll('#wordList > li').length >= 200", timeout=10000)
            offline_list = list_snapshot(page)
            offline_list_ok = offline_list_first and offline_list.get("count") == 200 and not offline_list.get("mismatches")
            require_check(result, "offline_word_list", "断网后词表仍可用", offline_list_ok,
                          "断网词表 count=%s mismatches=%s" % (offline_list.get("count"), offline_list.get("mismatches")), offline_list)
            page.locator("#tabStudy").click()

            offline_decks = all_decks_via_app(page)
            offline_decks_ok, offline_decks_reason = deck_check_ok(offline_decks, deployment["decks"])
            require_check(result, "offline_four_decks", "断网后四本词库仍完整", offline_decks_ok,
                          offline_decks_reason, offline_decks)

            page.locator("#deckSelect").select_option("core")
            wait_js(page, "() => activeDeck === 'core'", timeout=15000)
            page.locator("#chapterSelect").select_option("0")
            wait_js(page, "() => curChapter === 0 && queue.length === 200", timeout=15000)
            page.evaluate("() => loadChapter(0, 'natural', 0, deckJson('words')[0].word)")
            wait_js(page, "() => queue[idx] && queue[idx].word === deckJson('words')[0].word", timeout=10000)
            offline_detail = detail_snapshot(page, open_it=True)
            offline_detail_ok = bool(
                offline_detail.get("ok") and offline_detail.get("cached") and offline_detail.get("cached_has_word")
                and not offline_detail.get("failure_text") and offline_detail.get("phonetic")
            )
            require_check(result, "offline_detail", "断网后详情分片仍可用", offline_detail_ok,
                          "断网详情结果异常：%s" % json.dumps(offline_detail, ensure_ascii=False), offline_detail)
            page.evaluate("() => closeDetail()")

            offline_audio = audio_offline_snapshot(page, targets)
            offline_audio_ok = True
            offline_audio_reason = ""
            for target in targets:
                row = (offline_audio.get("results") or {}).get(target["label"]) or {}
                if row.get("header") != "hit":
                    offline_audio_ok = False
                    offline_audio_reason = "%s音频断网响应 x-ky-cache=%r，期望 hit" % (target["label"], row.get("header"))
                    break
                if not row.get("cached") or row.get("size", 0) <= 0 or not str(row.get("type", "")).startswith("audio/"):
                    offline_audio_ok = False
                    offline_audio_reason = "%s音频断网后未从 Cache Storage 返回有效音频" % target["label"]
                    break
            require_check(result, "offline_audio_cache_hits", "断网后中英文音频仍命中 Cache Storage", offline_audio_ok,
                          offline_audio_reason, offline_audio)

            result["cache_after_offline"] = cache_snapshot(page, build)
            final_state = page_state(page)
            final_ok = bool(
                final_state.get("online") is False
                and final_state.get("word")
                and final_state.get("word") not in ("加载中", "加载中…", "加载失败", "加载失败…")
                and final_state.get("controller")
            )
            require_check(result, "offline_end_to_end", "断网后完整学习链路仍可用", final_ok,
                          "最终页面状态异常：%s" % json.dumps(final_state, ensure_ascii=False), final_state)
            completed = True

    except CheckFailure:
        pass
    except Exception as exc:
        result["failures"].append({
            "key": "unexpected_exception",
            "name": "检查脚本异常",
            "reason": "%s: %s" % (exc.__class__.__name__, exc),
        })
        result["traceback"] = traceback.format_exc(limit=12)
    finally:
        stop_server(server if not server_stopped else None)
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        if temp_profile:
            shutil.rmtree(temp_profile, ignore_errors=True)

    result["duration_ms"] = int((time.monotonic() - started) * 1000)
    failed = [check for check in result["checks"] if not check.get("ok")]
    result["summary"] = {
        "passed": len(result["checks"]) - len(failed),
        "failed": len(failed),
        "total": len(result["checks"]),
        "completed": completed,
    }
    result["ok"] = completed and not failed and not result["failures"]
    if result["ok"]:
        result["status"] = "passed"
        result.pop("failures", None)
    else:
        result["status"] = "failed"
        if result["failures"]:
            result["reason"] = result["failures"][0]["reason"]
        elif not completed:
            result["reason"] = "检查未完整执行"
    # 只保留少量浏览器错误，避免噪声淹没结构化结果。
    result["browser_errors"] = result.get("browser_errors", [])[:20]
    return result


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="端到端离线检查（输出 JSON）")
    parser.add_argument("--json", action="store_true", help="输出紧凑 JSON（兼容旧调用）")
    parser.parse_args()
    try:
        data = run_check()
    except Exception as exc:
        data = {
            "ok": False,
            "status": "error",
            "started_at": now_iso(),
            "reason": "%s: %s" % (exc.__class__.__name__, exc),
            "traceback": traceback.format_exc(limit=12),
            "checks": [],
            "failures": [{"key": "fatal", "name": "检查脚本异常", "reason": str(exc)}],
        }
    if "--json" in sys.argv:
        print(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0 if data.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
