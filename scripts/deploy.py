# -*- coding: utf-8 -*-
"""构建、门禁测试并部署到 Cloudflare Pages。

用法：
    python scripts/deploy.py
    python scripts/deploy.py --skip-test
    python scripts/deploy.py --allow-pending-migrations
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT = "kaoyan2-words"
PUBLIC_URL = "https://kaoyan2-words.pages.dev"
LOCK = ROOT / "deploy.publish.lock"
LOCK_STALE_SECONDS = 30 * 60


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


def pending_migrations():
    folder = ROOT / "backend" / "migrations"
    return sorted(folder.glob("*.sql")) if folder.is_dir() else []


def output_value(text, pattern):
    match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip() if match else ""


def verify_health(base_url, attempts=5):
    url = base_url.rstrip("/") + "/api/health"
    last = "没有收到响应"
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"user-agent": "ky-deploy-check/1"})
            with urllib.request.urlopen(req, timeout=15) as response:
                body = response.read(4096).decode("utf-8", "replace")
                data = json.loads(body)
                if response.status == 200 and data.get("ok") is True:
                    return True, "ok"
                last = "HTTP %s payload=%s" % (response.status, body[:160])
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            last = str(exc)
        if attempt + 1 < attempts:
            time.sleep(2)
    return False, last


def main():
    skip_test = "--skip-test" in sys.argv
    allow_migrations = "--allow-pending-migrations" in sys.argv
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    lock_fd = None
    try:
        lock_fd = acquire_lock()
        migrations = pending_migrations()
        if migrations and not allow_migrations:
            print("检测到数据库迁移文件，未确认远端已执行，拒绝部署：")
            for path in migrations:
                print("  - " + str(path.relative_to(ROOT)))
            print("确认已执行后追加 --allow-pending-migrations。")
            return 2

        print("[1/4] 构建")
        r = run([sys.executable, os.path.join("scripts", "make_html.py")])
        if r.returncode != 0:
            print("构建失败")
            return 1

        if not skip_test:
            print("[2/4] 回归测试")
            r = run([sys.executable, os.path.join("scripts", "tools", "run_tests.py")])
            if r.returncode != 0:
                print("测试未通过，已中止部署")
                return 1
        else:
            print("[2/4] 跳过测试（仅允许紧急发布）")

        print("[3/4] 部署到 Cloudflare Pages")
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
        for line in tail.splitlines()[-12:]:
            print("  " + line.strip())
        if r.returncode != 0:
            print("部署命令失败，返回码 %s" % r.returncode)
            return 1
        if not (re.search(r"Deployment complete", tail, re.I) or re.search(r"\bSuccess\b", tail, re.I)):
            print("部署返回码为 0，但输出中没有成功标记；不能声称已上线")
            return 1
        deployment_url = output_value(tail, r"(https://[0-9a-f]{8,}[-.]" + re.escape(PROJECT) + r"\.pages\.dev)")
        deployment_id = output_value(tail, r"(?:Deployment ID|deployment id)\s*[:：]?\s*([0-9a-f-]{8,})")
        if not deployment_url:
            deployment_url = (re.findall(r"https://[^\s]+\.pages\.dev", tail) or [""])[-1]
        if not deployment_url:
            print("部署输出中没有 deployment URL，拒绝通过")
            return 1

        print("[4/4] 线上健康检查")
        ok, detail = verify_health("https://" + deployment_url.split("://", 1)[-1])
        if not ok:
            print("deployment URL 健康检查失败：" + detail)
            return 1
        ok, detail = verify_health(PUBLIC_URL)
        if not ok:
            print("正式域名健康检查失败：" + detail)
            return 1
        print("deployment_id=%s" % (deployment_id or "unknown"))
        print("deployment_url=%s" % deployment_url)
        print("health=ok")
        return 0
    except RuntimeError as exc:
        print(str(exc))
        return 1
    finally:
        if lock_fd is not None:
            release_lock(lock_fd)


if __name__ == "__main__":
    sys.exit(main())