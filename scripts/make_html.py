# -*- coding: utf-8 -*-
"""Embed the generated word list into the single-file mobile web app."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
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
    """只打包前端真正读取的字段，并生成每个词唯一的展示权重。"""
    total = len(source)
    return [
        {
            "id": r["id"],
            "word": r["word"],
            "family": r.get("family", ""),
            "meaning": r["meaning"],
            "forms": r.get("forms", []),
            "priority": r.get("priority", ""),
            # 长按面板要显示真题出现次数，用来判断这个词值不值得多花时间
            "freq": r.get("freq", 0),
            "en1_freq": r.get("en1_freq", 0),
            # 词表已按综合优先级排序；用名次映射到 0.01–100.00，
            # 保证同一词库内每个词的展示权重都不同。
            "weight": round((total - index + 1) * 100 / total, 2),
        }
        for index, r in enumerate(source, 1)
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


def render_html(deck_values, meta_value, detail_value):
    return (
        template.replace("__DATA__", json_block(deck_values["words"]))
        .replace("__DERIVATIVES__", json_block(deck_values["derivatives"]))
        .replace("__BASIC__", json_block(deck_values["basic"]))
        .replace("__INSURANCE__", json_block(deck_values["insurance"]))
        .replace("__META__", json_block(meta_value))
        .replace("__DETAIL__", json_block(detail_value))
    )


EXAM_TAGS = ("zk", "gk", "cet4", "cet6", "ky", "toefl", "ielts", "gre")

# ECDICT exchange 字段的形态码 → 中文标注
FORM_MARKS = {
    "p": "过去式", "d": "过去分词", "i": "现在分词",
    "s": "复数", "3": "第三人称单数", "r": "比较级", "t": "最高级",
}


def short_meaning(translation):
    """取第一个义项里最靠前的一小段，给词形做简短注释用。"""
    for line in (translation or "").split("\n"):
        line = line.strip()
        if not line or line.startswith("["):
            continue
        line = re.sub(r"^[a-z]+\.\s*", "", line)
        return line.split(",")[0].strip()[:14]
    return ""


def build_detail(rows):
    """长按查看用的详情：音标 + 前两个词性组 + 词形释义。

    只取前两组是因为词典里靠后的义项大多是生僻用法，考研不考；
    把整段塞进去反而会把「州 / 大写字母」这类非重点义摆到用户眼前。
    """
    path = DATA / "ecdict.csv"
    if not path.exists():
        return {}

    word_forms = {}
    lookup = set()
    for r in rows:
        word = r["word"]
        forms = [f.lower() for f in (r.get("forms") or []) if f and f.lower() != word]
        word_forms[word] = forms
        lookup.add(word)
        lookup.update(forms)

    ecdict = {}
    with io.open(path, encoding="utf-8", errors="replace", newline="") as f:
        for row in csv.DictReader(f):
            word = (row.get("word") or "").lower()
            if word in lookup and word not in ecdict:
                ecdict[word] = row

    detail = {}
    for word, forms in word_forms.items():
        row = ecdict.get(word)
        if not row:
            continue
        groups = []
        for line in (row.get("translation") or "").split("\n"):
            line = line.strip()
            if not line or line.startswith("["):   # 跳过 [计] [医] 这类领域行
                continue
            groups.append(line[:46] + "…" if len(line) > 46 else line)
        if not groups:
            continue
        item = {"t": "\n".join(groups[:2])}
        phonetic = (row.get("phonetic") or "").strip()
        if phonetic:
            item["p"] = phonetic
        # 考纲标签：ky = 考研大纲词，其余用来判断这个词的通用程度
        tags = [t for t in (row.get("tag") or "").split() if t in EXAM_TAGS]
        if tags:
            item["g"] = tags

        # 词形释义：形态变化只存码（前端映射成中文），真派生词才查自己的释义
        marks = {}
        for part in (row.get("exchange") or "").split("/"):
            if ":" not in part:
                continue
            code, value = part.split(":", 1)
            if code not in FORM_MARKS:
                continue
            for name in value.split("/"):
                key = name.strip().lower()
                if key and key != word:
                    marks.setdefault(key, []).append(code)
        form_info = {}
        for form in forms:
            if form in form_info:
                continue
            if form in marks:
                form_info[form] = "|".join(marks[form])
            else:
                form_info[form] = short_meaning((ecdict.get(form) or {}).get("translation"))
        if form_info:
            item["f"] = form_info

        detail[word] = item
    return detail


detail = build_detail(slim + derivative_slim + basic_slim + insurance_slim)

# 本地单文件版继续内嵌全部词库，双击即可完整离线使用。
standalone_html = render_html(
    {
        "words": slim,
        "derivatives": derivative_slim,
        "basic": basic_slim,
        "insurance": insurance_slim,
    },
    meta,
    detail,
)
OUT.write_text(standalone_html, encoding="utf-8", newline="\n")

# deploy/ 是纯生成目录，先清空，防止旧版页面和 .git 残留被一起上传。
DEPLOY.mkdir(parents=True, exist_ok=True)
for stale in DEPLOY.iterdir():
    if stale.is_dir():
        rmtree_force(stale)
    else:
        os.chmod(stale, stat.S_IWRITE)
        stale.unlink(missing_ok=True)

# 网页版只内嵌首章，其他词库拆成带内容哈希的独立资源：
# 首屏不再下载 3364 个词，同时这些资源仍可长期缓存并供 Service Worker 离线预取。
asset_map = {}
deck_payloads = {
    "words": slim,
    "derivatives": derivative_slim,
    "basic": basic_slim,
    "insurance": insurance_slim,
}
for deck_id, deck_rows in deck_payloads.items():
    payload = json_block(deck_rows)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    rel_path = Path("data") / f"{deck_id}.{digest}.json"
    target = DEPLOY / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload, encoding="utf-8", newline="\n")
    asset_map[deck_id] = "./" + rel_path.as_posix()

# 长按详情单独一片：只有第一次长按时才下载，不占首屏
detail_payload = json_block(detail)
detail_digest = hashlib.sha256(detail_payload.encode("utf-8")).hexdigest()[:12]
detail_rel = Path("data") / f"detail.{detail_digest}.json"
(DEPLOY / detail_rel).write_text(detail_payload, encoding="utf-8", newline="\n")
asset_map["detail"] = "./" + detail_rel.as_posix()

web_meta = dict(meta)
web_meta.update(
    {
        "web": True,
        "deck_sizes": {
            "words": len(slim),
            "derivatives": len(derivative_slim),
            "basic": len(basic_slim),
            "insurance": len(insurance_slim),
        },
        "assets": asset_map,
    }
)
web_html = render_html(
    {
        "words": slim[:200],
        "derivatives": [],
        "basic": [],
        "insurance": [],
    },
    web_meta,
    {},   # 网页版详情走独立分片，按需加载
)

# 主程序拆成带哈希的独立脚本，放入 head 并用 defer 提前并行下载。
# HTML 可以先绘制骨架，脚本和词库分片还能长期缓存。
app_match = re.search(r'<script id="ky-app">(.*?)</script>', web_html, re.S)
if not app_match:
    raise RuntimeError("ky-app script block not found")
app_js = app_match.group(1)
# 网页版主程序用 Terser 压缩；本机没有 npx 时自动回退到未压缩源码，不阻断构建。
if not os.environ.get("KY_NO_MINIFY"):
    npx = shutil.which("npx")
    if npx:
        try:
            minified = subprocess.run(
                [npx, "--yes", "terser", "--compress", "--mangle", "--format", "comments=false"],
                input=app_js.encode("utf-8"), capture_output=True, timeout=90,
            )
            if minified.returncode == 0 and minified.stdout.strip():
                app_js = minified.stdout.decode("utf-8")
        except Exception:
            pass
app_digest = hashlib.sha256(app_js.encode("utf-8")).hexdigest()[:12]
app_asset = f"./app.{app_digest}.js"
(DEPLOY / app_asset[2:]).write_text(app_js, encoding="utf-8", newline="\n")
web_html = web_html[:app_match.start()] + web_html[app_match.end():]
head_start = web_html.find("<head>")
if head_start < 0:
    raise RuntimeError("head tag not found")
head_start += len("<head>")
web_html = (
    web_html[:head_start]
    + f'\n<script defer fetchpriority="high" src="{app_asset}"></script>'
    + web_html[head_start:]
)

# 每次构建都换一个缓存名，保证 Service Worker 能拿到新页面但保留已缓存发音。
# 构建日期不参与哈希，否则每天都会全量重下页面。
build_version = hashlib.sha256(
    re.sub(r'"generated_at":"[^"]*"', "", web_html).encode("utf-8")
).hexdigest()[:12]
# 详情分片不进 SW 预缓存：它只在第一次长按时才用到，不该拖慢首次安装
runtime_assets = [asset_map[k] for k in ("words", "derivatives", "basic", "insurance")] + [app_asset]
sw_js = (
    (SOFT / "sw.template.js").read_text(encoding="utf-8")
    .replace("__BUILD_VERSION__", build_version)
    .replace("__DATA_ASSETS__", json.dumps(runtime_assets, ensure_ascii=False))
)
(SOFT / "sw.js").write_text(sw_js, encoding="utf-8", newline="\n")

(DEPLOY / "index.html").write_text(web_html, encoding="utf-8", newline="\n")
(DEPLOY / "sw.js").write_text(sw_js, encoding="utf-8", newline="\n")
for name in ("manifest.webmanifest", "icon-192.png", "icon-512.png"):
    shutil.copy2(SOFT / name, DEPLOY / name)
shutil.copy2(ROOT / "backend" / "worker.js", DEPLOY / "_worker.js")
(DEPLOY / "_headers").write_text(
    "/index.html\n  Cache-Control: public, max-age=0, must-revalidate\n"
    "/sw.js\n  Cache-Control: no-cache\n"
    "/manifest.webmanifest\n  Cache-Control: public, max-age=3600\n"
    "/data/*\n  Cache-Control: public, max-age=31536000, immutable\n"
    "/app.*.js\n  Cache-Control: public, max-age=31536000, immutable\n",
    encoding="utf-8",
    newline="\n",
)

print(f"output={OUT}")
print(f"deploy={DEPLOY / 'index.html'}")
print(f"words={len(slim)} derivatives={len(derivative_slim)} basic={len(basic_slim)} insurance={len(insurance_slim)}")
print(f"standalone={OUT.stat().st_size / 1024:.0f}KB web={len(web_html.encode('utf-8')) / 1024:.0f}KB")
