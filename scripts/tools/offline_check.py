# -*- coding: utf-8 -*-
"""离线实测：本地起 HTTP 服务 → 让 Service Worker 装好 → 关掉服务 → 重开页面看还能不能用。

用法：python scripts/tools/offline_check.py [--json]
"""
from __future__ import annotations

import functools
import http.server
import io
import json
import os
import re
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEPLOY = os.path.join(ROOT, "deploy")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def start_server():
    handler = functools.partial(Quiet, directory=DEPLOY)
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, port


def run_edge(url, profile, budget=8000):
    r = subprocess.run(
        [EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
         "--disable-features=Translate",
         "--user-data-dir=" + profile,
         "--virtual-time-budget=%d" % budget, "--dump-dom", url],
        capture_output=True, timeout=180,
    )
    return r.stdout.decode("utf-8", "replace")


def has_card(dom):
    """页面真的渲染出了词卡（不是浏览器错误页、也不是骨架）。"""
    m = re.search(r'<div[^>]*id="word"[^>]*>([^<]*)</div>', dom)
    return bool(m and m.group(1).strip())


def word_text(dom):
    m = re.search(r'<div[^>]*id="word"[^>]*>([^<]*)</div>', dom)
    return m.group(1).strip() if m else ""


def check():
    if not os.path.isdir(DEPLOY):
        return {"ok": False, "reason": "deploy/ 不存在，先跑 make_html.py"}
    tmp = tempfile.mkdtemp()
    profile = os.path.join(tmp, "profile")
    result = {"ok": False, "steps": []}
    httpd, port = start_server()
    url = "http://127.0.0.1:%d/" % port
    try:
        # 第一遍：联网，让 SW 完成 install + 预缓存
        online_dom = run_edge(url, profile, budget=10000)
        result["steps"].append({"step": "首次联网加载", "card": has_card(online_dom)})
        if not has_card(online_dom):
            result["reason"] = "联网首次加载就没渲染出词卡"
            return result

        # 关掉服务：之后所有网络请求都会失败，跟真实断网等价
        httpd.shutdown()
        httpd.server_close()
        result["steps"].append({"step": "关闭本地服务（等价断网）", "card": None})

        # 第二遍：同一浏览器 profile，缓存与 SW 都在，看还能不能打开
        offline_dom = run_edge(url, profile, budget=10000)
        offline_card = has_card(offline_dom)
        offline_word = word_text(offline_dom)
        online_word = word_text(online_dom)
        result["steps"].append({"step": "断网后重开", "card": offline_card, "word": offline_word})
        result["online_word"] = online_word
        result["offline_word"] = offline_word
        result["ok"] = offline_card and offline_word == online_word
        if not offline_card:
            result["reason"] = "断网后页面打不开（Service Worker 没兜住）"
        elif offline_word != online_word:
            result["reason"] = "断网后能打开，但词卡内容不一致"
        return result
    finally:
        try:
            httpd.shutdown()
            httpd.server_close()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    data = check()
    if "--json" in sys.argv:
        print(json.dumps(data, ensure_ascii=False))
    else:
        print("离线实测")
        for s in data["steps"]:
            print("  " + " | ".join("%s=%s" % (k, v) for k, v in s.items() if v is not None))
        print("  结果：" + ("通过" if data["ok"] else "失败 — " + data.get("reason", "")))
    return 0 if data.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
