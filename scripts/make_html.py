# -*- coding: utf-8 -*-
"""Embed the generated word list into the single-file mobile web app."""
from __future__ import annotations

import atexit
import csv
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from frontend_bundle import assemble_template

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOFT = ROOT / "software"
SHARED = ROOT / "shared"
DEPLOY_TMP_ROOT = ROOT / "deploy.tmp"
DEPLOY = None
DEPLOY_FINAL = ROOT / "deploy"
OUT = SOFT / "考研核心词.html"
MERGE_MARKER = "/*__MERGE__*/"
LOCK = ROOT / "deploy.lock"
LOCK_FD = None
LOCK_TOKEN = None
_LOCK_ATEXIT_REGISTERED = False
TERSER_VERSION = "5.51.2"


# 单一输入清单：required=False 的缺失输入是明确允许的；source_digest=True
# 的文件参与来源指纹（存在时才入账，保持既有 source_digest 协议不变）。
INPUT_MANIFEST = (
    ("template", "software/template.html", True, True, "file", "网页模板"),
    ("sw_template", "software/sw.template.js", True, True, "file", "Service Worker 模板"),
    ("worker_template", "backend/worker.js", True, True, "file", "Worker 模板"),
    ("merge_source", "shared/merge.js", True, True, "file", "前后端共享合并算法"),
    ("make_html", "scripts/make_html.py", True, True, "file", "构建脚本自身"),
    ("frontend_src", "software/src", True, True, "dir", "有序前端源片段、样式和 shell"),
    ("words", "data/words.json", True, True, "file", "核心词库"),
    ("words_order", "data/words_order.json", False, True, "file", "上游排序参考，仅用于来源指纹"),
    ("derivatives", "data/derivatives.json", True, True, "file", "派生词库"),
    ("basic", "data/basic.json", True, True, "file", "基础词库"),
    ("insurance", "data/insurance.json", True, True, "file", "保险词库"),
    ("ky2_freq", "data/ky2_freq.json", True, True, "file", "英语二词频"),
    ("selection_summary", "data/selection_summary.json", True, True, "file", "选词摘要"),
    ("ky1_freq", "data/ky1_freq.json", False, True, "file", "英语一词频；缺失时按空元数据处理"),
    ("meanings_curated", "data/meanings_curated.json", False, True, "file", "上游释义来源，仅用于来源指纹"),
    ("meanings_final", "data/meanings_final.json", False, True, "file", "上游释义来源，仅用于来源指纹"),
    ("meaning_corrections", "data/meaning_corrections.json", False, True, "file", "上游释义修正，仅用于来源指纹"),
    ("ecdict", "data/ecdict.csv", False, True, "file", "完整 ECDICT 重建源；常规构建不再依赖 66MB 原表"),
    ("ecdict_subset", "data/ecdict_subset.json", True, True, "file", "详情生成所需的可复现 ECDICT 子集"),
    ("lemma", "data/lemma.en.txt", False, True, "file", "上游词形还原来源，仅用于来源指纹"),
    ("manifest", "software/manifest.webmanifest", True, False, "file", "PWA manifest"),
    ("icon_192", "software/icon-192.png", True, False, "file", "PWA 图标 192"),
    ("icon_512", "software/icon-512.png", True, False, "file", "PWA 图标 512"),
    ("ky2_ref", "ref/ky2", False, False, "dir", "英语二真题原件；可选来源元数据"),
    ("ky1_ref", "ref/ky1", False, False, "dir", "英语一真题原件；可选来源元数据"),
)
INPUT_BY_KEY = {entry[0]: entry for entry in INPUT_MANIFEST}


def get_input_path(key: str):
    """返回 manifest 中的可选/必需路径；不存在或类型不符时返回 None。"""
    _, rel_path, _required, _digest, kind, _role = INPUT_BY_KEY[key]
    path = ROOT / rel_path
    if kind == "file":
        return path if path.is_file() else None
    return path if path.is_dir() else None


def require_input_path(key: str):
    path = get_input_path(key)
    if path is None:
        _, rel_path, _required, _digest, _kind, role = INPUT_BY_KEY[key]
        raise RuntimeError("缺少必需构建输入：%s (%s)" % (rel_path, role))
    return path


def validate_input_manifest():
    missing = []
    for key, rel_path, required, _digest, kind, role in INPUT_MANIFEST:
        if not required:
            continue
        path = ROOT / rel_path
        valid = path.is_file() if kind == "file" else path.is_dir()
        if not valid:
            missing.append(f"  - {key}: {rel_path} ({role})")
    if missing:
        raise RuntimeError("缺少必需构建输入：\n" + "\n".join(missing))


def release_lock():
    """只由 token 对应的持锁者释放；显式释放后 atexit 不再重复执行。"""
    token = globals().get("LOCK_TOKEN")
    fd = globals().get("LOCK_FD")
    globals()["LOCK_TOKEN"] = None
    globals()["LOCK_FD"] = None
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass
    if token:
        try:
            current_token = LOCK.read_text(encoding="ascii")
        except (FileNotFoundError, OSError):
            current_token = None
        if current_token == token:
            try:
                LOCK.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
    registered = globals().get("_LOCK_ATEXIT_REGISTERED", False)
    globals()["_LOCK_ATEXIT_REGISTERED"] = False
    unregister = getattr(atexit, "unregister", None)
    if registered and unregister is not None:
        try:
            unregister(release_lock)
        except Exception:
            pass


def acquire_lock():
    """用 O_EXCL 建锁并写入随机 token；不自动抢占/删除任何既有锁。"""
    if globals().get("LOCK_FD") is not None or globals().get("LOCK_TOKEN") is not None:
        raise RuntimeError("当前进程已经持有构建锁")
    token = os.urandom(32).hex()
    try:
        fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        owner = "unknown"
        try:
            owner = LOCK.read_text(encoding="ascii", errors="replace")[:80]
        except OSError:
            pass
        raise RuntimeError(
            "另一个构建正在运行（deploy.lock 已存在，owner=%s）；"
            "确认无构建进程后再手动删除该锁文件" % owner
        )
    payload = token.encode("ascii")
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(fd, payload[offset:])
            if written <= 0:
                raise OSError("写入构建锁 token 失败")
            offset += written
        os.fsync(fd)
    except BaseException as exc:
        try:
            os.close(fd)
        except OSError:
            pass
        # 这个文件是本进程通过 O_EXCL 刚创建的；写入/fsync 失败时立即回收，
        # 避免留下没有完整 ownership token 的残锁。不要读取既有锁再删除。
        try:
            LOCK.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
        raise RuntimeError("创建构建锁失败：%s" % exc) from exc
    globals()["LOCK_FD"] = fd
    globals()["LOCK_TOKEN"] = token
    try:
        atexit.register(release_lock)
        globals()["_LOCK_ATEXIT_REGISTERED"] = True
    except BaseException:
        release_lock()
        raise

acquire_lock()
validate_input_manifest()

# 唯一暂存目录；只有完整构建并写完软件产物后才替换 deploy/。
DEPLOY_TMP_ROOT.mkdir(parents=True, exist_ok=True)
DEPLOY = Path(tempfile.mkdtemp(prefix="build-%s-" % LOCK_TOKEN[:8], dir=DEPLOY_TMP_ROOT))



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


def atomic_write_text(path: Path, content: str):
    """同目录临时文件 + os.replace，避免 software 产物只写了一半。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=".%s." % path.name, suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def cleanup_staging():
    """异常退出时清理本次构建的唯一暂存目录；成功的目录已改名为 deploy/。"""
    stage = globals().get("DEPLOY")
    if stage is None:
        return
    try:
        if stage.exists():
            rmtree_force(stage)
    except Exception:
        pass


atexit.register(cleanup_staging)

def load_json_input(key):
    path = require_input_path(key) if INPUT_BY_KEY[key][2] else get_input_path(key)
    return json.loads(path.read_text(encoding="utf-8")) if path is not None else None


rows = load_json_input("words")
derivatives = load_json_input("derivatives")
basic = load_json_input("basic")
insurance = load_json_input("insurance")
freq = load_json_input("ky2_freq")
ky1 = load_json_input("ky1_freq") or {}
summary = load_json_input("selection_summary")

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def source_digest_entries():
    entries = []
    for key, rel_path, required, include_digest, kind, _role in INPUT_MANIFEST:
        if not include_digest:
            continue
        path = require_input_path(key) if required else get_input_path(key)
        if path is None:
            continue
        if kind == "file":
            entries.append(rel_path + ":" + sha256(path))
        elif kind == "dir":
            for child in sorted((item for item in path.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
                child_rel = child.relative_to(ROOT).as_posix()
                entries.append(child_rel + ":" + sha256(child))
    return entries

source_files = []
for exam, input_key in (("english_2", "ky2_ref"), ("english_1", "ky1_ref")):
    folder_path = get_input_path(input_key)
    if folder_path is None:
        # 真题原件是可选的来源元数据；缺失不影响词库和网页构建。
        continue
    paths = sorted(folder_path.rglob("*.pdf"))
    if exam == "english_1":
        # 与 build_freq_ky1 的真实输入保持一致：合订本 + 2022-2024 的真题原件，
        # 解析 PDF 只是参考资料，不能伪装成计频来源。
        combined = [path for path in paths if "2010-2021" in path.name]
        selected = combined[:1]
        for year in (2022, 2023, 2024):
            candidates = [path for path in paths if str(year) in path.name]
            if candidates:
                selected.append(min(candidates, key=lambda item: item.stat().st_size))
        paths = selected
    for path in paths:
        source_files.append({
            "exam": exam,
            "name": path.relative_to(folder_path).as_posix(),
            "sha256": sha256(path),
        })

meta = dict(freq.get("meta", {}))
meta.update({
    "generated_at": os.environ.get("KY_BUILD_DATE") or datetime.fromtimestamp(int(os.environ.get("SOURCE_DATE_EPOCH", "1793203200")), timezone.utc).date().isoformat(),
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



template_path = require_input_path("template")
template = assemble_template()
# Keep the tracked compatibility artifact in sync with ordered source fragments.
atomic_write_text(template_path, template)
# 合并算法只有一份实现，构建时分别注入前端和 Worker
merge_source = require_input_path("merge_source").read_text(encoding="utf-8")


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
    path = require_input_path("ecdict_subset")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise RuntimeError("ecdict subset schema_version 不受支持")
    fields = payload.get("field_names")
    entries = payload.get("entries")
    if not isinstance(fields, list) or not isinstance(entries, dict):
        raise RuntimeError("ecdict subset 结构不完整")

    word_forms = {}
    lookup = set()
    for r in rows:
        word = r["word"]
        forms = [f.lower() for f in (r.get("forms") or []) if f and f.lower() != word]
        word_forms[word] = forms
        lookup.add(word)
        lookup.update(forms)

    ecdict = {}
    for word in lookup:
        values = entries.get(word)
        if isinstance(values, list) and len(values) == len(fields):
            ecdict[word] = dict(zip(fields, values))

    detail = {}
    for word, forms in word_forms.items():
        row = ecdict.get(word)
        if not row:
            continue
        translation = normalize_translation(row.get("translation"))
        groups = []
        for line in translation.split("\n"):
            line = line.strip()
            # 一行可能连续带多个标签（如 "[医] [疾]病"），全部剥掉但保留实际释义。
            line = re.sub(r"^(?:\[[^\]]+\]\s*)+", "", line).strip()
            if not line:
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

# DEPLOY 是本次构建独占的唯一目录，不需要也不应该清理其他构建的暂存目录。

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


def terser_command():
    """优先使用项目本地 node_modules，缺失时才用精确版本的 npx 缓存。"""
    local_package = ROOT / "node_modules" / "terser" / "package.json"
    local_entry = ROOT / "node_modules" / "terser" / "bin" / "terser"
    if local_package.is_file() or local_entry.is_file():
        if not local_package.is_file() or not local_entry.is_file():
            raise RuntimeError("本地 terser 安装不完整，请安装 terser@%s" % TERSER_VERSION)
        try:
            installed_version = json.loads(local_package.read_text(encoding="utf-8"))["version"]
        except Exception as exc:
            raise RuntimeError("无法读取本地 terser 版本：%s" % exc) from exc
        if installed_version != TERSER_VERSION:
            raise RuntimeError(
                "本地 terser 版本为 %s，构建固定要求 %s" %
                (installed_version, TERSER_VERSION))
        node = shutil.which("node")
        if not node:
            raise RuntimeError("本地 terser 需要 Node：找不到 node")
        return [node, str(local_entry)]
    npx = shutil.which("npx")
    if not npx:
        raise RuntimeError(
            "找不到本地 terser 或 npx：请安装 terser@%s，或显式 KY_NO_MINIFY=1 跳过压缩" %
            TERSER_VERSION)
    # 版本固定，npx 只负责缺失时安装精确版本，不会解析到“latest”而漂移。
    return [npx, "--yes", "terser@%s" % TERSER_VERSION]


# 网页版主程序用 Terser 压缩。压缩失败必须让构建失败：
# 静默回退到未压缩源码会让产物体积翻倍、且没人发现，构建也不可复现。
# 确实要跳过压缩时显式设置 KY_NO_MINIFY=1。
if os.environ.get("KY_NO_MINIFY"):
    print("minify=skipped")
else:
    try:
        minified = subprocess.run(
            terser_command() + ["--compress", "--mangle", "--format", "comments=false"],
            input=app_js.encode("utf-8"), capture_output=True, timeout=180,
        )
    except Exception as exc:
        raise RuntimeError("terser 调用失败：%s" % exc) from exc
    if minified.returncode != 0 or not minified.stdout.strip():
        raise RuntimeError("terser 压缩失败：%s" % minified.stderr.decode("utf-8", "replace")[:300])
    app_js = minified.stdout.decode("utf-8")
if "sourceMappingURL=" in app_js:
    raise RuntimeError("terser 输出了 source map 指令，拒绝写入单文件版")

# 单文件版复用同一份压缩主程序，只替换脚本正文；四套词库仍完整内嵌。
standalone_app_match = re.search(r'<script id="ky-app">(.*?)</script>', standalone_html, re.S)
if not standalone_app_match:
    raise RuntimeError("standalone ky-app script block not found")
standalone_html = (
    standalone_html[:standalone_app_match.start()]
    + '<script id="ky-app">'
    + app_js
    + '</script>'
    + standalone_html[standalone_app_match.end():]
)

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
sw_template = require_input_path("sw_template").read_text(encoding="utf-8")
worker_template = require_input_path("worker_template").read_text(encoding="utf-8")
source_digest = hashlib.sha256(
    "\n".join(source_digest_entries()).encode("utf-8")
).hexdigest()
build_version = hashlib.sha256(
    "\n".join((
        re.sub(r'"generated_at":"[^"]*"', "", web_html),
        sw_template,
        worker_template,
        merge_source,
        source_digest,
        sha256(require_input_path("manifest")),
        sha256(require_input_path("icon_192")),
        sha256(require_input_path("icon_512")),
    )).encode("utf-8")
).hexdigest()[:12]
# 详情分片不进 SW 预缓存：它只在第一次长按时才用到，不该拖慢首次安装
runtime_assets = [asset_map[k] for k in ("words", "derivatives", "basic", "insurance")]
sw_js = (
    sw_template
    .replace("__BUILD_VERSION__", build_version)
    .replace("__APP_ASSET__", app_asset)
    .replace("__DATA_ASSETS__", json.dumps(runtime_assets, ensure_ascii=False))
)

(DEPLOY / "index.html").write_text(web_html, encoding="utf-8", newline="\n")
(DEPLOY / "sw.js").write_text(sw_js, encoding="utf-8", newline="\n")
for input_key, name in (
    ("manifest", "manifest.webmanifest"),
    ("icon_192", "icon-192.png"),
    ("icon_512", "icon-512.png"),
):
    shutil.copy2(require_input_path(input_key), DEPLOY / name)
# Worker 是单文件部署（Pages 高级模式下 _worker.js 不能带外部 import），
# 合并模块在构建时注入进来，源码里只留一个占位符。
worker_source = inject(worker_template, MERGE_MARKER, merge_source)
(DEPLOY / "_worker.js").write_text(worker_source, encoding="utf-8", newline="\n")
(DEPLOY / "build-meta.json").write_text(
    json.dumps({"build": build_version, "source_digest": source_digest, "app_asset": app_asset}, ensure_ascii=False, separators=(",", ":")) + "\n",
    encoding="utf-8", newline="\n",
)
(DEPLOY / "_headers").write_text(
    "/*\n"
    "  X-Content-Type-Options: nosniff\n"
    "  Referrer-Policy: same-origin\n"
    "  Strict-Transport-Security: max-age=31536000; includeSubDomains\n"
    "  Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()\n"
    "  Cross-Origin-Opener-Policy: same-origin\n"
    "  Cross-Origin-Resource-Policy: same-origin\n"
    "  Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob: data: https://dict.youdao.com; connect-src 'self'; manifest-src 'self'; frame-ancestors 'none'; frame-src 'none'; script-src-attr 'none'; base-uri 'none'; form-action 'self'; object-src 'none'\n"
    "/index.html\n  Cache-Control: public, max-age=0, must-revalidate\n"
    "/sw.js\n  Cache-Control: no-cache\n"
    "/build-meta.json\n  Cache-Control: no-cache\n"
    "/manifest.webmanifest\n  Cache-Control: public, max-age=3600\n"
    "/data/*\n  Cache-Control: public, max-age=31536000, immutable\n"
    "/app.*.js\n  Cache-Control: public, max-age=31536000, immutable\n",
    encoding="utf-8",
    newline="\n",
)

# 唯一暂存目录现已写完；再原子写软件产物，最后整体切换 deploy/。
backup = DEPLOY_TMP_ROOT / ("old-%s" % LOCK_TOKEN)
if backup.exists():
    raise RuntimeError("构建备份目录意外存在：%s" % backup)
moved_old = False
try:
    atomic_write_text(OUT, standalone_html)
    atomic_write_text(SOFT / "sw.js", sw_js)
    if DEPLOY_FINAL.exists():
        os.replace(DEPLOY_FINAL, backup)
        moved_old = True
    os.replace(DEPLOY, DEPLOY_FINAL)
    DEPLOY = None
except BaseException:
    # 第二次 rename 失败时恢复旧版本，不能把唯一可用目录留在备份路径。
    if moved_old and not DEPLOY_FINAL.exists() and backup.exists():
        os.replace(backup, DEPLOY_FINAL)
    raise
finally:
    if backup.exists() and DEPLOY_FINAL.exists():
        try:
            rmtree_force(backup)
        except Exception as exc:
            print("warning: deploy backup cleanup failed: %s" % exc)
    if DEPLOY is not None:
        try:
            if DEPLOY.exists():
                rmtree_force(DEPLOY)
        except Exception as exc:
            print("warning: deploy staging cleanup failed: %s" % exc)
    release_lock()

print(f"output={OUT}")
print(f"deploy={DEPLOY_FINAL / 'index.html'}")
print(f"words={len(slim)} derivatives={len(derivative_slim)} basic={len(basic_slim)} insurance={len(insurance_slim)}")
print(f"app={len(app_js.encode('utf-8')) / 1024:.0f}KB standalone={OUT.stat().st_size / 1024:.0f}KB "
      f"web={len(web_html.encode('utf-8')) / 1024:.0f}KB build={build_version}")
