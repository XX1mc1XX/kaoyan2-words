# -*- coding: utf-8 -*-
"""下载考研英语二真题 PDF 与红宝书词表 JSON。"""
import json
import os
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "ref", "ky2")
UA = {"User-Agent": "Mozilla/5.0"}


def default_branch(repo):
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}", headers=UA)
    return json.load(urllib.request.urlopen(req, timeout=30))["default_branch"]


def download(url, dest, tries=6):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest) and os.path.getsize(dest) > 1024:
        return f"skip {os.path.basename(dest)} {os.path.getsize(dest) // 1024}KB"
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
            return f"ok   {os.path.basename(dest)} {os.path.getsize(dest) // 1024}KB"
        except Exception as e:
            last = e
            time.sleep(2 + i * 2)
    raise last


def main():
    jobs = []
    repo2 = "Gatsby666-jay/Kaoyan-English-2c-2"
    b2 = default_branch(repo2)
    base2 = f"https://raw.githubusercontent.com/{repo2}/{b2}/"
    for name in [
        "2010-2021年考研英语二真题合集.pdf",
        "2022年考研英语二真题.pdf",
        "2023年考研英语二真题.pdf",
        "2024年考研英语二真题.pdf",
    ]:
        path = "2010-2024考研英语真题+解析/2010-2024考研英语真题/" + name
        jobs.append((base2 + urllib.parse.quote(path), os.path.join(OUT, name)))

    repo_r = "3056810551/2027-kaoyan-english-redbook-json"
    br = default_branch(repo_r)
    jobs.append((
        f"https://raw.githubusercontent.com/{repo_r}/{br}/words.json",
        os.path.join(ROOT, "ref", "redbook_words.json"),
    ))

    for url, dest in jobs:
        try:
            print(download(url, dest))
        except Exception as e:
            print("ERR", os.path.basename(dest), type(e).__name__, e)


if __name__ == "__main__":
    main()
