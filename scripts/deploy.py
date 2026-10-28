# -*- coding: utf-8 -*-
"""一键构建 + 测试 + 部署。测试不过就不部署。

用法：
    python scripts/deploy.py            # 完整流程
    python scripts/deploy.py --skip-test # 紧急跳过测试
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT = "kaoyan2-words"
PROXY = "http://127.0.0.1:7897"


def cf_env():
    """优先用 .wrangler/.cf_token（已被 git 忽略）里的 API Token。

    OAuth 登录会过期，而且回调要占 localhost:8976，机器上被占用时根本登录不了；
    API Token 没有这两个问题。
    """
    env = dict(os.environ)
    for key, name in (("CLOUDFLARE_API_TOKEN", ".cf_token"), ("CLOUDFLARE_ACCOUNT_ID", ".cf_account")):
        path = os.path.join(ROOT, ".wrangler", name)
        try:
            if os.path.exists(path):
                env[key] = open(path, encoding="utf-8").read().strip()
        except Exception:
            pass
    return env


def run(cmd, **kw):
    return subprocess.run(cmd, cwd=ROOT, **kw)


def main():
    skip_test = "--skip-test" in sys.argv
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    print("[1/3] 构建")
    r = run([sys.executable, os.path.join("scripts", "make_html.py")])
    if r.returncode != 0:
        print("构建失败")
        return 1

    if not skip_test:
        print("[2/3] 回归测试")
        r = run([sys.executable, os.path.join("scripts", "tools", "run_tests.py")])
        if r.returncode != 0:
            print("测试未通过，已中止部署")
            return 1
    else:
        print("[2/3] 跳过测试")

    print("[3/3] 部署到 Cloudflare Pages")
    # 用 PowerShell 执行，避开 python subprocess 调 npx 的兼容问题
    ps = (
        '$env:HTTP_PROXY="http://127.0.0.1:7897";'
        '$env:HTTPS_PROXY="http://127.0.0.1:7897";'
        '$env:NO_PROXY="localhost,127.0.0.1,::1";'
        'npx --yes wrangler@4.152.0 pages deploy deploy '
        '--project-name kaoyan2-words --branch main --commit-dirty=true'
    )
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=600, env=cf_env(),
    )
    tail = (r.stdout or "") + (r.stderr or "")
    ok = "Deployment complete" in tail or "Success" in tail
    for line in tail.splitlines()[-5:]:
        print("  " + line.strip())
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
