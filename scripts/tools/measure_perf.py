# -*- coding: utf-8 -*-
"""Repeatable local Edge/CDP performance baseline.

Builds the current template into a temporary local HTTP fixture, uses a fresh
edge profile for every cold sample, and never contacts real audio services.
"""
from __future__ import annotations

import argparse
import datetime as dt
import functools
import gzip
import hashlib
import http.server
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOFTWARE = ROOT / "software"
DATA = ROOT / "data"
SHARED = ROOT / "shared"
TEMPLATE = SOFTWARE / "template.html"
SW_TEMPLATE = SOFTWARE / "sw.template.js"
MERGE_SOURCE = SHARED / "merge.js"
EDGE_CANDIDATES = (
    Path(os.environ.get("KY_EDGE", "")) if os.environ.get("KY_EDGE") else None,
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
)


class PerfError(RuntimeError):
    pass


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def json_block(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def gzip_size(data):
    return len(gzip.compress(data, compresslevel=9, mtime=0))


def percentile(values, p):
    if not values:
        raise PerfError("percentile() received no samples")
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * (p / 100.0)
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def stats(values, digits=2):
    return {
        "n": len(values),
        "p50": round(percentile(values, 50), digits),
        "p95": round(percentile(values, 95), digits),
        "min": round(min(values), digits),
        "max": round(max(values), digits),
    }


def find_edge():
    for candidate in EDGE_CANDIDATES:
        if candidate and candidate.is_file():
            return candidate
    raise PerfError("Microsoft Edge not found; set KY_EDGE to msedge.exe")


def run_git(*args):
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=20, check=False,
        )
        return proc.stdout.strip() if proc.returncode == 0 else ""
    except Exception:
        return ""


def safe_rmtree(path, prefix):
    resolved = path.resolve()
    if not resolved.name.startswith(prefix):
        raise PerfError("refusing to clean non-perf temp directory: %s" % resolved)
    shutil.rmtree(resolved, ignore_errors=True)


def slim_rows(source):
    total = len(source)
    rows = []
    for index, row in enumerate(source, 1):
        rows.append({
            "id": row["id"], "word": row["word"], "family": row.get("family", ""),
            "meaning": row.get("meaning", ""), "forms": row.get("forms", []),
            "priority": row.get("priority", ""), "freq": row.get("freq", 0),
            "en1_freq": row.get("en1_freq", 0),
            "weight": round((total - index + 1) * 100 / total, 2) if total else 0,
        })
    return rows


def inject_once(source, marker, value):
    if marker not in source:
        raise PerfError("template placeholder missing: %s" % marker)
    return source.replace(marker, value, 1)


def current_source_int(js, name):
    match = re.search(r"\b(?:const|let|var)\s+%s\s*=\s*(\d+)\b" % re.escape(name), js)
    if not match:
        raise PerfError("integer constant %s not found in template" % name)
    return int(match.group(1))


def compatibility_shim(app_js):
    """Local-audio helpers only for an in-flight template that lacks them."""
    shims, parts = [], []
    if not re.search(r"\b(?:const|let|var)\s+AUDIO_PROXY_READY\b", app_js):
        parts.append("const AUDIO_PROXY_READY = true;\n")
        shims.append("AUDIO_PROXY_READY")
    if not re.search(r"\b(?:function\s+playSrcFor|(?:const|let|var)\s+playSrcFor\s*=)", app_js):
        parts.append(
            "function playSrcFor(text, lang) {\n"
            "  const q = new URLSearchParams({word: String(text || ''), lang: lang === 'zh' ? 'zh' : 'en'});\n"
            "  return '/api/audio?' + q.toString();\n"
            "}\n"
        )
        shims.append("playSrcFor")
    if not re.search(r"\b(?:function\s+offlineAudioUrl|(?:const|let|var)\s+offlineAudioUrl\s*=)", app_js):
        parts.append("function offlineAudioUrl(text, lang) { return playSrcFor(text, lang); }\n")
        shims.append("offlineAudioUrl")
    return "".join(parts) + app_js, shims


@dataclass
class BuiltSite:
    root: Path
    index_html: str
    app_js: str
    app_asset: str
    build: str
    source_sha256: str
    state_shard_count: int
    audio_preload_ahead: int
    audio_shims: list[str]
    deck_sizes: dict[str, int]

    def bundle(self):
        html = self.index_html.encode("utf-8")
        app = self.app_js.encode("utf-8")
        return {
            "app_asset": self.app_asset,
            "app_raw_bytes": len(app), "app_gzip_bytes": gzip_size(app),
            "index_raw_bytes": len(html), "index_gzip_bytes": gzip_size(html),
            "startup_raw_bytes": len(app) + len(html),
            "startup_gzip_bytes": gzip_size(app) + gzip_size(html),
            "gzip_note": "gzip level 9, mtime=0; startup = index.html + app JS",
        }
def build_site():
    template = TEMPLATE.read_text(encoding="utf-8")
    merge_source = MERGE_SOURCE.read_text(encoding="utf-8")
    sw_template = SW_TEMPLATE.read_text(encoding="utf-8")
    raw_decks = {
        key: json.loads((DATA / ("%s.json" % key)).read_text(encoding="utf-8"))
        for key in ("words", "derivatives", "basic", "insurance")
    }
    decks = {key: slim_rows(value) for key, value in raw_decks.items()}
    site_root = Path(tempfile.mkdtemp(prefix="ky-perf-site-"))
    try:
        (site_root / "data").mkdir(parents=True, exist_ok=True)
        assets = {}
        for deck_id, rows in decks.items():
            payload = json_block(rows)
            digest = sha256_bytes(payload.encode("utf-8"))[:12]
            rel = Path("data") / ("%s.%s.json" % (deck_id, digest))
            (site_root / rel).write_text(payload, encoding="utf-8", newline="\n")
            assets[deck_id] = "./" + rel.as_posix()
        meta = {
            "web": True,
            "deck_sizes": {key: len(value) for key, value in decks.items()},
            "assets": assets,
            "generated_at": "2026-10-29",
            "performance_fixture": True,
        }
        html = template
        for marker, value in (
            ("__DATA__", json_block(decks["words"][:40])),
            ("__DERIVATIVES__", json_block([])),
            ("__BASIC__", json_block([])),
            ("__INSURANCE__", json_block([])),
            ("__DETAIL__", json_block({})),
            ("__META__", json_block(meta)),
            ("/*__MERGE__*/", merge_source),
        ):
            html = inject_once(html, marker, value)
        match = re.search(r'<script id="ky-app">(.*?)</script>', html, re.S)
        if not match:
            raise PerfError('template is missing <script id="ky-app">')
        raw_app = match.group(1)
        state_shards = current_source_int(raw_app, "STATE_SHARD_COUNT")
        if state_shards != 64:
            raise PerfError("STATE_SHARD_COUNT=%d, expected 64" % state_shards)
        audio_ahead = current_source_int(raw_app, "AUDIO_PRELOAD_AHEAD")
        raw_app, shims = compatibility_shim(raw_app)
        npx = shutil.which("npx")
        if not npx:
            raise PerfError("npx is required to build the production-equivalent bundle")
        proc = subprocess.run(
            [npx, "--yes", "terser", "--compress", "--mangle", "--format", "comments=false"],
            input=raw_app.encode("utf-8"), capture_output=True, timeout=180, check=False,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            detail = proc.stderr.decode("utf-8", "replace")[:500]
            raise PerfError("terser failed: %s" % detail)
        app_js = proc.stdout.decode("utf-8")
        app_digest = sha256_bytes(app_js.encode("utf-8"))[:12]
        app_asset = "./app.%s.js" % app_digest
        (site_root / app_asset[2:]).write_text(app_js, encoding="utf-8", newline="\n")
        html = html[:match.start()] + html[match.end():]
        head_at = html.find("<head>")
        if head_at < 0:
            raise PerfError("template has no <head>")
        head_at += len("<head>")
        html = html[:head_at] + '\n<script defer fetchpriority="high" src="%s"></script>' % app_asset + html[head_at:]
        (site_root / "index.html").write_text(html, encoding="utf-8", newline="\n")
        build = sha256_bytes((app_js + sw_template + merge_source).encode("utf-8"))[:12]
        runtime_assets = [assets[key] for key in ("words", "derivatives", "basic", "insurance")]
        sw_js = (
            sw_template.replace("__BUILD_VERSION__", build)
            .replace("__APP_ASSET__", app_asset)
            .replace("__DATA_ASSETS__", json.dumps(runtime_assets, ensure_ascii=False))
        )
        (site_root / "sw.js").write_text(sw_js, encoding="utf-8", newline="\n")
        for name in ("manifest.webmanifest", "icon-192.png", "icon-512.png"):
            shutil.copy2(SOFTWARE / name, site_root / name)
        fingerprint_inputs = [TEMPLATE, SW_TEMPLATE, MERGE_SOURCE] + [
            DATA / ("%s.json" % key) for key in ("words", "derivatives", "basic", "insurance")
        ]
        source_fingerprint = sha256_bytes("\n".join(
            "%s:%s" % (path.relative_to(ROOT).as_posix(), sha256_file(path))
            for path in fingerprint_inputs
        ).encode("utf-8"))
        return BuiltSite(
            root=site_root, index_html=html, app_js=app_js, app_asset=app_asset,
            build=build, source_sha256=source_fingerprint, state_shard_count=state_shards,
            audio_preload_ahead=audio_ahead, audio_shims=shims,
            deck_sizes={key: len(value) for key, value in decks.items()},
        )
    except Exception:
        safe_rmtree(site_root, "ky-perf-site-")
        raise

def make_wav(seconds=0.083, rate=12000):
    count = max(1, int(seconds * rate))
    pcm = b"\x00\x00" * count
    return (
        b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
        + b"data" + struct.pack("<I", len(pcm)) + pcm
    )


AUDIO_WAV = make_wav()


class LocalPerfServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, site):
        super().__init__(address, handler)
        self.site = site
        self.lock = threading.Lock()
        self.audio_requests = []
        self.http_requests = []

    def record_http(self, method, path):
        with self.lock:
            self.http_requests.append({"at": time.perf_counter(), "method": method, "path": path})

    def audio_start(self, path):
        item = {"start": time.perf_counter(), "end": 0.0, "path": path}
        with self.lock:
            self.audio_requests.append(item)
        return item

    def audio_end(self, item):
        with self.lock:
            item["end"] = time.perf_counter()

    def audio_snapshot(self):
        with self.lock:
            return [dict(row) for row in self.audio_requests]


class PerfRequestHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, _fmt, *args):
        return

    def do_GET(self):
        self.server.record_http("GET", self.path)
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/api/audio":
            item = self.server.audio_start(self.path)
            try:
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(AUDIO_WAV)))
                self.send_header("Cache-Control", "public, max-age=31536000, immutable")
                self.send_header("X-Ky-Cache", "stored")
                self.send_header("Accept-Ranges", "none")
                self.end_headers()
                self.wfile.write(AUDIO_WAV)
            finally:
                self.server.audio_end(item)
            return
        if parsed.path == "/api/health":
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path.startswith("/api/"):
            body = b'{"ok":false,"error":"performance fixture has no API"}'
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def end_headers(self):
        path = urllib.parse.urlsplit(self.path).path
        if path in ("/", "/index.html"):
            self.send_header("Cache-Control", "no-store")
        elif path.endswith(".js") or path.startswith("/data/"):
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        elif path == "/sw.js":
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()


def start_server(site):
    handler = functools.partial(PerfRequestHandler, directory=str(site))
    server = LocalPerfServer(("127.0.0.1", 0), handler, site)
    thread = threading.Thread(target=server.serve_forever, name="ky-perf-http", daemon=True)
    thread.start()
    return server


def audio_key(path):
    parsed = urllib.parse.urlsplit(path)
    query = urllib.parse.parse_qs(parsed.query)
    word = (query.get("word") or query.get("text") or query.get("audio") or [""])[0]
    lang = (query.get("lang") or query.get("type") or ["en"])[0]
    return "%s:%s" % (lang, word or parsed.path)


def wait_audio_window(server, before, expected, timeout=12.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows = server.audio_snapshot()[before:]
        keys = {audio_key(row["path"]) for row in rows}
        if len(keys) >= expected and rows:
            return rows
        time.sleep(0.01)
    rows = server.audio_snapshot()[before:]
    raise PerfError("audio prefetch timeout: got %d unique, expected %d" % (
        len({audio_key(row["path"]) for row in rows}), expected
    ))


INIT_SCRIPT = r"""
(() => {
  try { localStorage.setItem('ky_auto_offline_v2', 'done'); } catch (_) {}
  const probe = {startedAt: performance.now(), first40At: 0, fill200At: 0, loadAt: 0, lastPosition: '', done: false};
  Object.defineProperty(window, '__kyPerfProbe', {value: probe, configurable: true});
  function sample() {
    const el = document.getElementById('position');
    const text = el ? (el.textContent || '').replace(/\s+/g, ' ').trim() : '';
    if (!text) return;
    probe.lastPosition = text;
    if (!probe.first40At && typeof queue !== 'undefined' && queue.length <= 40
        && typeof deckJson === 'function' && deckJson('words').length <= 40) {
      probe.first40At = performance.now();
    }
    if (probe.first40At && !probe.fill200At && typeof deckDataReady === 'function'
        && deckDataReady('core') && queue.length === 200) {
      probe.fill200At = performance.now();
      probe.done = true;
    }
  }
  const timer = setInterval(() => { sample(); if (probe.done) clearInterval(timer); }, 5);
  document.addEventListener('DOMContentLoaded', sample);
  window.addEventListener('load', () => { probe.loadAt = performance.now(); sample(); });
})();
"""


def page_probe(page):
    return page.evaluate(r"""
      () => {
        const nav = performance.getEntriesByType('navigation')[0] || {};
        const paints = {};
        for (const row of performance.getEntriesByType('paint')) paints[row.name] = row.startTime;
        const probe = window.__kyPerfProbe || {};
        return {
          fcp_ms: Number(paints['first-contentful-paint'] || 0),
          first_card_ms: Number(window.__firstCardAt || 0),
          dcl_ms: Number(nav.domContentLoadedEventEnd || 0),
          load_ms: Number(nav.loadEventEnd || probe.loadAt || 0),
          first_40_ms: Number(probe.first40At || 0),
          fill_200_ms: Number(probe.fill200At || 0),
          dom_nodes: document.querySelectorAll('*').length,
          position: document.getElementById('position')?.textContent?.replace(/\s+/g, ' ').trim() || '',
          queue_length: typeof queue === 'undefined' ? -1 : queue.length,
          ready: typeof deckDataReady === 'function' ? deckDataReady('core') : false
        };
      }
    """)


def launch_context(playwright, edge, profile, base_url, errors, requests, server=None):
    context = playwright.chromium.launch_persistent_context(
        str(profile), executable_path=str(edge), headless=True, service_workers="block",
        locale="zh-CN", viewport={"width": 1280, "height": 900},
        args=[
            "--disable-background-networking", "--disable-component-update", "--disable-extensions",
            "--disable-features=Translate,MediaRouter", "--no-default-browser-check", "--no-first-run",
            "--autoplay-policy=no-user-gesture-required",
        ],
    )
    context.add_init_script(INIT_SCRIPT)
    context.set_default_timeout(20000)

    def is_audio_request(request):
        lowered = request.url.lower()
        return any(token in lowered for token in ("audio", "dictvoice", "tts", "youdao", "baidu")) or request.resource_type == "media"

    def route_handler(route):
        url = route.request.url
        if url.startswith(base_url):
            route.continue_()
            return
        if is_audio_request(route.request):
            route.fulfill(status=200, body=AUDIO_WAV, headers={
                "Content-Type": "audio/wav", "Cache-Control": "no-store", "X-Ky-Cache": "stored",
            })
            return
        route.abort()

    audio_pending = {}

    def on_request(request):
        requests.append(request.url)
        if server is not None and not request.url.startswith(base_url) and is_audio_request(request):
            audio_pending[id(request)] = server.audio_start(request.url)

    def on_request_done(request):
        item = audio_pending.pop(id(request), None)
        if server is not None and item is not None:
            server.audio_end(item)

    context.route("**/*", route_handler)
    context.on("request", on_request)
    context.on("requestfinished", on_request_done)
    context.on("requestfailed", on_request_done)
    return context

def cold_measurement(playwright, edge, server, base_url):
    profile = Path(tempfile.mkdtemp(prefix="ky-perf-profile-"))
    errors, requests = [], []
    context = None
    try:
        context = launch_context(playwright, edge, profile, base_url, errors, requests, server)
        page = context.pages[0] if context.pages else context.new_page()
        page.on("pageerror", lambda exc: errors.append("pageerror: %s" % exc))
        page.goto(base_url, wait_until="load", timeout=60000)
        page.wait_for_function(
            "() => typeof queue !== 'undefined' && queue.length === 200 && deckDataReady('core')",
            timeout=30000,
        )
        page.wait_for_function("() => window.__kyPerfProbe && window.__kyPerfProbe.fill200At > 0", timeout=30000)
        data = page_probe(page)
        data["request_count"] = len(requests)
        data["browser_errors"] = list(errors)
        for key in ("fcp_ms", "first_card_ms", "dcl_ms", "load_ms", "first_40_ms", "fill_200_ms", "dom_nodes"):
            if not isinstance(data.get(key), (int, float)) or data[key] <= 0:
                raise PerfError("cold probe has invalid %s: %r" % (key, data.get(key)))
        if data["queue_length"] != 200 or "200" not in data["position"]:
            raise PerfError("first chapter did not reach 200: %r" % data)
        if data["fill_200_ms"] < data["first_40_ms"]:
            raise PerfError("40 to 200 timing is out of order: %r" % data)
        return data, context, errors, requests, profile
    except Exception:
        if context is not None:
            context.close()
        safe_rmtree(profile, "ky-perf-profile-")
        raise


def extended_measurements(page, built, server):
    chapter = page.evaluate(r"""
      () => {
        if (typeof loadChapter !== 'function' || deckIncomplete()) throw new Error('chapter probe not ready');
        const samples = [];
        for (let i = 0; i < 24; i += 1) {
          const target = i % 2 === 0 ? 1 : 0;
          const start = performance.now();
          loadChapter(target, undefined, 0, undefined, false, true);
          const elapsed = performance.now() - start;
          const word = document.getElementById('word')?.textContent?.trim() || '';
          if (!word || word === '加载中…') throw new Error('chapter switch did not render a card');
          samples.push(elapsed);
        }
        loadChapter(0, undefined, 0, undefined, false, true);
        return {samples, chapter_size: CHAPTER_SIZE, queue: queue.length};
      }
    """)

    vocabulary = page.evaluate(r"""
      () => {
        switchView('List');
        const terms = ['a', 'e', 'tion', 'pre', 'con', 're'];
        const searchSamples = [], matchCounts = [];
        for (let i = 0; i < 24; i += 1) {
          searchText = terms[i % terms.length];
          listQueryCache.key = '';
          const start = performance.now();
          renderList(true);
          searchSamples.push(performance.now() - start);
          matchCounts.push(listMatches.length);
        }
        const pageSamples = [], pageCounts = [];
        for (let cycle = 0; cycle < 8; cycle += 1) {
          searchText = '';
          priorityFilter = 'all';
          listQueryCache.key = '';
          listLimit = LIST_PAGE_SIZE;
          renderList(true);
          for (let pageNo = 2; pageNo <= 5; pageNo += 1) {
            const start = performance.now();
            listLimit = LIST_PAGE_SIZE * pageNo;
            renderList(false);
            pageSamples.push(performance.now() - start);
            pageCounts.push(document.getElementById('wordList').children.length);
          }
        }
        searchText = '';
        priorityFilter = 'all';
        listQueryCache.key = '';
        switchView('Study');
        return {search_samples: searchSamples, search_match_counts: matchCounts,
          pagination_samples: pageSamples, pagination_node_counts: pageCounts, page_size: LIST_PAGE_SIZE};
      }
    """)

    state = page.evaluate(r"""
      (shardCount) => {
        const oldAuth = authUser, oldState = state, oldRevision = stateRevision;
        const fullKey = '__ky_perf_full_state__', scope = '__perf_state_64__', records = 2400;
        const full = {};
        for (let i = 0; i < records; i += 1) {
          const name = 'perf-' + String(i).padStart(5, '0');
          full[name] = {w: (i % 4) + 1, seen: '2026-10-29T12:34:56.789Z', t: 1793200000000 + i};
        }
        try {
          if (STATE_SHARD_COUNT !== shardCount) throw new Error('shard constant changed while probing');
          authUser = scope;
          for (const key of Object.keys(localStorage)) if (key.includes('@' + scope)) localStorage.removeItem(key);
          localStorage.removeItem(fullKey);
          const fullText = JSON.stringify(full);
          const fullSamples = [];
          for (let i = 0; i < 60; i += 1) {
            const name = 'perf-' + String(i % records).padStart(5, '0');
            full[name] = {w: (i % 4) + 1, seen: '2026-10-29T12:35:00.000Z', t: 1793201000000 + i};
            const start = performance.now();
            localStorage.setItem(fullKey, JSON.stringify(full));
            fullSamples.push(performance.now() - start);
          }
          state = full;
          const initialStart = performance.now();
          if (!writeStateStorageForScope(state, authUser)) throw new Error('initial sharded write failed');
          const shardedInitialMs = performance.now() - initialStart;
          const generation = stateMetaForScope(authUser);
          if (!generation) throw new Error('sharded meta missing');
          const shardSamples = [];
          for (let i = 0; i < 60; i += 1) {
            const name = 'perf-' + String((i * 17) % records).padStart(5, '0');
            state[name] = {w: (i % 4) + 1, seen: '2026-10-29T12:36:00.000Z', t: 1793202000000 + i};
            const start = performance.now();
            if (!saveStateRecord(name)) throw new Error('sharded record write failed');
            shardSamples.push(performance.now() - start);
          }
          let maxShardBytes = 0, shardKeys = 0;
          for (let i = 0; i < shardCount; i += 1) {
            const row = localStorage.getItem(stateShardStorageKey(generation, i, authUser));
            if (row) {
              shardKeys += 1;
              maxShardBytes = Math.max(maxShardBytes, new TextEncoder().encode(row).length);
            }
          }
          const meta = localStorage.getItem(LS_STATE + '#meta@' + scope);
          return {shard_count: shardCount, records, full_samples: fullSamples, sharded_samples: shardSamples,
            full_json_bytes: new TextEncoder().encode(fullText).length, sharded_initial_ms: shardedInitialMs,
            max_shard_bytes: maxShardBytes, shard_keys: shardKeys, meta_ok: meta === '2:' + generation};
        } finally {
          try {
            authUser = scope;
            for (const key of Object.keys(localStorage)) if (key.includes('@' + scope)) localStorage.removeItem(key);
            localStorage.removeItem(fullKey);
          } catch (_) {}
          authUser = oldAuth;
          state = oldState;
          stateRevision = oldRevision;
          listQueryCache.key = '';
        }
      }
    """, built.state_shard_count)
    if not state.get("meta_ok") or state.get("shard_keys") != built.state_shard_count:
        raise PerfError("64-shard state probe incomplete: %r" % state)

    sync_snapshot = page.evaluate(r"""
      async () => {
        const oldState = state, oldRevision = stateRevision, synthetic = {};
        for (let i = 0; i < 2400; i += 1) {
          synthetic['sync-' + String(i).padStart(5, '0')] = {
            w: (i % 4) + 1, mastered: i % 9 === 0, seen: '2026-10-29T12:00:00.000Z', t: 1793200000000 + i
          };
        }
        const serializeSamples = [], gzipSamples = [];
        try {
          state = synthetic;
          let payloadText = '';
          for (let i = 0; i < 24; i += 1) {
            const start = performance.now();
            payloadText = JSON.stringify(snapshot());
            serializeSamples.push(performance.now() - start);
          }
          let gzipBytes = 0;
          for (let i = 0; i < 6; i += 1) {
            const start = performance.now();
            const body = await new Response(
              new Blob([payloadText], {type: 'application/json'}).stream().pipeThrough(new CompressionStream('gzip'))
            ).arrayBuffer();
            gzipBytes = body.byteLength;
            gzipSamples.push(performance.now() - start);
          }
          return {serialize_samples: serializeSamples, gzip_samples: gzipSamples,
            raw_bytes: new TextEncoder().encode(payloadText).length, gzip_bytes: gzipBytes,
            record_count: Object.keys(synthetic).length};
        } finally {
          state = oldState;
          stateRevision = oldRevision;
          listQueryCache.key = '';
        }
      }
    """)
    if sync_snapshot.get("raw_bytes", 0) <= 0 or sync_snapshot.get("gzip_bytes", 0) <= 0:
        raise PerfError("sync snapshot result invalid: %r" % sync_snapshot)
    expected_audio = built.audio_preload_ahead + 1
    page.evaluate(r"""
      () => {
        conf.speak = false;
        loadChapter(0, undefined, 0, undefined, false, true);
      }
    """)
    audio_samples = []
    for chapter_index in range(4):
        page.evaluate(r"""
          (chapter) => {
            window.__kyAudioWindowStart = performance.now();
            window.__kyAudioBeforeKeys = Array.from(audioPlayers.keys());
            if (chapter > 0) loadChapter(chapter, undefined, 0, undefined, false, true);
          }
        """, chapter_index)
        if chapter_index == 0:
            page.mouse.click(2, 2)
        page.wait_for_function(r"""
          (expected) => {
            const before = new Set(window.__kyAudioBeforeKeys || []);
            return Array.from(audioPlayers.keys()).filter(key => !before.has(key)).length >= expected;
          }
        """, arg=expected_audio, timeout=8000)
        elapsed = page.evaluate("() => performance.now() - window.__kyAudioWindowStart")
        unique_audio = page.evaluate(r"""
          () => {
            const before = new Set(window.__kyAudioBeforeKeys || []);
            return Array.from(audioPlayers.keys()).filter(key => !before.has(key)).length;
          }
        """)
        audio_samples.append({
            "chapter": chapter_index, "elapsed_ms": float(elapsed),
            "requests": int(unique_audio), "unique_audio": int(unique_audio),
        })
        if unique_audio < expected_audio:
            raise PerfError("audio window too small: chapter=%d unique=%d expected=%d" % (
                chapter_index, unique_audio, expected_audio
            ))

    return {
        "chapter_switch": {"samples": chapter["samples"], "chapter_size": chapter["chapter_size"],
          "queue": chapter["queue"]},
        "vocabulary": vocabulary,
        "local_storage_state": state,
        "sync_snapshot": sync_snapshot,
        "audio_prefetch": {"source_ahead": built.audio_preload_ahead,
          "expected_window": expected_audio, "windows": audio_samples},
    }


def normalize_extended(raw):
    chapter = raw["chapter_switch"]
    vocab = raw["vocabulary"]
    local_state = raw["local_storage_state"]
    sync_snapshot = raw["sync_snapshot"]
    audio = raw["audio_prefetch"]
    return {
        "chapter_switch_ms": stats(chapter["samples"]),
        "vocabulary": {
            "search_ms": stats(vocab["search_samples"]),
            "search_match_counts": vocab["search_match_counts"],
            "pagination_ms": stats(vocab["pagination_samples"]),
            "pagination_node_counts": vocab["pagination_node_counts"],
            "page_size": vocab["page_size"],
        },
        "local_storage_state": {
            "shard_count": local_state["shard_count"],
            "records": local_state["records"],
            "full_write_ms": stats(local_state["full_samples"]),
            "sharded_write_ms": stats(local_state["sharded_samples"]),
            "full_json_bytes": local_state["full_json_bytes"],
            "max_shard_bytes": local_state["max_shard_bytes"],
            "shard_keys": local_state["shard_keys"],
            "sharded_initial_write_ms": round(local_state["sharded_initial_ms"], 2),
        },
        "sync_snapshot": {
            "serialize_ms": stats(sync_snapshot["serialize_samples"]),
            "gzip_ms": stats(sync_snapshot["gzip_samples"]),
            "raw_bytes": sync_snapshot["raw_bytes"],
            "gzip_bytes": sync_snapshot["gzip_bytes"],
            "record_count": sync_snapshot["record_count"],
        },
        "audio_prefetch": {
            "source_ahead": audio["source_ahead"],
            "expected_window": audio["expected_window"],
            "windows": audio["windows"],
            "elapsed_ms": stats([row["elapsed_ms"] for row in audio["windows"]]),
            "request_count": [row["unique_audio"] for row in audio["windows"]],
        },
    }

def run_baseline(runs=5):
    if runs < 1:
        raise PerfError("--runs must be >= 1")
    edge = find_edge()
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise PerfError("Playwright is unavailable: %s" % exc) from exc
    built = build_site()
    server = None
    try:
        server = start_server(built.root)
        base_url = "http://127.0.0.1:%d/" % server.server_address[1]
        cold_rows = []
        extended_raw = None
        browser_version = ""
        with sync_playwright() as playwright:
            for index in range(runs):
                row, context, errors, _requests, profile = cold_measurement(playwright, edge, server, base_url)
                try:
                    browser_version = context.browser.version if context.browser else browser_version
                    if index == 0:
                        extended_raw = extended_measurements(context.pages[0], built, server)
                    if errors:
                        raise PerfError("browser page errors: " + " | ".join(errors[:5]))
                finally:
                    try:
                        context.close()
                    finally:
                        safe_rmtree(profile, "ky-perf-profile-")
                cold_rows.append(row)
        if extended_raw is None:
            raise PerfError("extended probes did not run")
        cold_metrics = {
            "fcp_ms": stats([row["fcp_ms"] for row in cold_rows]),
            "first_card_ms": stats([row["first_card_ms"] for row in cold_rows]),
            "dcl_ms": stats([row["dcl_ms"] for row in cold_rows]),
            "load_ms": stats([row["load_ms"] for row in cold_rows]),
            "dom_nodes": stats([row["dom_nodes"] for row in cold_rows], 0),
            "request_count": stats([row["request_count"] for row in cold_rows], 0),
        }
        fill_time = [row["fill_200_ms"] - row["first_40_ms"] for row in cold_rows]
        fill_after_nav = [row["fill_200_ms"] for row in cold_rows]
        extended = normalize_extended(extended_raw)
        result = {
            "schema": 1,
            "measured_at": utc_now(),
            "commit": run_git("rev-parse", "HEAD"),
            "target": {
                "template": str(TEMPLATE.relative_to(ROOT)),
                "template_sha256": sha256_file(TEMPLATE),
                "source_fingerprint": built.source_sha256,
                "build": built.build,
                "state_shard_count": built.state_shard_count,
                "deck_sizes": built.deck_sizes,
                "audio_shims": built.audio_shims,
                "local_http": base_url,
                "real_external_audio": False,
            },
            "environment": {
                "edge": str(edge), "browser_version": browser_version, "headless": True,
                "fresh_profile_per_cold_sample": True, "service_workers": "blocked", "external_requests": "aborted except local WAV fixtures", "runs": runs,
                "audio_fixture": "valid 0.083s PCM WAV",
            },
            "bundle_gzip": built.bundle(),
            "cold_start": {"samples": runs, "metrics": cold_metrics, "raw": cold_rows},
            "first_chapter_fill": {
                "from": 40, "to": 200, "fill_ms": stats(fill_time),
                "fill_from_navigation_ms": stats(fill_after_nav), "samples": runs,
            },
            **extended,
        }
        validate_result(result)
        return result
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        safe_rmtree(built.root, "ky-perf-site-")


def validate_result(result):
    paths = (
        ("bundle_gzip", "app_gzip_bytes"), ("bundle_gzip", "startup_gzip_bytes"),
        ("cold_start", "metrics"), ("first_chapter_fill", "fill_ms"),
        ("chapter_switch_ms", "p95"), ("vocabulary", "search_ms"),
        ("vocabulary", "pagination_ms"), ("local_storage_state", "full_write_ms"),
        ("local_storage_state", "sharded_write_ms"), ("audio_prefetch", "elapsed_ms"),
        ("sync_snapshot", "serialize_ms"), ("sync_snapshot", "gzip_ms"),
    )
    for path in paths:
        value = result
        for key in path:
            if not isinstance(value, dict) or key not in value:
                raise PerfError("result missing field %s" % ".".join(path))
            value = value[key]
        if value is None or value == "":
            raise PerfError("result field %s is empty" % ".".join(path))
    state = result["local_storage_state"]
    if state.get("shard_count") != 64 or state.get("shard_keys") != 64:
        raise PerfError("64-shard state baseline is incomplete")
    if result["target"].get("real_external_audio") is not False:
        raise PerfError("external-audio isolation assertion failed")


def measure():
    """Backward-compatible one-run entry point used by run_tests.py."""
    result = run_baseline(runs=1)
    cold = result["cold_start"]["raw"][0]
    return {
        "fcp": round(cold["fcp_ms"]), "dcl": round(cold["dcl_ms"]),
        "load": round(cold["load_ms"]), "firstCard": round(cold["first_card_ms"]),
        "nodes": round(cold["dom_nodes"]),
        "firstChapterFillMs": round(result["first_chapter_fill"]["fill_ms"]["p50"]),
        "bundleGzipBytes": result["bundle_gzip"]["startup_gzip_bytes"],
        "baseline": result,
    }

def human_report(result):
    bundle = result["bundle_gzip"]
    cold = result["cold_start"]["metrics"]
    fill = result["first_chapter_fill"]["fill_ms"]
    chapter = result["chapter_switch_ms"]
    vocab = result["vocabulary"]
    state = result["local_storage_state"]
    audio = result["audio_prefetch"]
    sync_snapshot = result["sync_snapshot"]
    return "\n".join([
        "Performance baseline",
        "  build                 %s" % result["target"]["build"],
        "  app gzip              %d bytes" % bundle["app_gzip_bytes"],
        "  startup bundle gzip   %d bytes (index %d + app %d)" % (
            bundle["startup_gzip_bytes"], bundle["index_gzip_bytes"], bundle["app_gzip_bytes"]),
        "Cold start (fresh Edge profile, n=%d)" % result["cold_start"]["samples"],
        "  FCP p50/p95           %.2f / %.2f ms" % (cold["fcp_ms"]["p50"], cold["fcp_ms"]["p95"]),
        "  first card p50/p95    %.2f / %.2f ms" % (cold["first_card_ms"]["p50"], cold["first_card_ms"]["p95"]),
        "  DCL p50/p95           %.2f / %.2f ms" % (cold["dcl_ms"]["p50"], cold["dcl_ms"]["p95"]),
        "  DOM nodes p50/p95     %d / %d" % (cold["dom_nodes"]["p50"], cold["dom_nodes"]["p95"]),
        "  first chapter 40->200 %.2f / %.2f ms" % (fill["p50"], fill["p95"]),
        "  chapter switch        %.2f / %.2f ms" % (chapter["p50"], chapter["p95"]),
        "  search                %.2f / %.2f ms" % (vocab["search_ms"]["p50"], vocab["search_ms"]["p95"]),
        "  pagination            %.2f / %.2f ms" % (vocab["pagination_ms"]["p50"], vocab["pagination_ms"]["p95"]),
        "LocalStorage state (64 shards, %d records)" % state["records"],
        "  full write            %.2f / %.2f ms (%d bytes)" % (
            state["full_write_ms"]["p50"], state["full_write_ms"]["p95"], state["full_json_bytes"]),
        "  sharded write         %.2f / %.2f ms (max shard %d bytes)" % (
            state["sharded_write_ms"]["p50"], state["sharded_write_ms"]["p95"], state["max_shard_bytes"]),
        "Audio prefetch (local WAV only)",
        "  window                %d requests" % audio["expected_window"],
        "  elapsed p50/p95       %.2f / %.2f ms" % (audio["elapsed_ms"]["p50"], audio["elapsed_ms"]["p95"]),
        "Sync snapshot (%d records)" % sync_snapshot["record_count"],
        "  serialize p50/p95     %.2f / %.2f ms" % (
            sync_snapshot["serialize_ms"]["p50"], sync_snapshot["serialize_ms"]["p95"]),
        "  gzip p50/p95          %.2f / %.2f ms (%d -> %d bytes)" % (
            sync_snapshot["gzip_ms"]["p50"], sync_snapshot["gzip_ms"]["p95"],
            sync_snapshot["raw_bytes"], sync_snapshot["gzip_bytes"]),
    ])


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="Local Edge/CDP performance baseline")
    parser.add_argument("--runs", type=int, default=5, help="fresh-profile cold samples (default: 5)")
    parser.add_argument("--json", action="store_true", help="print complete JSON")
    parser.add_argument("--out", help="optionally write JSON to this path")
    args = parser.parse_args(argv)
    try:
        result = run_baseline(args.runs)
        if args.out:
            target = Path(args.out)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("w", encoding="utf-8", newline="\n") as fh:
                json.dump(result, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(human_report(result))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc), "type": type(exc).__name__}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())