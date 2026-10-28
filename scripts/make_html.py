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
SHARED = ROOT / "shared"
# 先往临时目录写，构建完再整体替换：边清空边写会让目录短暂处于半成品状态
DEPLOY = ROOT / "deploy.tmp"
DEPLOY_FINAL = ROOT / "deploy"
OUT = SOFT / "考研核心词.html"
MERGE_MARKER = "/*__MERGE__*/"


def inject(source, marker, value):
    """替换占位符。

    用 partition 而不是 str.replace：合并模块的源码里一旦出现 $ 符号，
    str.replace 会把它当成替换模式（$& / $1）静默改写代码。
    """
    head, sep, tail = source.partition(marker)
    if not sep:
        raise RuntimeError("占位符缺失：" + marker)
    return head + value + tail


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
# 合并算法只有一份实现，构建时分别注入前端和 Worker
merge_source = (SHARED / "merge.js").read_text(encoding="utf-8")


def json_block(value):
    """嵌进 <script type="application/json"> 的 JSON。

    把 < 转成 \\u003c，可同时挡掉 </script> 提前闭合和 <!-- 进入 script
    double-escaped 状态两种破坏；JSON.parse 会自动还原。
    """
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def render_html(deck_values, meta_value, detail_value):
    html = template
    for marker, value in (
        ("__DATA__", json_block(deck_values["words"])),
        ("__DERIVATIVES__", json_block(deck_values["derivatives"])),
        ("__BASIC__", json_block(deck_values["basic"])),
        ("__INSURANCE__", json_block(deck_values["insurance"])),
        ("__META__", json_block(meta_value)),
        ("__DETAIL__", json_block(detail_value)),
        (MERGE_MARKER, merge_source),
    ):
        html = inject(html, marker, value)
    return html


EXAM_TAGS = ("zk", "gk", "cet4", "cet6", "ky", "toefl", "ielts", "gre")

# ECDICT exchange 字段的形态码 → 中文标注
FORM_MARKS = {
    "p": "过去式", "d": "过去分词", "i": "现在分词",
    "s": "复数", "3": "第三人称单数", "r": "比较级", "t": "最高级",
}


def normalize_translation(text):
    """ECDICT 的换行是字面的「反斜杠 + n」两个字符，不转成真换行，面板会原样显示出来。"""
    return (text or "").replace("\\n", "\n")


def is_verb_word(text):
    """判断这个词是否真的当动词用。

    名词/形容词的 exchange 里也常带着 p/d/i/3（词典收了罕见动词义），
    像 companion → companioned、stable → stabled，考研永远不会考，显示出来只是噪音。
    """
    return bool(re.search(r"(?:^|\n)\s*(?:v|vt|vi)\.", text))


# 派生词常见后缀 → 该派生词自己的词性；查释义时优先取同词性的义项行
SUFFIX_POS = (
    ("ity", "n"), ("ness", "n"), ("tion", "n"), ("sion", "n"), ("ment", "n"),
    ("ance", "n"), ("ence", "n"), ("ship", "n"), ("hood", "n"), ("ism", "n"),
    ("ist", "n"), ("er", "n"), ("or", "n"),
    ("able", "a"), ("ible", "a"), ("ive", "a"), ("ful", "a"), ("ous", "a"),
    ("less", "a"), ("al", "a"), ("ic", "a"), ("ary", "a"),
    ("ly", "ad"),
    ("ise", "v"), ("ize", "v"), ("ify", "v"),
)


def pos_for_form(form):
    for suffix, pos in SUFFIX_POS:
        # 留够词干：stable 不能被当成 -able 的派生词
        if form.endswith(suffix) and len(form) > len(suffix) + 3:
            return pos
    return ""


def short_meaning(translation, prefer_pos=""):
    """给词形做简短注释：优先取与派生词词性一致的那一行，再取最靠前的两个义项。

    不这么做会闹笑话：stable 的第一行是「n. 马房, 牛棚」，
    但 stability（名词）真正对应的是「a. 稳定的」那一行。
    """
    lines = []
    for line in normalize_translation(translation).split("\n"):
        line = line.strip()
        if not line or line.startswith("["):
            continue
        lines.append(line)
    if prefer_pos:
        matched = [line for line in lines if re.match(r"^%s\." % prefer_pos, line)]
        if matched:
            lines = matched
        else:
            lines.sort(key=len, reverse=True)
    else:
        # 词性看不出来时取最长的一行：短行往往是「马房, 牛棚」这种冷门义
        lines.sort(key=len, reverse=True)
    items = []
    for line in lines:
        body = re.sub(r"^[a-z]+\.\s*", "", line)
        for part in re.split(r"[,，、;；]", body):
            part = part.strip()
            if part and part not in items:
                items.append(part)
            if len(items) >= 2:
                break
        if len(items) >= 2:
            break
    return "·".join(items)[:16]


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
        translation = normalize_translation(row.get("translation"))
        groups = []
        for line in translation.split("\n"):
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
        verb = is_verb_word(translation)
        marks = {}
        for part in (row.get("exchange") or "").split("/"):
            if ":" not in part:
                continue
            code, value = part.split(":", 1)
            if code not in FORM_MARKS:
                continue
            # 原词基本不当动词用时，过去式 / 分词 / 三单对考研没意义
            if code in ("p", "d", "i", "3") and not verb:
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
                form_info[form] = short_meaning(
                    (ecdict.get(form) or {}).get("translation"), pos_for_form(form))
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

# 临时生成目录：上一次构建失败可能留下残留，先清干净再写。
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

# 长按详情按首字母拆片：一次长按只下载那个字母的详情（十几 KB），
# 而不是把 400KB 全表拉下来
detail_shards = {}
for word_key, word_info in detail.items():
    letter = word_key[0].lower() if word_key[:1].isalpha() else "_"
    detail_shards.setdefault(letter, {})[word_key] = word_info
detail_assets = {}
for letter, items in sorted(detail_shards.items()):
    payload = json_block(items)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    rel_path = Path("data") / f"detail-{letter}.{digest}.json"
    (DEPLOY / rel_path).write_text(payload, encoding="utf-8", newline="\n")
    detail_assets[letter] = "./" + rel_path.as_posix()
asset_map["details"] = detail_assets

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
        # 首屏只留一章的零头：整本章节靠分片按需加载，内嵌太多会把 HTML 撑大，
        # 而 Service Worker 又预缓存了完整词库，内容重复没有意义。
        "words": slim[:40],
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
# 网页版主程序用 Terser 压缩。压缩失败必须让构建失败：
# 静默回退到未压缩源码会让产物体积翻倍、且没人发现，构建也不可复现。
# 确实要跳过压缩时显式设置 KY_NO_MINIFY=1。
if os.environ.get("KY_NO_MINIFY"):
    print("minify=skipped")
else:
    npx = shutil.which("npx")
    if not npx:
        raise RuntimeError("找不到 npx，无法压缩主程序：装好 Node，或显式 KY_NO_MINIFY=1 跳过压缩")
    try:
        minified = subprocess.run(
            [npx, "--yes", "terser", "--compress", "--mangle", "--format", "comments=false"],
            input=app_js.encode("utf-8"), capture_output=True, timeout=180,
        )
    except Exception as exc:
        raise RuntimeError("terser 调用失败：%s" % exc) from exc
    if minified.returncode != 0 or not minified.stdout.strip():
        raise RuntimeError("terser 压缩失败：%s" % minified.stderr.decode("utf-8", "replace")[:300])
    app_js = minified.stdout.decode("utf-8")
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
# Service Worker 自身和合并模块也必须进哈希：只改它们时缓存名不变，
# 已经打开的页面就永远不会更新。
sw_template = (SOFT / "sw.template.js").read_text(encoding="utf-8")
build_version = hashlib.sha256(
    "\n".join((
        re.sub(r'"generated_at":"[^"]*"', "", web_html),
        sw_template,
        merge_source,
    )).encode("utf-8")
).hexdigest()[:12]
# 详情分片不进 SW 预缓存：它只在第一次长按时才用到，不该拖慢首次安装
runtime_assets = [asset_map[k] for k in ("words", "derivatives", "basic", "insurance")] + [app_asset]
sw_js = (
    sw_template
    .replace("__BUILD_VERSION__", build_version)
    .replace("__DATA_ASSETS__", json.dumps(runtime_assets, ensure_ascii=False))
)
(SOFT / "sw.js").write_text(sw_js, encoding="utf-8", newline="\n")

(DEPLOY / "index.html").write_text(web_html, encoding="utf-8", newline="\n")
(DEPLOY / "sw.js").write_text(sw_js, encoding="utf-8", newline="\n")
for name in ("manifest.webmanifest", "icon-192.png", "icon-512.png"):
    shutil.copy2(SOFT / name, DEPLOY / name)
# Worker 是单文件部署（Pages 高级模式下 _worker.js 不能带外部 import），
# 合并模块在构建时注入进来，源码里只留一个占位符。
worker_source = inject(
    (ROOT / "backend" / "worker.js").read_text(encoding="utf-8"), MERGE_MARKER, merge_source)
(DEPLOY / "_worker.js").write_text(worker_source, encoding="utf-8", newline="\n")
(DEPLOY / "_headers").write_text(
    "/*\n"
    "  X-Content-Type-Options: nosniff\n"
    "  Referrer-Policy: same-origin\n"
    "  Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    # media-src 必须放行有道：前端会直接把 <audio> 指向 dict.youdao.com 抢先发声，
    # 拦掉不会报错，只会静默退化成系统 TTS。
    "img-src 'self' data:; media-src 'self' blob: data: https://dict.youdao.com; "
    "connect-src 'self'; manifest-src 'self'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'\n"
    "/index.html\n  Cache-Control: public, max-age=0, must-revalidate\n"
    "/sw.js\n  Cache-Control: no-cache\n"
    "/manifest.webmanifest\n  Cache-Control: public, max-age=3600\n"
    "/data/*\n  Cache-Control: public, max-age=31536000, immutable\n"
    "/app.*.js\n  Cache-Control: public, max-age=31536000, immutable\n",
    encoding="utf-8",
    newline="\n",
)

# 临时目录写完再整体替换 deploy/：一边清空一边写会让目录短暂处于半成品状态，
# 已经打开的旧页面按需去拉旧哈希分片就会 404。
STALE = ROOT / "deploy.old"
if STALE.exists():
    rmtree_force(STALE)
if DEPLOY_FINAL.exists():
    os.replace(DEPLOY_FINAL, STALE)
os.replace(DEPLOY, DEPLOY_FINAL)
if STALE.exists():
    rmtree_force(STALE)

print(f"output={OUT}")
print(f"deploy={DEPLOY_FINAL / 'index.html'}")
print(f"words={len(slim)} derivatives={len(derivative_slim)} basic={len(basic_slim)} insurance={len(insurance_slim)}")
print(f"app={len(app_js.encode('utf-8')) / 1024:.0f}KB standalone={OUT.stat().st_size / 1024:.0f}KB "
      f"web={len(web_html.encode('utf-8')) / 1024:.0f}KB build={build_version}")
