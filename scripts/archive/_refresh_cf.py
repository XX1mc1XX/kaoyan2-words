# -*- coding: utf-8 -*-
"""用 refresh_token 手动刷新 Cloudflare OAuth token（走本地代理）。"""
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

CONF = os.path.join(os.environ["APPDATA"], "xdg.config", ".wrangler", "config", "default.toml")
CLIENT_ID = "54d11594-84e4-41aa-b438-e81b8fa78ee7"
PROXY = "http://127.0.0.1:7897"

text = io.open(CONF, encoding="utf-8", errors="replace").read()


def grab(key):
    m = re.search(rf'^{key}\s*=\s*"([^"]+)"', text, re.M)
    return m.group(1) if m else None


refresh = grab("refresh_token")
if not refresh:
    sys.exit("no refresh_token")

body = urllib.parse.urlencode({
    "grant_type": "refresh_token",
    "refresh_token": refresh,
    "client_id": CLIENT_ID,
}).encode()

req = urllib.request.Request(
    "https://dash.cloudflare.com/oauth2/token",
    data=body,
    headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "wrangler"},
)
opener = urllib.request.build_opener(urllib.request.ProxyHandler({"https": PROXY, "http": PROXY}))
try:
    resp = json.load(opener.open(req, timeout=45))
except urllib.error.HTTPError as e:
    detail = e.read().decode("utf-8", "replace")[:400]
    print(f"REFRESH FAILED: HTTP {e.code} — {detail}")
    sys.exit(1)
except Exception as e:
    print("REFRESH FAILED:", type(e).__name__, str(e)[:200])
    sys.exit(1)

new_at = resp.get("access_token")
new_rt = resp.get("refresh_token") or refresh
expires_in = int(resp.get("expires_in") or 3600)
if not new_at:
    print("no access_token in response:", list(resp.keys()))
    sys.exit(1)

exp = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
text = re.sub(r'^oauth_token\s*=\s*"[^"]*"', f'oauth_token = "{new_at}"', text, flags=re.M)
text = re.sub(r'^refresh_token\s*=\s*"[^"]*"', f'refresh_token = "{new_rt}"', text, flags=re.M)
text = re.sub(r'^expiration_time\s*=\s*"[^"]*"', f'expiration_time = "{exp}"', text, flags=re.M)
io.open(CONF, "w", encoding="utf-8", newline="\n").write(text)

print(f"OK 刷新成功，新 token {len(new_at)} 字符，有效期至 {exp}")
