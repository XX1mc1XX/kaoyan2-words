# -*- coding: utf-8 -*-
"""Embed the generated word list into the single-file mobile web app."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import stat
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOFT = ROOT / "software"
DEPLOY = ROOT / "deploy"
OUT = SOFT / "考研核心词.html"


def rmtree_force(path):
    """Windows 上 .git 里的只读文件会让 shutil.rmtree 静默失败，先清只读位。"""
    def retry(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)
    shutil.rmtree(path, onexc=retry)

rows = json.loads((DATA / "words.json").read_text(encoding="utf-8"))
derivatives = json.loads((DATA / "derivatives.json").read_text(encoding="utf-8"))
basic = json.loads((DATA / "basic.json").read_text(encoding="utf-8"))
insurance = json.loads((DATA / "insurance.json").read_text(encoding="utf-8"))
freq = json.loads((DATA / "ky2_freq.json").read_text(encoding="utf-8"))
ky1_path = DATA / "ky1_freq.json"
ky1 = json.loads(ky1_path.read_text(encoding="utf-8")) if ky1_path.exists() else {}
summary = json.loads((DATA / "selection_summary.json").read_text(encoding="utf-8"))

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

source_files = []
for exam, folder in (("english_2", "ky2"), ("english_1", "ky1")):
    folder_path = ROOT / "ref" / folder
    if not folder_path.exists():
        continue
    for path in sorted(folder_path.glob("*.pdf")):
        source_files.append({"exam": exam, "name": path.name, "sha256": sha256(path)})

meta = dict(freq.get("meta", {}))
meta.update({
    "generated_at": date.today().isoformat(),
    "selection_total": len(rows),
    "selection_bands": summary.get("bands", {}),
    "exam_weights": summary.get("weights", {"english_2": 1.0, "english_1": 0.35, "english_3": 0.0}),
    "english_1": ky1.get("meta", {}),
    "source_files": source_files,
})
def slim_rows(source):
    """只打包前端真正读取的字段（见 template.html 实际引用）。"""
    return [
        {
            "id": r["id"],
            "word": r["word"],
            "family": r.get("family", ""),
            "meaning": r["meaning"],
            "forms": r.get("forms", []),
            "priority": r.get("priority", ""),
        }
        for r in source
    ]

slim = slim_rows(rows)
derivative_slim = slim_rows(derivatives)
basic_slim = slim_rows(basic)
insurance_slim = slim_rows(insurance)



template = (SOFT / "template.html").read_text(encoding="utf-8")


def json_block(value):
    """嵌进 <script type="application/json"> 的 JSON。

    把 < 转成 \\u003c，可同时挡掉 </script> 提前闭合和 <!-- 进入 script
    double-escaped 状态两种破坏；JSON.parse 会自动还原。
    """
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


html = (
    template.replace("__DATA__", json_block(slim))
    .replace("__DERIVATIVES__", json_block(derivative_slim))
    .replace("__BASIC__", json_block(basic_slim))
    .replace("__INSURANCE__", json_block(insurance_slim))
    .replace("__META__", json_block(meta))
)
OUT.write_text(html, encoding="utf-8", newline="\n")

# 每次构建都换一个缓存名，保证 Service Worker 能拿到新页面但保留已缓存发音。
# 构建日期不参与哈希，否则每天都会全量重下页面。
build_version = hashlib.sha256(
    re.sub(r'"generated_at":"[^"]*"', "", html).encode("utf-8")
).hexdigest()[:12]
sw_js = (SOFT / "sw.template.js").read_text(encoding="utf-8").replace("__BUILD_VERSION__", build_version)
(SOFT / "sw.js").write_text(sw_js, encoding="utf-8", newline="\n")

# 网页版与离线版同步生成，避免手工复制造成版本不一致。
# deploy/ 是纯生成目录，先清空，防止旧版页面和 .git 残留被一起上传。
DEPLOY.mkdir(parents=True, exist_ok=True)
for stale in DEPLOY.iterdir():
    if stale.is_dir():
        rmtree_force(stale)
    else:
        os.chmod(stale, stat.S_IWRITE)
        stale.unlink(missing_ok=True)
(DEPLOY / "index.html").write_text(html, encoding="utf-8", newline="\n")
(DEPLOY / "sw.js").write_text(sw_js, encoding="utf-8", newline="\n")
for name in ("manifest.webmanifest", "icon-192.png", "icon-512.png"):
    shutil.copy2(SOFT / name, DEPLOY / name)
shutil.copy2(ROOT / "backend" / "worker.js", DEPLOY / "_worker.js")
(DEPLOY / "_headers").write_text(
    "/index.html\n  Cache-Control: public, max-age=0, must-revalidate\n"
    "/sw.js\n  Cache-Control: no-cache\n"
    "/manifest.webmanifest\n  Cache-Control: public, max-age=3600\n",
    encoding="utf-8",
    newline="\n",
)

print(f"output={OUT}")
print(f"deploy={DEPLOY / 'index.html'}")
print(f"words={len(slim)} derivatives={len(derivative_slim)} basic={len(basic_slim)} insurance={len(insurance_slim)} size={OUT.stat().st_size / 1024:.0f}KB")
