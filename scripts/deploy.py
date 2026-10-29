# -*- coding: utf-8 -*-
"""构建、门禁测试并部署到 Cloudflare Pages。

用法：
    python scripts/deploy.py
    python scripts/deploy.py --skip-test
    python scripts/deploy.py --allow-pending-migrations
    python scripts/deploy.py --allow-dirty-release
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT = "kaoyan2-words"
PUBLIC_URL = "https://kaoyan2-words.pages.dev"
LOCK = ROOT / "deploy.publish.lock"
LOCK_STALE_SECONDS = 30 * 60
RELEASE_COOLDOWN_SECONDS = 10 * 60
LAST_RELEASE = ROOT / ".git" / "ky-last-release.json"
MIGRATIONS_LEDGER = ROOT / "backend" / "migrations" / "applied.json"
EDGE_CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)
CDP_TIMEOUT_SECONDS = 60


def cf_env():
    """优先使用 .wrangler 下被 git 忽略的 API Token。"""
    env = dict(os.environ)
    for key, name in (("CLOUDFLARE_API_TOKEN", ".cf_token"), ("CLOUDFLARE_ACCOUNT_ID", ".cf_account")):
        path = ROOT / ".wrangler" / name
        try:
            if path.exists():
                env[key] = path.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    return env


def run(cmd, **kw):
    return subprocess.run(cmd, cwd=ROOT, **kw)


def acquire_lock():
    try:
        fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            age = time.time() - LOCK.stat().st_mtime
        except OSError:
            age = 0
        if age < LOCK_STALE_SECONDS:
            raise RuntimeError("另一个发布正在进行（deploy.publish.lock 未过期）")
        try:
            LOCK.unlink()
        except OSError:
            pass
        fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode("ascii"))
    return fd


def release_lock(fd):
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        LOCK.unlink()
    except OSError:
        pass


def migration_sha256(path):
    # checkout 的 autocrlf 会把迁移脚本改成 CRLF，哈希必须与换行符无关，
    # 否则干净 checkout 会把已执行的迁移误判成待执行。
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def applied_migration_hashes():
    try:
        payload = json.loads(MIGRATIONS_LEDGER.read_text(encoding="utf-8"))
        applied = payload.get("applied", {})
        return applied if isinstance(applied, dict) else {}
    except (OSError, ValueError):
        return {}


def pending_migrations():
    folder = ROOT / "backend" / "migrations"
    if not folder.is_dir():
        return []
    applied = applied_migration_hashes()
    pending = []
    for path in sorted(folder.glob("*.sql")):
        entry = applied.get(path.name)
        expected = entry.get("sha256") if isinstance(entry, dict) else ""
        if not expected or expected != migration_sha256(path):
            pending.append(path)
    return pending


def recent_release_activity():
    now = time.time()
    blocked = []
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ct %H"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            stamp, commit = result.stdout.strip().split(None, 1)
            age = now - float(stamp)
            if age < RELEASE_COOLDOWN_SECONDS:
                blocked.append("commit %s 仅 %.0f 秒前" % (commit[:12], max(0, age)))
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("无法检查最近提交时间：" + str(exc))
    try:
        marker = json.loads(LAST_RELEASE.read_text(encoding="utf-8"))
        released_at = float(marker.get("releasedAt", 0)) / 1000
        age = now - released_at
        if released_at > 0 and age < RELEASE_COOLDOWN_SECONDS:
            blocked.append("上次发布仅 %.0f 秒前" % max(0, age))
    except (OSError, ValueError, TypeError):
        pass
    return blocked


def record_release(meta, deployment_id, deployment_url):
    marker = {
        "releasedAt": int(time.time() * 1000),
        "commit": meta.get("commit", ""),
        "build": meta.get("build", ""),
        "deploymentId": deployment_id or "",
        "deploymentUrl": deployment_url,
    }
    LAST_RELEASE.parent.mkdir(parents=True, exist_ok=True)
    LAST_RELEASE.write_text(json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def output_value(text, pattern):
    match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip() if match else ""


def worktree_changes():
    cmd = [
        "git", "status", "--porcelain=v1", "--untracked-files=all", "--", ".",
        ":(exclude)deploy.publish.lock",
    ]
    try:
        result = subprocess.run(
            cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("无法确认工作区状态：" + str(exc))
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError("无法确认工作区状态：" + (detail or "git status 失败"))
    return [line for line in result.stdout.splitlines() if line.strip()]


def load_release_artifact():
    path = ROOT / "deploy" / "build-meta.json"
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("无法读取构建元数据：" + str(exc))
    app_asset = str(meta.get("app_asset", ""))
    match = re.fullmatch(r"\./app\.([0-9a-f]{12})\.js", app_asset)
    if not meta.get("build") or not match:
        raise RuntimeError("build-meta.json 缺少有效的 build/app_asset")
    app_path = ROOT / "deploy" / app_asset[2:]
    try:
        app_bytes = app_path.read_bytes()
    except OSError as exc:
        raise RuntimeError("无法读取构建主程序：" + str(exc))
    app_digest = hashlib.sha256(app_bytes).hexdigest()[:12]
    if app_digest != match.group(1):
        raise RuntimeError("app_asset 文件名与主程序内容 hash 不一致")
    return meta, app_bytes, app_digest


def http_bytes(url, timeout=60):
    # Cloudflare Pages ??? Windows ?????? Python/OpenSSL ? TLS?
    # curl ??????? KB??? PowerShell ? Invoke-WebRequest ???
    # ??????????? HTTP ??????????????????
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if shell:
        handle, name = tempfile.mkstemp(prefix="ky-http-", suffix=".bin")
        os.close(handle)
        env = dict(os.environ)
        env.update({
            "KY_HTTP_URL": url,
            "KY_HTTP_OUT": name,
            "KY_HTTP_TIMEOUT": str(max(1, int(timeout))),
        })
        ps = (
            "$ProgressPreference='SilentlyContinue'; "
            "$r=Invoke-WebRequest -UseBasicParsing -Uri $env:KY_HTTP_URL "
            "-OutFile $env:KY_HTTP_OUT -TimeoutSec ([int]$env:KY_HTTP_TIMEOUT); "
            "[Console]::Out.Write([int]$r.StatusCode)"
        )
        try:
            result = subprocess.run(
                [shell, "-NoProfile", "-NonInteractive", "-Command", ps],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=timeout + 15, env=env,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "PowerShell HTTP failed").strip()
                raise RuntimeError("HTTP ?????" + detail[:240])
            return 200, Path(name).read_bytes()
        finally:
            try:
                Path(name).unlink()
            except OSError:
                pass

    req = urllib.request.Request(
        url, headers={"user-agent": "ky-deploy-check/2", "cache-control": "no-cache"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.status, response.read()


def verify_release(base_url, meta, app_bytes, app_digest):
    base = base_url.rstrip("/")
    suffix = "?deploy_check=%d" % time.time_ns()
    try:
        _, body = http_bytes(base + "/build-meta.json" + suffix)
        remote = json.loads(body.decode("utf-8", "replace"))
        if remote != meta:
            return False, "build-meta 不一致"
        _, body = http_bytes(base + "/sw.js" + suffix)
        sw = body.decode("utf-8", "replace")
        if "BUILD_VERSION = '" + meta["build"] + "'" not in sw:
            return False, "SW 版本不一致"
        if "APP_ASSET = '" + meta["app_asset"] + "'" not in sw:
            return False, "SW 主程序 hash 不一致"
        _, body = http_bytes(base + "/" + suffix)
        html = body.decode("utf-8", "replace")
        if 'src="' + meta["app_asset"] + '"' not in html:
            return False, "线上 HTML 未引用 build-meta 对应主程序"
        _, remote_app = http_bytes(base + "/" + meta["app_asset"][2:] + suffix)
        if remote_app != app_bytes:
            return False, "线上主程序内容与本地构建不一致"
        if hashlib.sha256(remote_app).hexdigest()[:12] != app_digest:
            return False, "线上主程序内容 hash 不一致"
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


def find_edge():
    configured = os.environ.get("EDGE_PATH", "").strip()
    commands = [configured] if configured else []
    commands.extend([shutil.which("msedge"), shutil.which("microsoft-edge")])
    commands.extend(EDGE_CANDIDATES)
    for candidate in commands:
        try:
            if candidate and Path(candidate).is_file():
                return str(candidate)
        except OSError:
            continue
    return ""


def stop_process(process):
    if process is None:
        return
    try:
        if process.poll() is not None:
            return
        process.terminate()
        process.wait(timeout=10)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        process.kill()
    except OSError:
        pass
    try:
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


def local_json(url, timeout=2):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def wait_devtools_port(profile, process, timeout=20):
    marker = Path(profile) / "DevToolsActivePort"
    deadline = time.time() + timeout
    last = "没有生成 DevToolsActivePort"
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Edge 提前退出，返回码 %s" % process.returncode)
        try:
            lines = marker.read_text(encoding="ascii").splitlines()
            if lines:
                return int(lines[0].strip())
        except (OSError, ValueError) as exc:
            last = str(exc)
        time.sleep(0.2)
    raise RuntimeError("Edge DevTools 启动失败：" + last)


def wait_page_target(port, base_url, timeout=20):
    deadline = time.time() + timeout
    endpoint = "http://127.0.0.1:%d/json/list" % port
    last = "没有页面 target"
    wanted_origin = urllib.parse.urlsplit(base_url).netloc
    while time.time() < deadline:
        try:
            targets = local_json(endpoint)
            pages = [
                item for item in targets
                if item.get("type") == "page" and item.get("webSocketDebuggerUrl")
            ]
            if pages:
                for item in pages:
                    if urllib.parse.urlsplit(item.get("url", "")).netloc == wanted_origin:
                        return item
                return pages[0]
        except (OSError, ValueError) as exc:
            last = str(exc)
        time.sleep(0.2)
    raise RuntimeError("Edge 页面 target 不可用：" + last)


class DevToolsSocket:
    def __init__(self, url):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "ws" or not parsed.hostname or not parsed.port:
            raise RuntimeError("无效的 DevTools WebSocket 地址")
        self.sock = socket.create_connection((parsed.hostname, parsed.port), timeout=CDP_TIMEOUT_SECONDS)
        self.next_id = 0
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        path = parsed.path + (("?" + parsed.query) if parsed.query else "")
        request = (
            "GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\n"
            "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ) % (path, parsed.hostname, parsed.port, key)
        self.sock.sendall(request.encode("ascii"))
        header = b""
        while b"\r\n\r\n" not in header:
            chunk = self.sock.recv(1)
            if not chunk:
                raise RuntimeError("DevTools WebSocket 握手中断")
            header += chunk
            if len(header) > 16384:
                raise RuntimeError("DevTools WebSocket 握手响应过大")
        lines = header.decode("iso-8859-1").split("\r\n")
        if not lines or " 101 " not in (" " + lines[0] + " "):
            raise RuntimeError("DevTools WebSocket 握手失败：" + lines[0])
        expected = base64.b64encode(hashlib.sha1(
            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
        ).digest()).decode("ascii")
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                name, value = line.split(":", 1)
                headers[name.strip().lower()] = value.strip()
        if headers.get("sec-websocket-accept") != expected:
            raise RuntimeError("DevTools WebSocket 校验失败")

    def close(self):
        try:
            self._send_frame(8, b"")
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass

    def _send_frame(self, opcode, payload):
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length <= 0xFFFF:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def _recv_exact(self, size):
        data = b""
        while len(data) < size:
            chunk = self.sock.recv(size - len(data))
            if not chunk:
                raise RuntimeError("DevTools WebSocket 已关闭")
            data += chunk
        return data

    def _recv_frame(self):
        first, second = self._recv_exact(2)
        fin = bool(first & 0x80)
        opcode = first & 0x0F
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if second & 0x80 else b""
        payload = self._recv_exact(length)
        if mask:
            payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        return fin, opcode, payload

    def _recv_message(self):
        chunks = []
        message_opcode = None
        while True:
            fin, opcode, payload = self._recv_frame()
            if opcode == 8:
                raise RuntimeError("DevTools WebSocket 被关闭")
            if opcode == 9:
                self._send_frame(10, payload)
                continue
            if opcode == 10:
                continue
            if opcode in (1, 2):
                message_opcode = opcode
                chunks = [payload]
            elif opcode == 0 and message_opcode is not None:
                chunks.append(payload)
            else:
                raise RuntimeError("DevTools WebSocket 收到未知帧")
            if fin:
                return message_opcode, b"".join(chunks)

    def call(self, method, params=None):
        self.next_id += 1
        request_id = self.next_id
        payload = json.dumps(
            {"id": request_id, "method": method, "params": params or {}},
            ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")
        self._send_frame(1, payload)
        while True:
            opcode, body = self._recv_message()
            if opcode != 1:
                continue
            message = json.loads(body.decode("utf-8", "replace"))
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError("DevTools %s 失败：%s" % (method, message["error"]))
            return message.get("result", {})


def evaluate_js(devtools, expression):
    payload = devtools.call("Runtime.evaluate", {
        "expression": expression,
        "awaitPromise": True,
        "returnByValue": True,
    })
    if payload.get("exceptionDetails"):
        details = payload["exceptionDetails"]
        description = details.get("exception", {}).get("description") or details.get("text")
        raise RuntimeError("页面脚本执行失败：" + str(description)[:300])
    return (payload.get("result") or {}).get("value")


def page_state_expression(app_asset):
    expression = r"""
(() => {
  const expected = new URL(__APP_ASSET__, location.href).pathname;
  const toPath = value => {
    try { return new URL(value, location.href).pathname; } catch (_) { return ''; }
  };
  const wordNode = document.querySelector('#word');
  const word = wordNode ? String(wordNode.textContent || '').trim() : '';
  return {
    href: location.href,
    ready: document.readyState,
    word,
    pending: !word || word.startsWith('加载中') || word.startsWith('加载失败'),
    app_script: Array.from(document.scripts).some(node => node.src && toPath(node.src) === expected),
    app_resource: performance.getEntriesByType('resource').some(entry => toPath(entry.name) === expected)
  };
})()
"""
    return expression.replace("__APP_ASSET__", json.dumps(app_asset, ensure_ascii=False))


def wait_page_state(devtools, app_asset, timeout=40):
    deadline = time.time() + timeout
    last = {}
    last_error = ""
    while time.time() < deadline:
        try:
            state = evaluate_js(devtools, page_state_expression(app_asset)) or {}
            last = state
            if (
                state.get("ready") == "complete"
                and not state.get("pending")
                and state.get("app_script") is True
                and state.get("app_resource") is True
            ):
                return state, ""
        except RuntimeError as exc:
            last_error = str(exc)
        time.sleep(0.5)
    if last_error:
        return None, last_error
    return None, "页面未完成加载或 build-meta 对应主程序未实际执行：%s" % json.dumps(last, ensure_ascii=False)


def service_worker_expression():
    return r"""
(async () => {
  const out = {supported: false, registered: false, active: false, controlled: false};
  if (!('serviceWorker' in navigator)) return out;
  out.supported = true;
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  try {
    const registration = await Promise.race([
      navigator.serviceWorker.ready,
      new Promise((_, reject) => setTimeout(() => reject(new Error('service worker ready timeout')), 20000))
    ]);
    out.registered = !!registration;
    out.active = !!(registration && registration.active && registration.active.state === 'activated');
    out.scope = registration && registration.scope;
  } catch (error) {
    out.error = String(error && (error.message || error));
  }
  const deadline = Date.now() + 10000;
  while (!navigator.serviceWorker.controller && Date.now() < deadline) await sleep(200);
  const controller = navigator.serviceWorker.controller;
  out.controlled = !!controller;
  if (controller) {
    try { out.controller_path = new URL(controller.scriptURL).pathname; } catch (_) {}
  }
  return out;
})()
"""


def inspect_browser_release(devtools, meta, app_digest):
    expression = r"""
(async () => {
  const expectedMeta = __META__;
  const expectedDigest = __DIGEST__;
  const result = {};
  const pathOf = value => {
    try { return new URL(value, location.href).pathname; } catch (_) { return ''; }
  };
  try {
    const suffix = '?deploy_check=' + Date.now();
    const metaResponse = await fetch('/build-meta.json' + suffix, {cache: 'no-store'});
    result.meta_status = metaResponse.status;
    const remoteMeta = await metaResponse.json();
    result.meta_match = remoteMeta.build === expectedMeta.build
      && remoteMeta.app_asset === expectedMeta.app_asset
      && remoteMeta.source_digest === expectedMeta.source_digest;

    const appPath = pathOf(expectedMeta.app_asset);
    const appResponse = await fetch(expectedMeta.app_asset + suffix, {cache: 'no-store'});
    result.app_status = appResponse.status;
    const appBytes = await appResponse.arrayBuffer();
    const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', appBytes)))
      .map(value => value.toString(16).padStart(2, '0')).join('');
    result.app_digest_match = digest.slice(0, 12) === expectedDigest;
    result.app_script = Array.from(document.scripts)
      .some(node => node.src && pathOf(node.src) === appPath);
    result.app_resource = performance.getEntriesByType('resource')
      .some(entry => pathOf(entry.name) === appPath);

    const worker = navigator.serviceWorker;
    result.sw_controlled = !!(worker && worker.controller);
    result.sw_controller_ok = !!(worker && worker.controller
      && pathOf(worker.controller.scriptURL) === '/sw.js');
    const registrations = worker ? await worker.getRegistrations() : [];
    result.sw_active = registrations.some(registration => registration.active
      && registration.active.state === 'activated'
      && pathOf(registration.active.scriptURL) === '/sw.js');

    const cacheName = 'ky-shell-' + expectedMeta.build;
    const cache = await caches.open(cacheName);
    const keys = await cache.keys();
    result.cache_has_app = keys.some(request => pathOf(request.url) === appPath);

    const healthResponse = await fetch('/api/health' + suffix, {cache: 'no-store'});
    result.health_status = healthResponse.status;
    const health = await healthResponse.json();
    result.health_ok = healthResponse.status === 200 && health.ok === true && health.database === true;
  } catch (error) {
    result.error = String(error && (error.stack || error.message) || error);
  }
  return result;
})()
"""
    expression = expression.replace("__META__", json.dumps(meta, ensure_ascii=False))
    expression = expression.replace("__DIGEST__", json.dumps(app_digest))
    return evaluate_js(devtools, expression) or {}


def verify_browser_release(base_url, meta, app_digest):
    edge = find_edge()
    if not edge:
        return False, "找不到 Microsoft Edge"
    base = base_url.rstrip("/") + "/"
    profile_root = tempfile.mkdtemp(prefix="ky-deploy-edge-")
    profile = str(Path(profile_root) / "profile")
    process = None
    devtools = None
    try:
        process = subprocess.Popen(
            [
                edge, "--headless=new", "--disable-gpu", "--no-first-run",
                "--no-default-browser-check", "--disable-features=Translate",
                "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0",
                "--remote-allow-origins=*", "--user-data-dir=" + profile, base,
            ],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        port = wait_devtools_port(profile, process)
        target = wait_page_target(port, base)
        devtools = DevToolsSocket(target["webSocketDebuggerUrl"])
        state, detail = wait_page_state(devtools, meta["app_asset"])
        if not state:
            return False, detail

        worker = evaluate_js(devtools, service_worker_expression()) or {}
        if worker.get("controlled") is not True:
            devtools.call("Page.reload", {"ignoreCache": True})
            state, detail = wait_page_state(devtools, meta["app_asset"])
            if not state:
                return False, "SW 接管刷新后页面验收失败：" + detail
            worker = evaluate_js(devtools, service_worker_expression()) or {}

        inspected = inspect_browser_release(devtools, meta, app_digest)
        checks = {
            "build-meta": inspected.get("meta_match") is True,
            "主程序 HTTP": inspected.get("app_status") == 200,
            "主程序内容": inspected.get("app_digest_match") is True,
            "页面 script": inspected.get("app_script") is True,
            "页面资源": inspected.get("app_resource") is True,
            "SW active": inspected.get("sw_active") is True,
            "SW 接管": inspected.get("sw_controlled") is True and worker.get("controlled") is True,
            "SW controller": inspected.get("sw_controller_ok") is True,
            "SW 缓存": inspected.get("cache_has_app") is True,
            "browser health": inspected.get("health_ok") is True,
        }
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            detail = "、".join(failed)
            if inspected.get("error"):
                detail += "；" + str(inspected["error"])[:240]
            return False, detail
        return True, "ok"
    except Exception as exc:
        return False, str(exc)
    finally:
        if devtools is not None:
            devtools.close()
        stop_process(process)
        shutil.rmtree(profile_root, ignore_errors=True)


def verify_health(base_url, attempts=5):
    url = base_url.rstrip("/") + "/api/health?deploy_check=%d" % time.time_ns()
    last = "没有收到响应"
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"user-agent": "ky-deploy-check/1"})
            with urllib.request.urlopen(req, timeout=15) as response:
                body = response.read(4096).decode("utf-8", "replace")
                data = json.loads(body)
                if response.status == 200 and data.get("ok") is True and data.get("database") is True:
                    return True, "ok"
                last = "HTTP %s payload=%s" % (response.status, body[:160])
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            last = str(exc)
        if attempt + 1 < attempts:
            time.sleep(2)
    return False, last


def verify_target(base_url, meta, app_bytes, app_digest):
    last = "没有收到响应"
    for attempt in range(6):
        ok, detail = verify_release(base_url, meta, app_bytes, app_digest)
        if ok:
            last = ""
            break
        last = detail
        if attempt < 5:
            time.sleep(3)
    if last:
        return False, "构建校验失败：" + last

    browser_detail = ""
    for attempt in range(3):
        ok, detail = verify_browser_release(base_url, meta, app_digest)
        if ok:
            browser_detail = ""
            break
        browser_detail = detail
        if attempt < 2:
            time.sleep(4)
    if browser_detail:
        return False, "全新 Edge 验收失败：" + browser_detail

    ok, detail = verify_health(base_url)
    if not ok:
        return False, "健康检查失败：" + detail
    return True, "ok"


def print_failed_deploy_output(tail):
    for line in tail.splitlines()[-12:]:
        safe = re.sub(
            r"Deployment complete|Success(?:ful(?:ly)?)?|成功|✅|✔|✓",
            "[未确认]", line, flags=re.IGNORECASE,
        )
        if safe.strip():
            print("  " + safe.strip())


def main():
    skip_test = "--skip-test" in sys.argv
    allow_migrations = "--allow-pending-migrations" in sys.argv
    allow_dirty = "--allow-dirty-release" in sys.argv
    allow_recent = "--allow-recent-release" in sys.argv
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    lock_fd = None
    try:
        lock_fd = acquire_lock()

        changes = worktree_changes()
        if changes and not allow_dirty:
            print("工作区存在未提交改动，默认拒绝发布：")
            for line in changes[:20]:
                print("  " + line)
            if len(changes) > 20:
                print("  ... 另有 %d 项" % (len(changes) - 20))
            print("确认这些改动属于本次发布后，追加 --allow-dirty-release。")
            return 2
        if changes:
            print("工作区不干净；已按 --allow-dirty-release 继续。")

        recent = recent_release_activity()
        if recent and not allow_recent:
            print("最近 10 分钟存在提交或发布，默认拒绝部署：")
            for item in recent:
                print("  - " + item)
            print("确认没有其他会话在发布后，追加 --allow-recent-release。")
            return 2
        if recent:
            print("最近 10 分钟存在发布活动；已按 --allow-recent-release 继续。")

        migrations = pending_migrations()
        if migrations and not allow_migrations:
            print("检测到数据库迁移文件，未确认远端已执行，拒绝部署：")
            for path in migrations:
                print("  - " + str(path.relative_to(ROOT)))
            print("确认已执行后追加 --allow-pending-migrations。")
            return 2

        print("[1/5] 构建")
        r = run([sys.executable, os.path.join("scripts", "make_html.py")])
        if r.returncode != 0:
            print("构建失败")
            return 1
        try:
            meta, app_bytes, app_digest = load_release_artifact()
        except RuntimeError as exc:
            print("构建产物校验失败：" + str(exc))
            return 1

        if not skip_test:
            print("[2/5] 回归测试")
            r = run([sys.executable, os.path.join("scripts", "tools", "run_tests.py")])
            if r.returncode != 0:
                print("测试未通过，已中止部署")
                return 1
        else:
            print("[2/5] 跳过测试（仅允许紧急发布）")

        print("[3/5] 离线实测")
        r = run([sys.executable, os.path.join("scripts", "tools", "offline_check.py"), "--json"])
        if r.returncode != 0:
            print("离线实测失败，已中止部署")
            return 1

        print("[4/5] 部署到 Cloudflare Pages")
        ps = (
            'if (-not $env:NO_PROXY) { $env:NO_PROXY="localhost,127.0.0.1,::1" };'
            'npx --yes wrangler@4.152.0 pages deploy deploy '
            '--project-name kaoyan2-words --branch main --commit-dirty=true'
        )
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=600, env=cf_env(),
            )
        except subprocess.TimeoutExpired:
            print("部署命令超时，不能确认线上版本")
            return 1
        tail = (r.stdout or "") + "\n" + (r.stderr or "")
        if r.returncode != 0:
            print("部署命令失败，返回码 %s" % r.returncode)
            print_failed_deploy_output(tail)
            return 1
        if not (re.search(r"Deployment complete", tail, re.I) or re.search(r"\bSuccess\b", tail, re.I)):
            print("部署返回码为 0，但输出中没有 Cloudflare 完成标记；不能确认已上线")
            print_failed_deploy_output(tail)
            return 1
        deployment_url = output_value(tail, r"(https://[0-9a-f]{8,}[-.]" + re.escape(PROJECT) + r"\.pages\.dev)")
        deployment_id = output_value(tail, r"(?:Deployment ID|deployment id)\s*[:：]?\s*([0-9a-f-]{8,})")
        if not deployment_url:
            deployment_url = (re.findall(r"https://[^\s]+\.pages\.dev", tail) or [""])[-1]
        if not deployment_url:
            print("部署输出中没有 deployment URL，拒绝通过")
            return 1
        deployment_url = deployment_url.rstrip("/.,;)]}")
        parsed = urllib.parse.urlsplit(deployment_url)
        if parsed.scheme != "https" or not parsed.netloc:
            print("deployment URL 无效：" + deployment_url)
            return 1
        deployment_base = "https://" + parsed.netloc
        public_base = PUBLIC_URL.rstrip("/")

        print("[5/5] 双域名线上验收（HTTP + 全新 Edge profile）")
        for label, base_url in (("deployment URL", deployment_base), ("PUBLIC_URL", public_base)):
            print("  验证 %s：%s" % (label, base_url))
            ok, detail = verify_target(base_url, meta, app_bytes, app_digest)
            if not ok:
                print("%s 验收失败：%s" % (label, detail))
                return 1

        try:
            record_release(meta, deployment_id, deployment_base)
        except OSError as exc:
            print("线上验收通过，但无法写入本地发布互斥标记：" + str(exc))
            return 1
        print("deployment_id=%s" % (deployment_id or "unknown"))
        print("deployment_url=%s" % deployment_base)
        print("public_url=%s" % public_base)
        print("verified=deployment_url,public_url")
        print("health=ok")
        print("release=ok")
        return 0
    except Exception as exc:
        print("发布中止：" + str(exc))
        return 1
    finally:
        if lock_fd is not None:
            release_lock(lock_fd)


if __name__ == "__main__":
    sys.exit(main())
