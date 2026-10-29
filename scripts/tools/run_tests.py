# -*- coding: utf-8 -*-
"""统一回归测试：把散落的验证点整合成一个可重复执行的套件。

用法：
    python scripts/tools/run_tests.py

全部通过返回 0，有失败返回 1（可用于 CI 或部署前门禁）。
"""
from __future__ import annotations

import ast
import csv
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
import textwrap
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUILT = os.path.join(ROOT, "software", "考研核心词.html")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def source_sha256(path):
    suffix = Path(path).suffix.lower()
    if suffix in {".css", ".csv", ".html", ".js", ".json", ".md", ".py", ".sql", ".txt", ".webmanifest"}:
        data = Path(path).read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        return hashlib.sha256(data).hexdigest()
    return file_sha256(path)


def expected_source_digest():
    paths = [
        "software/template.html", "software/sw.template.js", "backend/worker.js",
        "shared/merge.js", "scripts/make_html.py", "software/src", "data/words.json", "data/words_order.json",
        "data/derivatives.json", "data/basic.json", "data/insurance.json",
        "data/ky2_freq.json", "data/selection_summary.json", "data/ky1_freq.json",
        "data/meanings_curated.json", "data/meanings_final.json",
        "data/meaning_corrections.json", "data/ecdict_subset.json",
    ]
    parts = []
    for rel in paths:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            continue
        if os.path.isdir(path):
            for child in sorted((Path(path).rglob("*")), key=lambda item: item.as_posix()):
                if child.is_file():
                    child_rel = child.relative_to(ROOT).as_posix()
                    parts.append(child_rel + ":" + source_sha256(child))
        else:
            parts.append(rel + ":" + source_sha256(path))
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


results = []

# 首卡时间预算：本地生产基线 800ms。共享 CI runner 的冷启动明显慢于开发机，
# 用 KY_PERF_BUDGET_MS 单独放宽 gate，避免机器噪声把真实回归淹没成假红。
PERF_BUDGET_MS = int(os.environ.get("KY_PERF_BUDGET_MS", "800"))


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))


# ---------- 静态检查（不需要浏览器）----------
def run_node_harness(script, files=None, timeout=180):
    """Run real JS in a temporary directory under scripts/tools."""
    harness_dir = tempfile.mkdtemp(prefix=".node-harness-", dir=os.path.join(ROOT, "scripts", "tools"))
    try:
        for name, content in (files or {}).items():
            path = os.path.join(harness_dir, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with io.open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
        harness = os.path.join(harness_dir, "harness.mjs")
        with io.open(harness, "w", encoding="utf-8", newline="\n") as f:
            f.write(script)
        env = dict(os.environ)
        env["KY_HARNESS_DIR"] = harness_dir
        proc = subprocess.run(
            ["node", harness], cwd=ROOT, env=env, capture_output=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
        data = None
        for line in proc.stdout.splitlines():
            if line.startswith("RESULT:"):
                try:
                    data = json.loads(line[7:])
                except json.JSONDecodeError:
                    data = None
        return data, proc
    finally:
        shutil.rmtree(harness_dir, ignore_errors=True)


def harness_detail(proc):
    text = (proc.stderr or proc.stdout or "").strip().replace("\n", " ")
    return text[:500]


def materialized_worker_source():
    worker = io.open(os.path.join(ROOT, "backend", "worker.js"), encoding="utf-8").read()
    merge = io.open(os.path.join(ROOT, "shared", "merge.js"), encoding="utf-8").read()
    marker = "/*__MERGE__*/"
    if marker not in worker:
        raise RuntimeError("backend/worker.js merge marker missing")
    return worker.replace(marker, merge, 1)


def static_checks():
    if not os.path.exists(BUILT):
        check("产物存在", False, "先跑 make_html.py")
        return
    t = io.open(BUILT, encoding="utf-8").read()
    source_html = io.open(os.path.join(ROOT, "software", "template.html"), encoding="utf-8").read()

    # 单文件版内联了长按详情（约 416KB），上限相应放宽；网页版首包不受影响
    check("产物大小 < 1.2MB", os.path.getsize(BUILT) < 1200 * 1024,
          "%.0fKB" % (os.path.getsize(BUILT) / 1024))
    check("无 autoShow 残留", t.count("autoShow") <= 2,
          "仅允许 delete conf.autoShow 清理语句")
    check("无 forms-title 残留", t.count("forms-title") == 0)
    check("无「考查形式」字样", t.count("考查形式") == 0)
    check("释义开关存在", t.count("meaningToggle") >= 2, "按钮 HTML + 事件")
    check("含 showByDefault 设置", "showByDefault" in t)
    check("无 INTERVALS 残留", t.count("INTERVALS") == 0)
    check("含 posWord 进度定位", "posWord" in t)
    check("含撤销条", "undoBar" in t)
    check("含导出进度", "exportProgress" in t)
    check("含 deckChapter 记忆", "deckChapter" in t)
    check("含登录面板", "authModal" in t and "accountBtn" in t)
    check("含云同步接口", "/state" in t and "snapshot" in t)
    check("同步单请求快路径", all(x in t for x in ("baseUpdatedAt", "syncWithServer", "/state/sync", "/state?since=", "CompressionStream")))
    check("同步变更追踪", all(x in t for x in ("syncDirty", "localRevision", "noteLocalChange")))
    # 合并算法只有 shared/merge.js 一份实现，前端和 Worker 都是构建时注入的
    check("合并实现来自共享模块", "function mergeSnapshots" in t and "function isTombstone" in t,
          "standalone 里应有注入后的合并代码")
    check("共享模块未被复制回源码",
          "__MERGE__" in io.open(os.path.join(ROOT, "software", "template.html"), encoding="utf-8").read()
          and "__MERGE__" in io.open(os.path.join(ROOT, "backend", "worker.js"), encoding="utf-8").read())
    check("清空用墓碑而非 forceAt", "tombstone(now)" in source_html and "conf.forceAt =" not in source_html)
    check("清空/导入请求服务端补墓碑", "overwritePending" in t)
    check("导入保留备份里的墓碑", "const incoming = validateStateStore(d.state, now);" in source_html and "if (rec.del === 1)" in source_html)
    check("竞态跳过不推进同步版本",
          source_html.index("return { result, changedLocally: false, skipped: true };")          < source_html.index("lastSyncAt = result.updatedAt || Date.now();"),
          "guard 必须挡在推进 lastSyncAt 之前，否则下一轮会用旧快照 PUT 覆盖")
    check("含恢复原序按钮", "restoreOrder" in t)
    check("每词唯一权重", "displayWeightOf" in t and '"weight":' in t and "综合权重" not in t)
    check("含鼠标滚轮翻词", "wheelLockedUntil" in source_html and "addEventListener('wheel'" in source_html)
    check("含发音代理", "/api/audio?" in t)
    check("朗读可切中英文", all(x in t for x in ("speakLang", "zhVoice", "toggleSpeakLang", "meaningForSpeech")))
    check("朗读键长按切换语言", "speakLongFired" in t and "pointerdown" in t and "pointercancel" in t)
    check("中文语音状态如实展示", "zhVoiceStat" in t and "zhVoiceStatus" in t and "AUDIO_PROXY_READY" in t)
    check("中文朗读走百度可缓存音频", all(x in t for x in ("lang=zh", "offlineZhTexts", "AUDIO_PROXY_READY")))
    check("卡片顶部锚定不随释义跳动", "justify-content:flex-start" in t and "clamp(34px,10vh,88px)" in t)
    check("发音预加载可秒播", all(x in source_html for x in ("AUDIO_PRELOAD_AHEAD", "audioPlayers", "readyState >= 2")))
    check("发音 Blob 内存缓存", "audioBlobUrls" in source_html and "URL.createObjectURL(blob)" in source_html)
    check("新词发音不等待网络", "新词不等待网络" in source_html and "1800" not in source_html)
    check("含 Service Worker 注册", "navigator.serviceWorker.register('./sw.js'" in source_html)
    check("含离线缓存资源", os.path.exists(os.path.join(ROOT, "software", "sw.js"))
          and os.path.exists(os.path.join(ROOT, "software", "manifest.webmanifest")))
    check("离线账号可恢复", "LS_AUTH" in t and "savedAuthUser" in t)
    check("词表分批渲染", "LIST_PAGE_SIZE" in t and "list-more" in t)
    check("移除首屏毛玻璃", "backdrop-filter:blur(12px)" not in t)
    check("含自定义图标", all(x in t for x in ("iconChoices", "iconUpload", "ICON_PRESETS", "appFavicon")))

    # --- 长按详情 ---
    check("含长按详情面板", all(x in t for x in ("detailMask", "detailSheet", "pressTimer")))
    check("长按详情数据块", 'id="ky-deck-detail"' in t)
    check("详情带音标与真题次数", '"p":' in t and '"freq":' in t)
    check("详情词典默认展开", "$('detailDictBox').open = true" in source_html)
    check("等级只用单字母上卡片", "PRIORITY_LABELS" in source_html and "el.textContent = level;" in source_html)
    check("图标有体积上限", "ICON_DATA_MAX" in source_html and "icon.data.length <= ICON_DATA_MAX" in source_html)
    check("头像不等网络就先渲染",
          "renderAuth();" in source_html.split("let authMode = 'login';")[1][:160])
    check("头像读屏标签随登录态变", "btn.setAttribute('aria-label'" in source_html)

    # --- 首屏：词库走 JSON 数据块，按需解析 ---
    check("词库改用 JSON 数据块", t.count('type="application/json"') == 6)
    check("无内联词表字面量", "const WORDS =" not in t)
    first_screen = json_block_bytes(t, "words")
    check("首屏解析数据量 < 250KB", 0 < first_screen < 250 * 1024, "%.0fKB" % (first_screen / 1024))
    check("全量表惰性构建", "const allWords =" in source_html and "allWordsCache" in source_html)
    check("词位索引惰性构建", "wordLocationCache" in t)
    check("首卡渲染打点", "__firstCardAt" in t)
    check("启动校验不触发章节常量 TDZ", t.find("const CHAPTER_SIZE") >= 0 and t.find("const CHAPTER_SIZE") < t.find("validateStateStore(state"))
    source_paths = [os.path.join(ROOT, "software", "template.html"), os.path.join(ROOT, "software", "sw.template.js"), os.path.join(ROOT, "backend", "worker.js"), os.path.join(ROOT, "shared", "merge.js"), os.path.join(ROOT, "scripts", "make_html.py"), os.path.join(ROOT, "scripts", "deploy.py")]
    dirty_sources = [os.path.relpath(p, ROOT) for p in source_paths if os.path.exists(p) and chr(0xfffd) in io.open(p, encoding="utf-8").read()]
    check("source text is clean", not dirty_sources, str(dirty_sources[:5]))
    bundle_proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "frontend_bundle.py"), "--check"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    check("前端源片段可重建模板", bundle_proc.returncode == 0,
          (bundle_proc.stdout + bundle_proc.stderr).strip()[:160])
    check("模板占位符完整", io.open(os.path.join(ROOT, "software", "template.html"), encoding="utf-8").read().count("/*__MERGE__*/") == 1)
    check("交互元素无重复ID", len(re.findall(r'\bid="([^"]+)"', t)) == len(set(re.findall(r'\bid="([^"]+)"', t))))

    # --- 离线 ---
    sw_path = os.path.join(ROOT, "software", "sw.js")
    sw = io.open(sw_path, encoding="utf-8").read() if os.path.exists(sw_path) else ""
    check("SW 版本号已注入", sw != "" and "__BUILD_VERSION__" not in sw)
    check("SW 导航离线回退", "离线缓存尚未完成" in sw)
    check("SW 发音优先缓存", "cacheFirstAudio" in sw)
    check("SW 不拦接口请求", "url.pathname.includes('/api/')" in sw)
    check("SW 注册禁缓存", "updateViaCache: 'none'" in source_html and "registration.update()" in source_html)
    check("头像弹窗带全量下载入口",
          all(x in t for x in ("offlineStart", "offlineStop", "runOfflineDownload")))
    check("SW 音频缓存放得下全量", "AUDIO_CACHE_MAX = 8000" in sw)
    # SW 换音频缓存名会清空已下好的音频；前端那两个「已下载」标记必须跟着换版本，
    # 否则会以为全都下过了，后台补下载永远不再启动，用户就一直走慢路径
    check("前端音频标记与 SW 缓存版本对齐",
          "AUDIO_CACHE_VERSION = 'v2'" in source_html and "AUDIO_CACHE = 'ky-audio-v2'" in sw
          and "'ky_audio_words_v1'" not in source_html and "'ky_auto_offline_v1'" not in source_html)
    check("SW 音频缓存只存成功响应", "if (!network.ok)" in sw and "storeAudioResponse(cache, key, network)" in sw)
    check("SW缓存写入反馈协议", "x-ky-cache" in sw and "store-failed" in sw and "AUDIO_CACHE_CONFIRMED_HEADER" in t)
    check("SW淘汰通知页面", "ky:audio-evicted" in sw and "ky:audio-evicted" in t)
    check("离线下载有取消控制器", "new AbortController()" in source_html and "offlineJob.controller" in source_html)
    check("离线准备失败释放任务槽", "words = await offlineWordList();" in source_html and "offlineJob = null;" in source_html)
    check("离线自动批次检查全量目标", "const allTargets = targets;" in source_html and "allTargets.some(t =>" in source_html)
    check("离线请求超时可独立取消", "externalSignal.removeEventListener" in source_html and "OFFLINE_FETCH_TIMEOUT" in source_html)
    check("详情失败不缓存网络空分片", "delete detailShards[key]; throw new Error(\x27detail load failed\x27)" in io.open(os.path.join(ROOT, "software", "template.html"), encoding="utf-8").read())
    check("章节音频定时器可取消", "chapterPrefetchTimer" in t and "clearTimeout(chapterPrefetchTimer)" in t)
    merge_source = io.open(os.path.join(ROOT, "shared", "merge.js"), encoding="utf-8").read()
    check("清空只删除旧记录保留并发新学习",
          "stamp > t ? rec" in merge_source and "keepRecord ? rec : tombstone(t)" in merge_source)
    # 页面把下载成功记成「已缓存」，SW 要是因配额紧张就跳过存储，两边状态会分叉
    check("SW 配额紧张时淘汰而不是拒存", "storeAudioResponse" in sw and "evictAudioEntries(" in sw)
    check("SW 新版本通知刷新", "ky:sw-updated" in sw and "client.navigate(client.url)" not in sw)
    mf_path = os.path.join(ROOT, "software", "manifest.webmanifest")
    mf = io.open(mf_path, encoding="utf-8").read() if os.path.exists(mf_path) else ""
    check("manifest 独立显示", '"display": "standalone"' in mf)
    check("manifest 图标齐备",
          os.path.exists(os.path.join(ROOT, "software", "icon-192.png"))
          and os.path.exists(os.path.join(ROOT, "software", "icon-512.png")))

    # --- 构建产物 ---
    deploy = os.path.join(ROOT, "deploy")
    meta_path = os.path.join(deploy, "build-meta.json")
    meta = json.load(io.open(meta_path, encoding="utf-8")) if os.path.exists(meta_path) else {}
    check("构建产物带来源指纹", meta.get("source_digest") == expected_source_digest(),
          "rerun make_html.py" if meta else "build-meta.json 缺失")
    allowed = {"index.html", "sw.js", "_worker.js", "_headers", "manifest.webmanifest",
               "icon-192.png", "icon-512.png", "data", "build-meta.json"}
    if os.path.isdir(deploy):
        extra = sorted(x for x in set(os.listdir(deploy)) - allowed if not re.fullmatch(r"app\.[0-9a-f]{12}\.js", x))
        check("部署目录无多余文件", not extra, str(extra[:5]))
        check("部署含 _worker.js", os.path.exists(os.path.join(deploy, "_worker.js")))
        worker_js = io.open(os.path.join(deploy, "_worker.js"), encoding="utf-8").read() \
            if os.path.exists(os.path.join(deploy, "_worker.js")) else ""
        check("worker 支持中文 TTS 代理",
              "fanyi.baidu.com/gettts" in worker_js and "AUDIO_ZH_RE" in worker_js)
        # 释义里就有「...」「…」「《》」，正则漏一个字符，那条中文朗读就是 400 没声音
        check("中文 TTS 正则放行释义符号",
              "，、。；;:：.…《》" in worker_js)
        web_path = os.path.join(deploy, "index.html")
        web_html = io.open(web_path, encoding="utf-8").read() if os.path.exists(web_path) else ""
        web_gzip = len(gzip.compress(web_html.encode("utf-8"), 9)) if web_html else 0
        check("网页首包 gzip < 50KB", 0 < web_gzip < 50 * 1024, "%.1fKB" % (web_gzip / 1024))
        web_words = json_block_value(web_html, "words")
        check("网页首屏只内嵌少量词", 0 < len(web_words) <= 50, "%d 词" % len(web_words))
        app_files = [x for x in os.listdir(deploy) if re.fullmatch(r"app\.[0-9a-f]{12}\.js", x)]
        check("网页主程序独立缓存", len(app_files) == 1 and ("src=\"./" + app_files[0] + "\"") in web_html, str(app_files))
        data_dir = os.path.join(deploy, "data")
        data_files = sorted(os.listdir(data_dir)) if os.path.isdir(data_dir) else []
        data_names = [re.sub(r"\.[0-9a-f]{12}\.json$", "", x) for x in data_files]
        deck_names = [x.split(".", 1)[0] for x in data_files]
        check("网页词库拆分资源齐备",
              all(x.endswith(".json") for x in data_files)
              and {"words", "derivatives", "basic", "insurance"} <= set(deck_names), str(data_files))
        deploy_sw = io.open(os.path.join(deploy, "sw.js"), encoding="utf-8").read() if os.path.exists(os.path.join(deploy, "sw.js")) else ""
        check("SW 预缓存拆分词库", "./data/" in deploy_sw and "__DATA_ASSETS__" not in deploy_sw)
        check("SW 预缓存主程序", any(("./" + x) in deploy_sw for x in app_files))
        headers = io.open(os.path.join(deploy, "_headers"), encoding="utf-8").read() if os.path.exists(os.path.join(deploy, "_headers")) else ""
        check("拆分词库长期缓存", "/data/*" in headers and "immutable" in headers)
        check("主程序长期缓存", "/app.*.js" in headers and "immutable" in headers)
        check("部署带 nosniff 与 CSP",
              "X-Content-Type-Options: nosniff" in headers
              and "Content-Security-Policy" in headers
              and "frame-ancestors 'none'" in headers)
        detail_files = [x for x in data_files if x.startswith("detail-")]
        detail_sizes = [os.path.getsize(os.path.join(data_dir, x)) for x in detail_files]
        check("详情按首字母分片", len(detail_files) >= 24, "%d 片" % len(detail_files))
        check("详情单片 < 80KB", bool(detail_sizes) and max(detail_sizes) < 80 * 1024,
              "最大 %.0fKB" % (max(detail_sizes) / 1024 if detail_sizes else 0))
    else:
        check("部署目录无多余文件", False, "先跑 make_html.py")
        check("部署含 _worker.js", False)

    check("顶栏合并词库与词数", "deck-inline" in t and "deck-bar" not in t and "deck-label" not in t)
    check("顶栏无品牌文字与旧标签", "英语二词汇" not in t and "deck-label" not in t and "deck-bar" not in t)
    check("页面标题不含英语二", "<title>考研核心词汇</title>" in t)
    check("应用名称不含英语二", "英语二" not in mf)


def json_block_value(html, deck_id):
    """读取某个内嵌 JSON 数据块。"""
    head = '<script type="application/json" id="ky-deck-%s">' % deck_id
    start = html.find(head)
    if start < 0:
        return []
    start += len(head)
    end = html.find("</script>", start)
    if end < 0:
        return []
    try:
        return json.loads(html[start:end])
    except Exception:
        return []


def json_block_bytes(html, deck_id):
    """算出某个数据块在首屏需要 JSON.parse 的字节数。"""
    head = '<script type="application/json" id="ky-deck-%s">' % deck_id
    start = html.find(head)
    if start < 0:
        return 0
    start += len(head)
    end = html.find("</script>", start)
    return end - start if end > start else 0


# ---------- 数据完整性 ----------
def data_checks():
    D = os.path.join(ROOT, "data")
    decks = ("words", "derivatives", "basic", "insurance")
    allw, total = {}, 0
    for d in decks:
        p = os.path.join(D, d + ".json")
        if not os.path.exists(p):
            check("数据 %s 存在" % d, False)
            continue
        data = json.load(io.open(p, encoding="utf-8"))
        total += len(data)
        ids = [x["id"] for x in data]
        check("%s id 1..N 连续" % d, ids == list(range(1, len(data) + 1)), "%d 词" % len(data))
        empty = [x["word"] for x in data if not (x.get("meaning") or "").strip()]
        check("%s 无空释义" % d, not empty, str(empty[:5]))
        bad_word = [x["word"] for x in data if not re.fullmatch(r"[a-z][a-z'\- ]*", x["word"])]
        check("%s 词形规范" % d, not bad_word, str(bad_word[:5]))
        bad_pri = [x["word"] for x in data if not re.fullmatch(r"[SABC]( .*)?", x.get("priority") or "")]
        check("%s priority 合法" % d, not bad_pri, str(bad_pri[:5]))
        bad_forms = [x["word"] for x in data if not isinstance(x.get("forms"), list)]
        check("%s forms 为数组" % d, not bad_forms, str(bad_forms[:5]))
        for x in data:
            allw.setdefault(x["word"], []).append(d)
    dup = {w: v for w, v in allw.items() if len(v) > 1}
    check("跨库无重复词", not dup, str(list(dup.items())[:3]))
    check("总词数 > 3000", total > 3000, "%d 词" % total)
    stub = [w for w in allw if len(w) < 2]
    check("无词根碎片", not stub, str(stub[:5]))

    # 派生库单独审：重要在前、四档齐全、别把原形词当派生词收进来
    deriv = json.load(io.open(os.path.join(D, "derivatives.json"), encoding="utf-8"))
    order = "SABC"
    levels = [x["priority"][0] for x in deriv]
    check("派生词分级齐全", set(levels) == set(order), str(sorted(set(levels))))
    ranks = [order.index(level) for level in levels]
    check("派生词按等级从高到低排", ranks == sorted(ranks), "首位=%s" % deriv[0]["priority"])
    scores = [x["priority_score"] for x in deriv]
    check("派生词按分数从高到低排",
          all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1)), "首位=%s" % scores[0])
    pairs = {x["word"]: x["family"] for x in deriv}
    loops = [word for word, family in pairs.items() if pairs.get(family) == word]
    check("派生词没有互相指认", not loops, str(loops[:5]))
    # 生成脚本目前只维护 JSON 为权威数据；CSV 必须与同源结果一致，不能一边 1545 条、一边 1456 条。
    for deck in ("words", "insurance"):
        csv_path = os.path.join(D, deck + ".csv")
        json_path = os.path.join(D, deck + ".json")
        rows = json.load(io.open(json_path, encoding="utf-8"))
        if not os.path.exists(csv_path):
            check("%s CSV 与 JSON 同源" % deck, False, "CSV 缺失")
            continue
        with io.open(csv_path, encoding="utf-8-sig", newline="") as f:
            csv_all = list(csv.reader(f))
            csv_header = csv_all[0] if csv_all else []
            csv_rows = csv_all[1:]
        # 不依赖中文表头：固定第二列就是单词；CSV 只用于人工查看，JSON 是权威来源。
        csv_words = [(r[1] or "").strip().lower() for r in csv_rows if len(r) > 1]
        json_words = [r["word"].strip().lower() for r in rows]
        check("%s CSV 与 JSON 同源" % deck, len(csv_words) == len(json_words) and set(csv_words) == set(json_words),
              "CSV=%d JSON=%d" % (len(csv_words), len(json_words)))
        expected_header = {
            "words": ["序号", "单词", "核心释义", "考查形式", "背诵优先级"],
            "insurance": ["序号", "单词", "核心释义", "考查形式", "补漏优先级", "覆盖", "英一覆盖", "加权覆盖", "优先级分数"],
        }[deck]
        header = csv_header
        check("%s CSV 表头完整" % deck, header == expected_header, str(header))

        if deck == "insurance":
            missing_score = [r["word"] for r in rows if "priority_score" not in r]
            bad_weight = [r["word"] for r in rows if r.get("en1_coverage", 0) > 0 and r.get("weighted_coverage", 0) == 0]
            check("insurance 优先级分数完整", not missing_score, str(missing_score[:5]))
            check("insurance 英一覆盖计入加权", not bad_weight, str(bad_weight[:5]))


# ---------- 浏览器内行为测试 ----------
BROWSER_SUITE = r"""
<script>
window.addEventListener('error', e => { try { document.title = 'RESULT:' + JSON.stringify({ error: String((e.error && e.error.stack) || e.message || e.error) }); } catch {} });
function fire(card, type, x, y) {
  const t = new Touch({ identifier: 1, target: card, clientX: x, clientY: y,
                        pageX: x, pageY: y, screenX: x, screenY: y });
  card.dispatchEvent(new TouchEvent(type, {
    touches: type === 'touchend' ? [] : [t],
    targetTouches: type === 'touchend' ? [] : [t],
    changedTouches: [t], bubbles: true, cancelable: true
  }));
}
function tap(card) {
  const t = new Touch({ identifier: 9, target: card, clientX: 200, clientY: 400,
                        pageX: 200, pageY: 400, screenX: 200, screenY: 200 });
  card.dispatchEvent(new TouchEvent('touchstart', { touches: [t], targetTouches: [t], changedTouches: [t], bubbles: true, cancelable: true }));
  card.dispatchEvent(new TouchEvent('touchend', { touches: [], targetTouches: [], changedTouches: [t], bubbles: true, cancelable: true }));
}
function tapEl(el) {
  const t = new Touch({ identifier: 11, target: el, clientX: 200, clientY: 400,
                        pageX: 200, pageY: 400, screenX: 200, screenY: 200 });
  el.dispatchEvent(new TouchEvent('touchstart', { touches: [t], targetTouches: [t], changedTouches: [t], bubbles: true, cancelable: true }));
  el.dispatchEvent(new TouchEvent('touchend', { touches: [], targetTouches: [], changedTouches: [t], bubbles: true, cancelable: true }));
}
function swipe(card, x1, x2) {
  fire(card, 'touchstart', x1, 400);
  fire(card, 'touchmove', (x1 + x2) / 2, 401);
  fire(card, 'touchmove', x2, 402);
  fire(card, 'touchend', x2, 402);
}
setTimeout(function () {
  const out = {};
  // 页面加载后到这里还没切过库，此时缓存里应该只有首屏真正用到的那一个词库
  out.lazy_cached_before = Object.keys(_deckCache).sort().join(',');
  out.all_words_lazy_at_boot = allWordsCache === null;
  try {
    const card = document.getElementById('card');
    const mean = document.getElementById('meaning');
    const vis = () => !mean.classList.contains('meaning-placeholder');

    // A. 翻面
    out.flip_init = vis();
    tap(card); out.flip_1 = vis();
    tap(card); out.flip_2 = vis();

    // B. 翻词自动收起
    revealed = true; renderStudy();
    navigate(1);
    out.flip_after_next = vis();

    // C. 左滑认识 + 撤销
    const w = queue[idx];
    swipe(card, 300, 140);
    setTimeout(function () {
      out.left_mastered = !!(state[w.word] || {}).mastered;
      out.left_due = ((state[w.word] || {}).due || 0) > Date.now();
      // 滑完卡片必须完全归位：晚到的 rAF 不能把位移和透明度又写回去
      out.swipe_settled = swipeTrack.style.transform === '' && card.style.opacity === ''
        && !card.classList.contains('swipe-ok');
      out.undo_visible = !document.getElementById('undoBar').classList.contains('hidden');
      document.getElementById('undoBtn').click();
      setTimeout(function () {
        out.undo_cleared = !(state[w.word] || {}).mastered;
        out.undo_back = document.getElementById('word').textContent === w.word;

        // D. 右滑权重
        const w2 = queue[idx];
        swipe(card, 100, 260);
        setTimeout(function () {
          out.right_same = document.getElementById('word').textContent === w2.word;
          out.right_weight = ((state[w2.word] || {}).w || 0) >= 1;
          out.weight_badge = !document.getElementById('weightBadge').classList.contains('hidden');
          // 右滑是弹回：位移和透明度要立刻复位，红色边框提示会再留一会儿
          out.right_settled = swipeTrack.style.transform === '' && card.style.opacity === '';
          const shownWeight = Number(document.getElementById('wordId').textContent);
          out.composite_weight = Number.isFinite(shownWeight)
            && Math.abs(shownWeight - displayWeightOf(w2)) < 0.001;
          out.unique_weights = new Set(DECKS.core.words.map(w => w.weight)).size === DECKS.core.words.length;

          // E. 词库章节记忆
          gotoChapter(1);
          const ch = curChapter;
          switchDeck('derivative');
          switchDeck('core');
          out.deck_chapter = curChapter === ch;

          // F. 进度按词恢复
          const target = queue[Math.min(3, queue.length - 1)];
          const key = chapterKey(curChapter);
          chapterData[key] = { order: queue.map(x => x.word), pos: 3, posWord: target.word };
          loadChapter(curChapter);
          out.resume_ok = queue[idx] && queue[idx].word === target.word;
          // G. 默认顺序稳定，只有手动打乱才变
          const k0 = chapterKey(0);
          delete chapterData[k0];
          loadChapter(0);
          const ord1 = queue.slice(0, 15).map(x => x.word).join();
          delete chapterData[k0];
          loadChapter(0);
          out.order_stable = ord1.length > 0 && ord1 === queue.slice(0, 15).map(x => x.word).join();
          loadChapter(0, 'shuffle');
          out.order_shuffled = ord1 !== queue.slice(0, 15).map(x => x.word).join();
          loadChapter(0, 'natural');
          out.order_restored = ord1 === queue.slice(0, 15).map(x => x.word).join();

          const orderBeforeConfirm = queue.map(x => x.word).join();
          const prompts = [];
          const originalConfirm = window.confirm;
          window.confirm = msg => { prompts.push(msg); return false; };
          document.getElementById('shuffleChapter').click();
          out.shuffle_confirm_cancel = prompts.length === 1 && queue.map(x => x.word).join() === orderBeforeConfirm;
          document.getElementById('restoreOrder').click();
          out.restore_confirm_cancel = prompts.length === 2 && queue.map(x => x.word).join() === orderBeforeConfirm;
          out.confirm_messages = prompts.length === 2;
          window.confirm = originalConfirm;
          delete chapterData[k0];

          // H. 点红点减权重
          const w3 = queue[idx];
          state[w3.word] = { w: 2, mastered: false, seen: 1 };
          renderStudy();
          document.getElementById('weightBadge').click();
          out.weight_down = (state[w3.word].w === 1);
          out.weight_badge_val = document.getElementById('weightBadge').textContent === '1';
          delete state[w3.word];
          renderStudy();

          // I. 已认识库有词，右滑恢复
          switchDeck('core');
          const mw = queue[idx];
          state[mw.word] = { w: 0, mastered: true, seen: 1 };
          save(LS_STATE, state);
          switchDeck('mastered');
          out.mastered_has_words = queue.length > 0;
          const mv = queue[0];
          restoreMastered(mv);
          out.mastered_restored = state[mv.word] && state[mv.word].mastered === false;
          switchDeck('core');

          // J. 跨章翻页：本章末词按下一个 → 下一章首词
          gotoChapter(0);
          idx = queue.length - 1;
          renderStudy();
          navigate(1);
          out.cross_next = curChapter === 1 && idx === 0;
          navigate(-1);
          out.cross_prev = curChapter === 0 && idx === queue.length - 1;

          // K. 点角标不触发翻面
          const visNow = vis();
          tapEl(document.querySelector('.badges .weight-badge') || document.querySelector('.badges .priority'));
          out.badge_no_flip = vis() === visNow;

          // K2. 等级徽章只显示单字母；长按详情里词典默认展开，不用再点一次
          out.priority_letter = /^[SABC]$/.test(document.getElementById('priorityBadge').textContent);
          openDetail(queue[idx]);
          out.dict_open_default = document.getElementById('detailDictBox').open === true;
          out.detail_shown = !document.getElementById('detailMask').classList.contains('hidden');
          closeDetail();
          out.detail_hidden = document.getElementById('detailMask').classList.contains('hidden');

          // K3. 统计口径：待学 = 总词数 - 学过，学过但没掌握的词不能还算「待学」
          out.stat_total = Number(document.getElementById('sTotal').textContent);
          out.stat_learned = Number(document.getElementById('sLearned').textContent);
          out.stat_due = Number(document.getElementById('sDue').textContent);
          out.stat_due_ok = out.stat_due === out.stat_total - out.stat_learned;

          // K4. 图标跟着账号走：要进快照，且不能被「从没设过图标的游客端」洗成默认
          const presetIcon = { kind: 'preset', id: 'moon' };
          const keptIcon = conf.icon, keptIconAt = conf.iconAt;
          conf.icon = presetIcon; conf.iconAt = 1;
          out.snapshot_has_icon = JSON.stringify(snapshot().conf.icon) === JSON.stringify(presetIcon);
          const iconMerged = mergeConf(
            { deck: 'core', progressAt: 1, icon: presetIcon, iconAt: 1 },
            { deck: 'core', progressAt: 999999, icon: null, iconAt: 0 },
            {}, {}, 0, 0);
          out.merge_icon_kept = !!iconMerged.icon && iconMerged.icon.id === 'moon';
          conf.icon = keptIcon; conf.iconAt = keptIconAt;

          // L. 从单词上起手的触摸不会被吞（否则滑动判定的 touchend 丢失）
          let cardGotTouchEnd = false;
          card.addEventListener('touchend', () => { cardGotTouchEnd = true; }, { once: true });
          const wordEl = document.getElementById('word');
          fire(wordEl, 'touchstart', 300, 400);
          fire(wordEl, 'touchend', 300, 400);
          out.word_touchend_reaches_card = cardGotTouchEnd;

          // N. 词库惰性解析：同一库只解析一次，切到别的库才解析
          const words1 = deckJson('words'), words2 = deckJson('words');
          out.lazy_same_ref = words1 === words2;
          out.lazy_words_count = words1.length;
          out.lazy_insurance_count = deckJson('insurance').length;
          out.lazy_after_has_insurance = 'insurance' in _deckCache;
          const metaBefore = document.getElementById('deckMeta').textContent;
          switchDeck('insurance');
          out.deck_meta_insurance = document.getElementById('deckMeta').textContent;
          switchDeck('core');
          out.deck_meta_core = document.getElementById('deckMeta').textContent;
          out.deck_meta_restored = document.getElementById('deckMeta').textContent === metaBefore;
          out.all_words_count = allWords().length;
          out.all_words_ready = allWordsCache !== null;
          out.first_card_marked = typeof window.__firstCardAt === 'number';
          const firstWord = words1[0].word;
          out.word_location = (wordLocation().get(firstWord) || {}).deck;

          // O. 翻卡/切词只改文本和属性，不重建 DOM（重建会让长列表卡顿）
          // 点开释义时单词和释义的纵坐标都不能动：卡片是 flex-start 锚定的，
          // 换成居中会把整块内容重新居中，单词就会往上跳。
          const wordBox = document.getElementById('word').getBoundingClientRect();
          const meaningBox = document.getElementById('meaning').getBoundingClientRect();
          const nodesBeforeFlip = document.querySelectorAll('*').length;
          toggleMeaning();
          out.word_shift = Math.round(document.getElementById('word').getBoundingClientRect().top - wordBox.top);
          out.meaning_shift = Math.round(document.getElementById('meaning').getBoundingClientRect().top - meaningBox.top);
          out.flip_node_delta = document.querySelectorAll('*').length - nodesBeforeFlip;
          toggleMeaning();
          const nodesBeforeNext = document.querySelectorAll('*').length;
          navigate(1);
          out.navigate_node_delta = document.querySelectorAll('*').length - nodesBeforeNext;

          // P. 已认识库：右滑恢复后要停在同一位置，不能跳回本章第一个词
          switchDeck('mastered');
          if (queue.length >= 4) {
            idx = 2; renderStudy();
            const lenBefore = queue.length;
            const nextWord = queue[3].word;
            restoreMastered(queue[idx]);
            out.restore_len_minus_one = queue.length === lenBefore - 1;
            out.restore_on_next_word = document.getElementById('word').textContent === nextWord;
          } else {
            out.restore_len_minus_one = true;
            out.restore_on_next_word = true;
          }
          switchDeck('core');

          // Q. 删除靠墓碑表达：一端清空后，另一端的旧词不能被拼回来
          const nowMs = Date.now();
          const snapReset = {
            state: { alpha: tombstone(nowMs - 1000), beta: tombstone(nowMs - 900) },
            chapterData: {}, daily: {}, conf: {},
          };
          const snapOld = {
            state: { alpha: { mastered: true, t: 1 }, beta: { mastered: true, t: 1 } },
            chapterData: {}, daily: {}, conf: {},
          };
          const resetMerged = mergeSnapshots(snapOld, snapReset).state;
          out.merge_tombstone_wins = !!resetMerged.alpha && resetMerged.alpha.del === 1
            && !!resetMerged.beta && resetMerged.beta.del === 1;
          // 删除与更新的先后由 t 决定：删了之后重新背的词要能复活
          out.merge_delete_beats_older = mergeState({ beta: { mastered: true, t: 5 } }, { beta: tombstone(50) }).beta.del === 1;
          out.merge_relearn_beats_delete = mergeState({ beta: { mastered: true, t: 80 } }, { beta: tombstone(50) }).beta.mastered === true;
          // 过老的墓碑会被清掉，否则 payload 永远被删除记录撑大
          out.merge_tombstone_pruned = !('beta' in pruneTombstones(
            { beta: tombstone(nowMs - 500 * 864e5) }, nowMs));
          // 清空全部：云端独有的键只有服务端知道，必须由服务端补墓碑
          const resetAt = nowMs - 2000;
          const covered = tombstoneAll(
            { state: { aa: { t: 1 }, bb: { t: 1 } }, chapterData: { 'core:0': { t: 1 } }, daily: {}, conf: {} },
            resetAt);
          out.tombstone_all_covers_cloud = covered.state.aa.del === 1 && covered.state.bb.del === 1
            && covered.chapterData['core:0'].del === 1;
          // 清空之后马上又背的词：比 reset fence 新的客户端记录必须优先。
          const resetPayload = {
            state: { aa: { mastered: true, t: nowMs - 1000 } }, chapterData: {}, daily: {}, conf: {},
          };
          const resetMerge = preferPayload(mergeSnapshots(resetPayload, covered), resetPayload);
          out.reset_prefers_client = resetMerge.state.aa.mastered === true && resetMerge.state.bb.del === 1;
          // 反向时间线：客户端旧墓碑不能覆盖另一台设备在 reset 后写下的 live 记录。
          const protectedMerge = preferPayload(
            mergeSnapshots({ state: { aa: tombstone(nowMs - 3000) }, chapterData: {}, daily: {}, conf: {} },
              { state: { aa: { mastered: true, t: nowMs } }, chapterData: {}, daily: {}, conf: {} }),
            { state: { aa: tombstone(nowMs - 3000) }, chapterData: {}, daily: {}, conf: {} });
          out.merge_preserves_post_reset_live = protectedMerge.state.aa.mastered === true;
          // __proto__ 键不能改掉结果对象的原型
          const polluted = mergeState(JSON.parse('{"__proto__":{"ghost":1},"alpha":{"t":1}}'), {});
          out.merge_no_proto_pollution = !('ghost' in polluted)
            && Object.getPrototypeOf(polluted) === Object.prototype;
          // 快照只写非默认字段，避免 payload 逼近上限
          const stateBackup = state;
          state = { zzz: { w: 0, mastered: false, seen: 0, t: 0, due: 0 } };
          const slimSnap = snapshot();
          state = stateBackup;
          out.snapshot_slim = !!slimSnap.state.zzz && Object.keys(slimSnap.state.zzz).length === 0;
          // 墓碑记录被重新写入进度时必须变回活记录，否则删除标记会跟着新数据上传
          state = { yyy: tombstone(1) };
          const revived = liveEntry('yyy');
          const liveOk = !revived.del && revived.w === 0;
          state = stateBackup;
          out.live_entry_revives = liveOk;
          const posOld = {
            state: {}, chapterData: { 'core:0': { order: ['state'], t: 10, pos: 0 } },
            conf: { deck: 'core', chapter: 0, deckChapter: { core: 0 }, progressAt: 10 },
          };
          const posNew = {
            state: {}, chapterData: { 'derivative:0': { order: ['investigation', 'analysis'], t: 20, pos: 1 } },
            conf: { deck: 'derivative', chapter: 0, deckChapter: { derivative: 0 }, progressAt: 20 },
          };
          const posMerged = mergeSnapshots(posOld, posNew);
          out.merge_position_latest = posMerged.conf.deck === 'derivative'
            && posMerged.chapterData['derivative:0'].order[0] === 'investigation';

          // S. 学习节奏：每日过卡计数、新掌握计数、连续天数、跨端合并
          const todayK = dayKey(Date.now());
          const sBefore = (daily[todayK] || {}).s || 0;
          const mBefore = (daily[todayK] || {}).m || 0;
          bumpDaily(false, false);
          out.daily_bump = ((daily[todayK] || {}).s || 0) === sBefore + 1;
          bumpDaily(true, true);
          const recNow = daily[todayK] || {};
          out.daily_master_bump = recNow.m === mBefore + 1 && recNow.s === sBefore + 2;
          const dk = offset => dayKey(todayTs() - offset * DAY);
          const fakeDaily = {};
          fakeDaily[dk(0)] = { s: 1 }; fakeDaily[dk(1)] = { s: 2 }; fakeDaily[dk(2)] = { s: 3 };
          out.streak_three = streakDays(fakeDaily) === 3;
          const brokenDaily = {};
          brokenDaily[dk(0)] = { s: 1 }; brokenDaily[dk(2)] = { s: 3 };
          out.streak_broken = streakDays(brokenDaily) === 1;
          const yesterdayOnly = {};
          yesterdayOnly[dk(1)] = { s: 2 }; yesterdayOnly[dk(2)] = { s: 1 };
          out.streak_yesterday = streakDays(yesterdayOnly) === 2;
          const mergedD = mergeDaily(
            { [dk(0)]: { s: 5, m: 1 } },
            { [dk(0)]: { s: 3, m: 2 }, [dk(1)]: { s: 1, m: 0 } });
          out.merge_daily_max = mergedD[dk(0)].s === 5 && mergedD[dk(0)].m === 2 && mergedD[dk(1)].s === 1;
          out.snapshot_has_daily = !!snapshot().daily;
          out.daily_scoped = typeof scopedKey(LS_DAILY) === 'string' && SCOPED_KEYS.has(LS_DAILY);
          // 撤销把当天计数减掉之后，云端较旧的大值不能再把它顶回来
          out.merge_daily_newer_t = mergeDaily(
            { [dk(0)]: { s: 5, m: 1, t: 100 } },
            { [dk(0)]: { s: 2, m: 0, t: 200 } })[dk(0)].s === 2;
          // 撤销要把 daily 一起回滚，否则误滑一次会永久多算
          const undoBase = (daily[dayKey(Date.now())] || {}).s || 0;
          if (queue[idx]) {
            mark(queue[idx], true);
            const afterMark = (daily[dayKey(Date.now())] || {}).s || 0;
            doUndo();
            const afterUndo = (daily[dayKey(Date.now())] || {}).s || 0;
            out.undo_rolls_daily = afterMark === undoBase + 1 && afterUndo === undoBase;
          } else {
            out.undo_rolls_daily = true;
          }
          switchView('Stat');
          out.rhythm_rendered = document.querySelectorAll('#sWeek .week-day').length === 7
            && document.getElementById('sStreak').textContent !== ''
            && !!document.querySelector('#sWeek .week-day.today');
          switchView('Study');

          // R. 桌面鼠标点卡片翻面；触摸结束后补发的合成 click 不能多翻一次
          const cardEl = document.getElementById('card');
          const meanEl = document.getElementById('meaning');
          const meaningShown = () => !meanEl.classList.contains('meaning-placeholder');
          const beforeClick = meaningShown();
          // 前面的手势测试刚触发过 touchend；把时间窗标记清零，等价于「等过了 800ms」
          lastCardTouchAt = 0;
          cardEl.dispatchEvent(new MouseEvent('click', { bubbles: true }));
          out.desktop_click_flips = meaningShown() !== beforeClick;
          const afterTouchFlip = meaningShown();
          fire(cardEl, 'touchend', 200, 400);
          cardEl.dispatchEvent(new MouseEvent('click', { bubbles: true }));
          out.touch_synth_click_ignored = meaningShown() === afterTouchFlip;

          // M. 词表首屏只渲染一页，避免移动端一次创建上千个节点
          switchView('List');
          out.list_first_page = document.querySelectorAll('#wordList li').length === 100;
          const moreBtn = document.querySelector('.list-more');
          out.list_has_more = !!moreBtn;
          if (moreBtn) moreBtn.click();
          out.list_load_more = document.querySelectorAll('#wordList li').length === 200;
          switchView('Study');

          // M. 自主更换图标（默认 Logo + 登录态 + 内置图标 + 自定义图片 + 恢复）
          const iconBackup = conf.icon;
          const authBackup = authUser;
          authUser = 'tester';
          conf.icon = null;
          renderAuth(); renderIconSettings();
          out.icon_login_logo = !!document.querySelector('#accountAvatar svg')
            && !document.querySelector('#accountAvatar img')
            && document.getElementById('accountBtn').classList.contains('online')
            && document.getElementById('iconCurrentName').textContent === '默认 Logo'
            && !!document.querySelector('.icon-choice.active');
          authUser = authBackup;
          conf.icon = { kind: 'preset', id: 'book' };
          renderAuth(); renderIconSettings(); syncFavicon(currentIcon());
          out.icon_preset = !!document.querySelector('#accountAvatar img')
            && !!document.querySelector('.icon-choice.active')
            && document.getElementById('iconCurrentName').textContent === '书本'
            && document.getElementById('appFavicon').href.startsWith('data:image/svg+xml');
          conf.icon = { kind: 'image', data: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZQmcAAAAASUVORK5CYII=' };
          renderAuth(); renderIconSettings();
          out.icon_custom = !!document.querySelector('#accountAvatar img')
            && document.getElementById('iconCurrentName').textContent.startsWith('自定义');
          conf.icon = iconBackup;
          renderAuth(); renderIconSettings(); syncFavicon(currentIcon());
          out.icon_restore = true;

          // N. 顶栏单行：Logo + 词库下拉框 + 词数 + 页签
          const deckBackup = activeDeck;
          switchDeck('derivative');
          out.header_compact = !!document.querySelector('header #deckSelect')
            && !!document.querySelector('header #deckMeta')
            && !document.querySelector('.deck-bar')
            && !document.querySelector('header .brand')
            && !document.querySelector('.deck-label');
          out.header_deck_count = document.getElementById('deckSelect').value === 'derivative'
            && document.getElementById('deckMeta').textContent === DECKS.derivative.words.length + ' 词';
          switchDeck(deckBackup);

          // O. 鼠标滚轮上下翻词
          switchDeck('core');
          loadChapter(0, 'natural');
          idx = 0;
          renderStudy();
          const wheelStart = queue[idx].word;
          const wheelDownEvent = new WheelEvent('wheel', { deltaY: 120, bubbles: true, cancelable: true });
          card.dispatchEvent(wheelDownEvent);
          out.wheel_next = wheelDownEvent.defaultPrevented && queue[idx].word !== wheelStart;
          wheelLockedUntil = 0;
          const wheelUpEvent = new WheelEvent('wheel', { deltaY: -120, bubbles: true, cancelable: true });
          card.dispatchEvent(wheelUpEvent);
          out.wheel_prev = wheelUpEvent.defaultPrevented && queue[idx].word === wheelStart;

          document.title = 'RESULT:' + JSON.stringify(out);
        }, 200);
      }, 150);
    }, 250);
  } catch (e) {
    document.title = 'RESULT:' + JSON.stringify({ error: e.message });
  }
}, 1400);
</script>
"""


def web_browser_checks():
    """Serve deploy/ like production and verify the split first-load path."""
    deploy = os.path.join(ROOT, "deploy")
    index_path = os.path.join(deploy, "index.html")
    if not os.path.exists(index_path):
        check("网页版首次加载测试", False, "deploy/index.html 不存在")
        return
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=deploy, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    probe_path = os.path.join(deploy, "_webcheck.html")
    profile = tempfile.mkdtemp(prefix="ky-webcheck-")
    try:
        html = io.open(index_path, encoding="utf-8").read()
        probe = r'''
<script>
setTimeout(async function(){
  const out = {};
  try {
    out.web_mode = WEB_MODE;
    out.first_card = Math.round(window.__firstCardAt || 0);
    out.boot_word = document.getElementById('word').textContent;
    out.boot_meta = document.getElementById('deckMeta').textContent;
    out.boot_options = document.getElementById('chapterSelect').options.length;
    out.boot_queue = queue.length;
    out.partial_len = deckJson('words').length;
    // 内嵌词库只有几十个时，分母必须按整章显示，不能露出「只有 40 个」
    const fullWords = _deckCache.words;
    _deckReady.delete('words');
    _deckCache.words = fullWords.slice(0, 40);
    queue = chapterSlice(0).slice();
    idx = 0;
    renderStudy();
    out.partial_denominator = document.getElementById('position').textContent;
    out.partial_bar_max = document.getElementById('progressBar').max;
    // Partial first shard: saved word #80 must not be replaced by word #1.
    const resumeFull = fullWords;
    const resumeTarget = resumeFull[80].word;
    const resumeOrder = resumeFull.slice(0, 200).map(x => x.word);
    _deckReady.delete('words');
    _deckCache.words = resumeFull.slice(0, 40);
    chapterData['core:0'] = { order: resumeOrder, pos: 80, posWord: resumeTarget };
    curChapter = 0;
    loadChapter(0);
    out.partial_resume_pending = pendingSeek && pendingSeek.word;
    out.partial_resume_loading = studyLoading;
    out.partial_resume_word = document.getElementById('word').textContent;
    out.partial_resume_stays_loading = !!(pendingSeek && pendingSeek.word === resumeTarget && studyLoading && document.getElementById('word').textContent !== resumeFull[0].word);
    _deckCache.words = resumeFull;
    _deckReady.add('words');
    _deckCache.words = fullWords;
    _deckReady.add('words');
    chapterData['core:0'] = { order: resumeOrder, pos: 80, posWord: resumeTarget };
    loadChapter(0);
    out.partial_resume_after_fill = !!(queue[idx] && queue[idx].word === resumeTarget);
    loadChapter(curChapter, undefined, 0);

    // 拖动进度条：拖动中不朗读，松手必须立刻读出新目标词，不能等用户再去点喇叭
    document.dispatchEvent(new Event('touchstart'));
    const bar = document.getElementById('progressBar');
    const dragTarget = 2;
    bar.value = String(dragTarget);
    bar.dispatchEvent(new Event('input', { bubbles: true }));
    const dragWord = queue[dragTarget] && queue[dragTarget].word;
    out.drag_holding = dragging === true && lastSpoken !== dragWord;
    bar.dispatchEvent(new Event('pointerup', { bubbles: true }));
    out.drag_released = dragging === false;
    out.drag_spoken = !!dragWord && lastSpoken === dragWord;
    gotoChapter(1);
    await new Promise(function(r){ setTimeout(r, 1800); });
    out.chapter = curChapter;
    out.chapter_queue = queue.length;
    out.chapter_word = queue[0] && queue[0].word;
    switchView('List');
    await new Promise(function(r){ setTimeout(r, 1000); });
    out.list_count = document.querySelectorAll('#wordList li').length;
    await switchDeck('derivative');
    out.deriv_meta = document.getElementById('deckMeta').textContent;
    out.deriv_count = deckJson('derivatives').length;

    // —— 学习进度持久化 ——
    // 切库 + 跳章 + 翻词之后，词书/章节/章内位次必须同时落盘，
    // 否则刷新或登录同步时会跳回旧章。
    await switchDeck('core');
    await ensureDeckData('core');   // 第 2 章要整表，先等词库就绪
    gotoChapter(2);
    navigate(3);
    const savedConf = JSON.parse(localStorage.getItem('ky_conf_v1') || '{}');
    out.pos_deck = savedConf.deck;
    out.pos_chapter = savedConf.chapter;
    out.pos_deck_chapter = savedConf.deckChapter && savedConf.deckChapter.core;
    out.pos_resume = resumePosition();
    out.pos_idx = idx;
    out.pos_word = queue[idx] && queue[idx].word;
    // 每本词书各记各的章，来回切换不能互相带跑
    await switchDeck('derivative');
    out.deriv_chapter = curChapter;
    await switchDeck('core');
    out.back_chapter = curChapter;
    // 合并：本地位置更新时必须赢，而且 chapter 与 deckChapter 要一致
    const m = mergeConf(
      { deck: 'core', chapter: 4, deckChapter: { core: 1 }, progressAt: 900 },
      { deck: 'core', chapter: 1, deckChapter: { core: 1 }, progressAt: 100 }, {}, {});
    out.merge_chapter = m.chapter;
    out.merge_deck_chapter = m.deckChapter.core;
    // 登录：游客进度按时间并进账号，不能因为账号里有旧数据就整体丢弃
    localStorage.setItem('ky_words_v1@probe', JSON.stringify({ apple: { w: 3, t: 100, mastered: false } }));
    const guestProbe = {
      apple: { w: 3, t: 500, mastered: true }, banana: { w: 1, t: 400 },
    };
    if (typeof writeStateStorageForScope === 'function') writeStateStorageForScope(guestProbe, null);
    else localStorage.setItem('ky_words_v1', JSON.stringify(guestProbe));
    adoptGuestProgress('probe');
    const adopted = typeof readStateStoreForScope === 'function'
      ? readStateStoreForScope('probe', {})
      : JSON.parse(localStorage.getItem('ky_words_v1@probe') || '{}');
    out.adopt_apple_mastered = !!(adopted.apple && adopted.apple.mastered);
    out.adopt_banana = !!adopted.banana;
    out.adopt_generation_sharded = /^2:[a-z0-9-]+$/.test(localStorage.getItem('ky_words_v1#meta@probe') || '')
      && !localStorage.getItem('ky_words_v1@probe');

    // —— 学习节奏（每日统计） ——
    out.web_daily_scoped = SCOPED_KEYS.has('ky_daily_v1');
    out.web_snapshot_daily = !!(snapshot().daily && typeof snapshot().daily === 'object');
    localStorage.setItem('ky_daily_v1', JSON.stringify({ [dayKey(Date.now())]: { s: 4, m: 1 } }));
    localStorage.setItem('ky_daily_v1@probe', JSON.stringify({ [dayKey(Date.now())]: { s: 2, m: 2 } }));
    adoptGuestProgress('probe');
    const adoptedDaily = JSON.parse(localStorage.getItem('ky_daily_v1@probe') || '{}');
    const ad = adoptedDaily[dayKey(Date.now())] || {};
    out.web_daily_adopt = ad.s === 4 && ad.m === 2;
    // 同步合并后不能丢每日记录（用当天日期：合并结果会按 120 天窗口裁剪）
    const dkToday = dayKey(Date.now());
    const dailyMerged = mergeSnapshots(
      { state: {}, chapterData: {}, daily: { [dkToday]: { s: 3, m: 0 } }, conf: { forceAt: 0 } },
      { state: {}, chapterData: {}, daily: { [dkToday]: { s: 5, m: 2 } }, conf: { forceAt: 0 } });
    out.web_daily_merge = dailyMerged.daily[dkToday].s === 5 && dailyMerged.daily[dkToday].m === 2;
    // —— 云端快照与导入必须共用校验，且不能被畸形数据打崩 ——
    const future = Date.now() + 365 * 864e5;
    const cleanedState = validateStateStore({
      good: { w: 3, mastered: true, due: future, t: Date.now(), extra: 'drop' },
      bad: 'not-a-record', ['__proto__']: { mastered: true },
    }, Date.now());
    out.validate_state = cleanedState.good && cleanedState.good.w === 3
      && cleanedState.good.mastered === true && !('extra' in cleanedState.good) && !('bad' in cleanedState);
    const snapshotBefore = JSON.stringify({ state, chapterData, daily, conf, activeDeck, curChapter });
    applyingRemote = true;
    const applied = applySnapshot({
      state: { valid: { w: 1, t: Date.now() } },
      chapterData: { 'core:0': { order: ['valid'], pos: 0, t: Date.now() } },
      daily: { [dayKey(Date.now())]: { s: 1, m: 0, t: Date.now() } },
      conf: { deck: 'core', chapter: 0, deckChapter: { core: 0 }, progressAt: Date.now() },
    });
    applyingRemote = false;
    out.apply_snapshot = applied === true && !!state.valid && activeDeck === 'core' && curChapter === 0;
    const prepared = prepareImport({
      state: { imported: { w: 2, t: Date.now() } },
      chapterData: { 'core:0': { order: ['imported'], pos: 0, posWord: 'imported', t: Date.now() } },
      daily: { [dayKey(Date.now())]: { s: 2, m: 0, t: Date.now() } },
      conf: { deck: 'core', chapter: 0, deckChapter: { core: 0 }, progressAt: Date.now(), speak: false },
    });
    out.import_atomic = prepared.state.imported && prepared.state.valid
      && prepared.state.valid.del === 1 && prepared.chapterData['core:0'].posWord === 'imported'
      && prepared.conf.speak === false && prepared.conf.overwritePending === true;
    out.import_operation = prepared.conf.overwriteMode === 'import'
      && Number(prepared.conf.importStartedAt) > 0
      && /^[A-Za-z0-9._:-]{8,96}$/.test(prepared.conf.importOperationId || '');
    let importRejected = false;
    try { prepareImport({ state: [], chapterData: {}, daily: {}, conf: {} }); }
    catch { importRejected = true; }
    out.import_rejects_array = importRejected;
    const restored = JSON.parse(snapshotBefore);
    state = restored.state; chapterData = restored.chapterData; daily = restored.daily; conf = restored.conf;
    activeDeck = restored.activeDeck; curChapter = restored.curChapter;

    // 游客空间「清空过」留下的墓碑，登录时不能把账号里同样的词一起删掉
    localStorage.setItem('ky_words_v1@probe2', JSON.stringify({ cherry: { mastered: true, t: 900 } }));
    const guestProbe2 = { cherry: { del: 1, t: 1000 }, date: { w: 1, t: 800 } };
    if (typeof writeStateStorageForScope === 'function') writeStateStorageForScope(guestProbe2, null);
    else localStorage.setItem('ky_words_v1', JSON.stringify(guestProbe2));
    adoptGuestProgress('probe2');
    const adopted2 = typeof readStateStoreForScope === 'function'
      ? readStateStoreForScope('probe2', {})
      : JSON.parse(localStorage.getItem('ky_words_v1@probe2') || '{}');
    out.adopt_keeps_account_word = !!(adopted2.cherry && adopted2.cherry.mastered);
    out.adopt_still_merges_live = !!adopted2.date;
    out.adopt2_generation_sharded = /^2:[a-z0-9-]+$/.test(localStorage.getItem('ky_words_v1#meta@probe2') || '')
      && !localStorage.getItem('ky_words_v1@probe2');
    // 游客的「清空后待同步」标志也不能带进账号，否则登录会顺手清掉云端进度
    localStorage.setItem('ky_conf_v1', JSON.stringify({
      deck: 'core', overwritePending: true, overwriteMode: 'clear', resetAt: 1,
      serverFenceAt: 1, serverFenceMode: 'clear', serverFenceOperationId: 'guest-op',
      importStartedAt: 1, importOperationId: 'guest-import-op', progressAt: 999,
    }));
    adoptGuestProgress('probe3');
    const conf3 = JSON.parse(localStorage.getItem('ky_conf_v1@probe3') || '{}');
    out.adopt_drops_guest_reset = !conf3.overwritePending && !conf3.overwriteMode
      && !conf3.resetAt && !conf3.serverFenceAt && !conf3.serverFenceMode
      && !conf3.serverFenceOperationId && !conf3.importStartedAt && !conf3.importOperationId;
    const accountFence = {
      deck: 'core', progressAt: 5, overwritePending: true, overwriteMode: 'import',
      resetAt: 0, serverFenceAt: 123, serverFenceMode: 'import',
      serverFenceOperationId: 'account-op-123', importStartedAt: 120, importOperationId: 'account-import-123',
    };
    localStorage.setItem('ky_conf_v1@probe4', JSON.stringify(accountFence));
    localStorage.setItem('ky_conf_v1', JSON.stringify({
      deck: 'core', progressAt: 1000, overwritePending: true, overwriteMode: 'clear', resetAt: 900,
      serverFenceAt: 900, serverFenceMode: 'clear', serverFenceOperationId: 'guest-op-900',
      importStartedAt: 900, importOperationId: 'guest-import-900',
    }));
    adoptGuestProgress('probe4');
    const conf4 = JSON.parse(localStorage.getItem('ky_conf_v1@probe4') || '{}');
    out.adopt_preserves_account_fence = conf4.overwritePending === true
      && conf4.overwriteMode === 'import' && Number(conf4.resetAt) === 0
      && Number(conf4.serverFenceAt) === 123 && conf4.serverFenceMode === 'import'
      && conf4.serverFenceOperationId === 'account-op-123'
      && Number(conf4.importStartedAt) === 120 && conf4.importOperationId === 'account-import-123';

    chapterData['core:0'] = { order: ['alpha'], pos: 5, posWord: 'alpha', t: 1 };
    chapterData['core:1'] = { order: ['beta'], pos: 0, posWord: 'beta', t: 2 };
    activeDeck = 'core'; curChapter = 1; queue = [{ word: 'beta' }]; idx = 0;
    localStorage.setItem(LS_POS, JSON.stringify({ 'core:0': { pos: 5, posWord: 'alpha', t: 1 } }));
    savePos(true);
    const positionsAfter = JSON.parse(localStorage.getItem(LS_POS) || '{}');
    out.position_cross_tab_merge = positionsAfter['core:0'] && positionsAfter['core:0'].pos === 5
      && positionsAfter['core:0'].posWord === 'alpha'
      && positionsAfter['core:1'] && positionsAfter['core:1'].pos === 0;
  } catch (e) {
    out.error = e.stack || e.message;
  }
  document.title = 'RESULT:' + JSON.stringify(out);
}, 600);
</script>
'''
        io.open(probe_path, "w", encoding="utf-8").write(html.replace("</body>", probe + "</body>"))
        url = "http://127.0.0.1:%d/_webcheck.html" % port
        r = subprocess.run(
            [EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
             "--user-data-dir=" + profile, "--virtual-time-budget=20000", "--dump-dom", url],
            capture_output=True, timeout=120,
        )
        dom = r.stdout.decode("utf-8", "replace")
        i = dom.find("RESULT:")
        if i < 0:
            check("网页版首次加载测试", False, "未拿到浏览器结果")
            return
        raw = dom[i + 7:dom.find("</title>", i)]
        data = json.loads(raw)
        if "error" in data:
            check("网页版首次加载测试", False, data["error"][:160])
            return
        check("网页版进入按需加载模式", data.get("web_mode") is True)
        # 首屏内联的只有 40 词（静态检查已卡 <=50），但第一章必须补齐到整章 200，
        # 否则「第 1 / 40 个」这种缺词状态会一直挂着。补全靠后台拉全词库。
        check("网页首屏补齐整库", data.get("partial_len") == 1342, "实际=%s" % data.get("partial_len"))
        check("网页第一章整章 200 词", data.get("boot_queue") == 200, "实际=%s" % data.get("boot_queue"))
        check("内嵌词库时分母仍显示整章",
              data.get("partial_denominator") == "第 1 / 200 个" and data.get("partial_bar_max") == "200",
              "位置=%s 进度条=%s" % (data.get("partial_denominator"), data.get("partial_bar_max")))
        check("拖动进度条拖动中不朗读", data.get("drag_holding") is True, "实际=%s" % data.get("drag_holding"))
        check("拖动进度条松手后朗读新词",
              data.get("drag_released") is True and data.get("drag_spoken") is True,
              "松手=%s 朗读=%s" % (data.get("drag_released"), data.get("drag_spoken")))
        check("网页首卡快速出现", 0 < data.get("first_card", 0) < PERF_BUDGET_MS, "%sms" % data.get("first_card"))
        app_name = next((x for x in os.listdir(deploy) if re.fullmatch(r"app\.[0-9a-f]{12}\.js", x)), "")
        app_text = io.open(os.path.join(deploy, app_name), encoding="utf-8").read() if app_name else ""
        check("同步位置字段完整", all(x in app_text for x in ("progressAt", "chapter:Number(conf.chapter)", "mergeConf")), "同步页码/当前位置")
        check("网页首屏显示完整词数", data.get("boot_meta") == "1342 词", "实际=%s" % data.get("boot_meta"))
        check("网页章节总数完整", data.get("boot_options") == 7, "实际=%s" % data.get("boot_options"))
        check("网页切章加载成功", data.get("chapter") == 1 and data.get("chapter_queue", 0) > 0,
              "实际=%s/%s" % (data.get("chapter"), data.get("chapter_queue")))
        check("网页词表加载完整", data.get("list_count") == 100, "实际=%s" % data.get("list_count"))
        check("网页切库加载成功", data.get("deriv_meta") == "120 词" and data.get("deriv_count") == 120,
              "实际=%s/%s" % (data.get("deriv_meta"), data.get("deriv_count")))
        check("切章翻词后章节落盘", data.get("pos_chapter") == 2 and data.get("pos_deck") == "core",
              "章=%s 库=%s" % (data.get("pos_chapter"), data.get("pos_deck")))
        check("章号同时写进 deckChapter", data.get("pos_deck_chapter") == 2,
              "实际=%s" % data.get("pos_deck_chapter"))
        check("恢复位置与当前章节一致", data.get("pos_resume") == 2, "实际=%s" % data.get("pos_resume"))
        check("首屏 40 条时保留后半章恢复目标", data.get("partial_resume_stays_loading") is True, "pending=%s loading=%s word=%s" % (data.get("partial_resume_pending"), data.get("partial_resume_loading"), data.get("partial_resume_word")))
        check("后台补全后恢复后半章词", data.get("partial_resume_after_fill") is True)
        check("章内位次落盘", data.get("pos_idx") == 3, "实际=%s" % data.get("pos_idx"))
        check("切库各记各的章", data.get("deriv_chapter") == 0 and data.get("back_chapter") == 2,
              "派生=%s 回核心=%s" % (data.get("deriv_chapter"), data.get("back_chapter")))
        check("合并进度取更新的一端", data.get("merge_chapter") == 4 and data.get("merge_deck_chapter") == 4,
              "章=%s deckChapter=%s" % (data.get("merge_chapter"), data.get("merge_deck_chapter")))
        check("登录采纳游客进度", data.get("adopt_apple_mastered") is True and data.get("adopt_banana") is True,
              "apple=%s banana=%s" % (data.get("adopt_apple_mastered"), data.get("adopt_banana")))
        check("登录采纳游客进度写入 shard generation", data.get("adopt_generation_sharded") is True,
              "实际=%s" % data.get("adopt_generation_sharded"))
        check("每日节奏按账号隔离", data.get("web_daily_scoped") is True)
        check("每日节奏进入同步快照", data.get("web_snapshot_daily") is True)
        check("登录采纳游客每日节奏", data.get("web_daily_adopt") is True)
        check("每日节奏合并取较大值", data.get("web_daily_merge") is True)
        check("游客墓碑不删账号的词", data.get("adopt_keeps_account_word") is True,
              "实际=%s" % data.get("adopt_keeps_account_word"))
        check("游客有效进度仍然并入", data.get("adopt_still_merges_live") is True)
        check("旧账号进度迁移到 shard generation", data.get("adopt2_generation_sharded") is True,
              "实际=%s" % data.get("adopt2_generation_sharded"))
        check("游客清空标志不串账号", data.get("adopt_drops_guest_reset") is True)
        check("账号破坏性 fence 不被游客覆盖", data.get("adopt_preserves_account_fence") is True,
              "实际=%s" % data.get("adopt_preserves_account_fence"))
        check("云端快照校验生效", data.get("validate_state") is True)
        check("应用云端快照不报未定义函数", data.get("apply_snapshot") is True, "error=%s" % data.get("error"))
        check("导入事务保留墓碑并覆盖进度", data.get("import_atomic") is True)
        check("导入持久化稳定操作 ID", data.get("import_operation") is True)
        check("多标签位置只更新当前章节", data.get("position_cross_tab_merge") is True)
        check("导入拒绝畸形数组", data.get("import_rejects_array") is True)
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except Exception:
            server.kill()
        if os.path.exists(probe_path):
            os.remove(probe_path)
        shutil.rmtree(profile, ignore_errors=True)


def state_shard_behavior_checks():
    template = io.open(os.path.join(ROOT, "software", "template.html"), encoding="utf-8").read()
    storage_start = template.find("const SCOPED_KEYS")
    storage_end = template.find("const todayTs", storage_start)
    commit_start = template.find("function commitStores", storage_end)
    commit_end = template.find("function objectRecord", commit_start)
    savepos_start = template.find("function savePos", storage_end)
    savepos_end = template.find("function resumePosition", savepos_start)
    if min(storage_start, storage_end, commit_start, commit_end, savepos_start, savepos_end) < 0:
        check("state 分片行为测试可准备", False, "未找到 state 存储函数边界")
        return
    setup = r"""
const LS_STATE = 'ky_words_v1';
const LS_DAILY = 'ky_daily_v1';
const LS_CONF = 'ky_conf_v1';
const LS_POS = 'ky_pos_v1';
let authUser = null;
let state = {};
let conf = {};
let activeDeck = 'core';
let curChapter = 0;
let chapterData = {};
let idx = 0;
let queue = [];
function chapterKey(ch) { return activeDeck + ':' + ch; }
const emitted = [];
const bus = { emit(type) { emitted.push(type); } };
const storage = new Map();
const writeLog = [];
let failSet = null;
const localStorage = {
  getItem(key) { return storage.has(String(key)) ? storage.get(String(key)) : null; },
  setItem(key, value) {
    if (failSet && failSet(String(key))) {
      failSet = null;
      throw new Error('quota');
    }
    writeLog.push(String(key));
    storage.set(String(key), String(value));
  },
  removeItem(key) { storage.delete(String(key)); },
};
const warningEl = { classList: { remove() {} } };
const document = { getElementById() { return warningEl; } };
"""
    tail = r"""
function snapshotStorage() {
  return new Map([...storage.entries()].filter(([key]) => key.startsWith('ky_words_v1#')));
}
function changedStorageKeys(before, after) {
  const keys = new Set([...before.keys(), ...after.keys()]);
  return [...keys].filter(key => before.get(key) !== after.get(key)).sort();
}
const out = {};
out.shardCount = STATE_SHARD_COUNT;

const legacyGuest = {
  legacy: { mastered: true, t: 10 },
  apple: { w: 1, t: 11 },
};
localStorage.setItem('ky_words_v1', JSON.stringify(legacyGuest));
out.legacyFallback = readStateStoreForScope(null, {}).legacy && readStateStoreForScope(null, {}).legacy.mastered === true;
state = {
  legacy: legacyGuest.legacy,
  apple: legacyGuest.apple,
  banana: { mastered: true, t: 12 },
};
out.migrationWrite = saveStateRecord('banana');
const guestGeneration = stateMetaForScope(null);
out.generationCreated = /^[a-z0-9-]+$/.test(guestGeneration);
out.migratedRead = readStateStoreForScope(null, {}).banana && readStateStoreForScope(null, {}).banana.mastered === true;
out.legacyRemoved = localStorage.getItem('ky_words_v1') === null;
out.shardKeyExists = localStorage.getItem('ky_words_v1#' + guestGeneration + '-' + stateShardIndex('banana')) !== null;

const beforeSingle = snapshotStorage();
state.apple = { w: 9, t: 99, mastered: true };
out.singleWrite = saveStateRecord('apple');
const afterSingle = snapshotStorage();
const singleChanged = changedStorageKeys(beforeSingle, afterSingle);
out.singleChangedKeys = singleChanged.length;
out.singleChangedExpected = singleChanged.length === 1 && singleChanged[0] === ('ky_words_v1#' + guestGeneration + '-' + stateShardIndex('apple'));
out.singleReadBack = readStateStoreForScope(null, {}).apple && readStateStoreForScope(null, {}).apple.w === 9;

const beforeFailed = readStateStoreForScope(null, {});
failSet = key => key.startsWith('ky_words_v1#') && !key.includes('#meta') && !beforeSingle.has(key);
out.failedCommit = commitStores({ state: { shouldNotLand: { t: 1 } }, chapterData: {}, daily: {}, conf: {} });
out.failedMetaStable = stateMetaForScope(null) === guestGeneration;
out.failedReadStable = !readStateStoreForScope(null, {}).shouldNotLand && readStateStoreForScope(null, {}).apple.w === 9;

const imported = { imported: { mastered: true, t: 200 } };
const importedChapters = { 'core:0': { order: ['alpha', 'beta'], pos: 1, posWord: 'beta', t: 201 } };
out.importCommit = commitStores({ state: imported, chapterData: importedChapters, daily: {}, conf: {} });
const importGeneration = stateMetaForScope(null);
out.importGenerationSwitched = !!importGeneration && importGeneration !== guestGeneration;
out.importRead = readStateStoreForScope(null, {}).imported && !readStateStoreForScope(null, {}).apple;
out.oldGenerationCleaned = ![...storage.keys()].some(key => key.startsWith('ky_words_v1#' + guestGeneration + '-'));
const importedPos = JSON.parse(localStorage.getItem(LS_POS) || '{}');
out.importPosSynced = importedPos['core:0'] && importedPos['core:0'].pos === 1
  && importedPos['core:0'].posWord === 'beta' && !('order' in importedPos['core:0']);

out.clearCommit = commitStores({ state: {}, chapterData: {}, daily: {}, conf: {} });
const clearGeneration = stateMetaForScope(null);
out.clearGenerationSwitched = !!clearGeneration && clearGeneration !== importGeneration;
out.clearReadEmpty = Object.keys(readStateStoreForScope(null, {})).length === 0;
out.importGenerationCleaned = ![...storage.keys()].some(key => key.startsWith('ky_words_v1#' + importGeneration + '-'));
out.clearPosSynced = Object.keys(JSON.parse(localStorage.getItem(LS_POS) || '{}')).length === 0;

localStorage.setItem('ky_words_v1@alice', JSON.stringify({ legacyAlice: { mastered: true, t: 300 } }));
out.accountLegacyRead = readStateStoreForScope('alice', {}).legacyAlice && readStateStoreForScope('alice', {}).legacyAlice.mastered === true;
authUser = 'alice';
state = { aliceOnly: { mastered: true, t: 301 } };
out.aliceWrite = saveStateRecord('aliceOnly');
const aliceGeneration = stateMetaForScope('alice');
authUser = 'bob';
state = { bobOnly: { mastered: true, t: 302 } };
out.bobWrite = saveStateRecord('bobOnly');
const bobGeneration = stateMetaForScope('bob');
out.accountIsolation = !readStateStoreForScope('alice', {}).bobOnly
  && !readStateStoreForScope('bob', {}).aliceOnly
  && !!readStateStoreForScope('bob', {}).bobOnly;
out.accountKeysSeparated = !!aliceGeneration && !!bobGeneration
  && storage.has('ky_words_v1#meta@alice') && storage.has('ky_words_v1#meta@bob')
  && storage.has('ky_words_v1#' + aliceGeneration + '-' + stateShardIndex('aliceOnly') + '@alice')
  && storage.has('ky_words_v1#' + bobGeneration + '-' + stateShardIndex('bobOnly') + '@bob');

authUser = null;
activeDeck = 'core';
curChapter = 0;
chapterData = {
  'core:0': { order: ['alpha', 'beta', 'gamma'], pos: 0, posWord: 'alpha', t: 10 },
  'core:1': { order: ['delta', 'epsilon'], pos: 0, posWord: 'delta', t: 11 },
};
conf = { deck: 'core', chapter: 0, deckChapter: { core: 0 }, progressAt: 1 };
queue = [{ word: 'alpha' }, { word: 'beta' }, { word: 'gamma' }];
idx = 1;
const chapterBefore = JSON.stringify(chapterData);
localStorage.setItem('ky_chapter_v1', chapterBefore);
localStorage.setItem(LS_POS, JSON.stringify({ 'core:1': { pos: 1, t: 777, posWord: 'epsilon' } }));
writeLog.length = 0;
savePos(true);
out.posWriteKeys = writeLog.slice();
out.chapterDataNotRewritten = localStorage.getItem('ky_chapter_v1') === chapterBefore;
const posStore = JSON.parse(localStorage.getItem(LS_POS) || '{}');
out.posSmallRecord = posStore['core:0'] && posStore['core:0'].pos === 1
  && posStore['core:0'].posWord === 'beta' && !('order' in posStore['core:0'])
  && posStore['core:1'] && posStore['core:1'].pos === 1
  && posStore['core:1'].posWord === 'epsilon' && !('order' in posStore['core:1']);
out.posPreservesOtherChapter = posStore['core:1'] && posStore['core:1'].pos === 1
  && posStore['core:1'].t === 777;

const refreshBase = { 'core:0': { order: ['alpha', 'beta', 'gamma'], pos: 0, posWord: 'alpha', t: 1 } };
localStorage.setItem('ky_chapter_v1', JSON.stringify(refreshBase));
localStorage.setItem(LS_POS, JSON.stringify({ 'core:0': { pos: 2, posWord: 'gamma', t: 99 } }));
const refreshed = loadChapterStoreWithPositions(refreshBase);
out.refreshRestoresPosition = refreshed['core:0'].pos === 2
  && refreshed['core:0'].posWord === 'gamma' && refreshed['core:0'].t === 99
  && refreshed['core:0'].order.join(',') === 'alpha,beta,gamma';

storage.delete(LS_POS);
authUser = 'alice';
activeDeck = 'core';
curChapter = 0;
chapterData = { 'core:0': { order: ['alice'], pos: 0, posWord: 'alice', t: 1 } };
queue = [{ word: 'alice' }];
idx = 0;
savePos(false);
const alicePos = JSON.parse(localStorage.getItem(LS_POS + '@alice') || '{}');
authUser = 'bob';
chapterData = { 'core:0': { order: ['bob'], pos: 0, posWord: 'bob', t: 2 } };
queue = [{ word: 'bob' }];
idx = 0;
savePos(false);
const bobPos = JSON.parse(localStorage.getItem(LS_POS + '@bob') || '{}');
out.posAccountIsolation = alicePos['core:0'] && alicePos['core:0'].posWord === 'alice'
  && bobPos['core:0'] && bobPos['core:0'].posWord === 'bob'
  && !storage.has('ky_pos_v1');
console.log('RESULT:' + JSON.stringify(out));
"""
    source = setup + "\n" + template[storage_start:storage_end] + "\n" + template[commit_start:commit_end] + "\n" + template[savepos_start:savepos_end] + "\n" + tail
    data, proc = run_node_harness(source, timeout=120)
    if data is None:
        detail = harness_detail(proc)
        for name in ("旧 ky_words_v1 迁移到 generation shard", "单次 saveStateRecord 只改一个 shard", "导入/清空 generation 原子切换", "失败写入不切换 generation", "state 分片账号隔离", "翻词只写 ky_pos_v1 小键", "刷新从 ky_pos_v1 恢复位置", "导入/清空同步 positions", "positions 账号隔离"):
            check(name, False, detail)
        return
    check("旧 ky_words_v1 迁移到 generation shard",
          data.get("shardCount") == 64
          and data.get("legacyFallback") is True and data.get("migrationWrite") is True
          and data.get("generationCreated") is True and data.get("migratedRead") is True
          and data.get("legacyRemoved") is True and data.get("shardKeyExists") is True,
          json.dumps(data, ensure_ascii=False)[:700])
    check("单次 saveStateRecord 只改一个 shard",
          data.get("singleWrite") is True and data.get("singleChangedKeys") == 1
          and data.get("singleChangedExpected") is True and data.get("singleReadBack") is True,
          json.dumps(data, ensure_ascii=False)[:700])
    check("导入/清空 generation 原子切换",
          data.get("importCommit") is True and data.get("importGenerationSwitched") is True
          and data.get("importRead") is True and data.get("oldGenerationCleaned") is True
          and data.get("clearCommit") is True and data.get("clearGenerationSwitched") is True
          and data.get("clearReadEmpty") is True and data.get("importGenerationCleaned") is True,
          json.dumps(data, ensure_ascii=False)[:700])
    check("失败写入不切换 generation",
          data.get("failedCommit") is False and data.get("failedMetaStable") is True
          and data.get("failedReadStable") is True,
          json.dumps(data, ensure_ascii=False)[:700])
    check("state 分片账号隔离",
          data.get("accountLegacyRead") is True and data.get("aliceWrite") is True
          and data.get("bobWrite") is True and data.get("accountIsolation") is True
          and data.get("accountKeysSeparated") is True,
          json.dumps(data, ensure_ascii=False)[:700])
    check("翻词只写 ky_pos_v1 小键",
          data.get("posWriteKeys") == ["ky_pos_v1", "ky_conf_v1"]
          and data.get("chapterDataNotRewritten") is True
          and data.get("posSmallRecord") is True,
          json.dumps(data, ensure_ascii=False)[:700])
    check("刷新从 ky_pos_v1 恢复位置", data.get("refreshRestoresPosition") is True,
          json.dumps(data, ensure_ascii=False)[:700])
    check("导入/清空同步 positions",
          data.get("importPosSynced") is True and data.get("clearPosSynced") is True,
          json.dumps(data, ensure_ascii=False)[:700])
    check("positions 账号隔离", data.get("posAccountIsolation") is True,
          json.dumps(data, ensure_ascii=False)[:700])


def worker_audio_behavior_checks():
    try:
        worker_source = materialized_worker_source()
    except Exception as exc:
        check("Worker 音频行为测试可准备", False, str(exc))
        return
    script = r"""
import { pathToFileURL } from 'node:url';
globalThis.caches = { default: { match: async () => null, put: async () => {} } };
const { default: worker } = await import(pathToFileURL(process.env.KY_HARNESS_DIR + '/worker.mjs').href);
const makeFixed = () => new Response(new Uint8Array([73, 68, 51]), {
  status: 200,
  headers: { 'content-type': 'audio/mpeg', 'content-length': '3' },
});
const makeChunked = () => {
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(new Uint8Array([73, 68, 51]));
      controller.close();
    },
  });
  return new Response(stream, { status: 200, headers: { 'content-type': 'audio/mpeg' } });
};
globalThis.fetch = async target => String(target).includes('fanyi.baidu.com') ? makeFixed() : makeChunked();
const env = { ASSETS: { fetch: async () => new Response('') } };
async function audio(url) {
  const response = await worker.fetch(new Request(url), env, { waitUntil() {} });
  const body = await response.arrayBuffer();
  return {
    status: response.status,
    bytes: body.byteLength,
    type: response.headers.get('content-type') || '',
    text: response.ok ? '' : new TextDecoder().decode(body),
  };
}
const out = {
  zhV2: await audio('https://example.com/api/audio?lang=zh&v=2&word=hello'),
  chunked: await audio('https://example.com/api/audio?word=hello'),
};
console.log('RESULT:' + JSON.stringify(out));
"""
    data, proc = run_node_harness(script, {"worker.mjs": worker_source})
    if data is None:
        detail = harness_detail(proc)
        check("Worker 接受 zh v=2", False, detail)
        check("Worker 接受无 Content-Length 的 chunked 音频", False, detail)
        return
    zh = data.get("zhV2") or {}
    chunked = data.get("chunked") or {}
    check("Worker 接受 zh v=2",
          zh.get("status") == 200 and zh.get("bytes") == 3 and zh.get("type") == "audio/mpeg",
          json.dumps(zh, ensure_ascii=False))
    check("Worker 接受无 Content-Length 的 chunked 音频",
          chunked.get("status") == 200 and chunked.get("bytes") == 3 and chunked.get("type") == "audio/mpeg",
          json.dumps(chunked, ensure_ascii=False))


def frontend_api_behavior_checks():
    template = io.open(os.path.join(ROOT, "software", "template.html"), encoding="utf-8").read()
    start = template.find("function combinedAbortSignal")
    end = template.find("function commitStores", start)
    if start < 0 or end < 0:
        check("前端 API 行为测试可准备", False, "未找到 api 函数边界")
        return
    script = r"""
import fs from 'node:fs';
import vm from 'node:vm';
const template = fs.readFileSync('software/template.html', 'utf8');
const start = template.indexOf('function combinedAbortSignal');
const end = template.indexOf('function commitStores', start);
if (start < 0 || end < 0) throw new Error('api source missing');
const snippet = template.slice(start, end);
const context = {
  location: { protocol: 'https:' },
  navigator: { onLine: true },
  AbortController, AbortSignal, DOMException, Response, Headers, URL,
  setTimeout, clearTimeout, console,
  fetch: null,
};
vm.createContext(context);
vm.runInContext('let apiEpochController = null; function handleSessionExpired() {};\n' + snippet + '\nglobalThis.__api = api;', context);
const out = {};
context.fetch = async () => new Response('{"ok":true}', { status: 200 });
try {
  const value = await context.__api('/valid');
  out.valid = value && value.ok === true;
} catch (err) {
  out.valid = false;
  out.validError = String(err && err.message || err);
}
context.fetch = async () => new Response('{broken-json', { status: 200 });
try {
  const value = await context.__api('/bad-json');
  out.badJsonRejected = false;
  out.badJsonValue = value;
} catch (err) {
  out.badJsonRejected = true;
  out.badJsonError = String(err && err.message || err);
}
context.fetch = (_url, options) => new Promise((_resolve, reject) => {
  const signal = options && options.signal;
  const abort = () => reject(new DOMException('aborted', 'AbortError'));
  if (!signal) return;
  if (signal.aborted) abort();
  else signal.addEventListener('abort', abort, { once: true });
});
try {
  await context.__api('/slow', { timeout: 25 });
  out.timeoutRejected = false;
} catch (err) {
  out.timeoutRejected = true;
  out.timeoutError = String(err && err.message || err);
}
console.log('RESULT:' + JSON.stringify(out));
"""
    data, proc = run_node_harness(script)
    if data is None:
        detail = harness_detail(proc)
        check("前端 API 坏 JSON 必须失败", False, detail)
        check("前端 API 超时必须失败", False, detail)
        return
    check("前端 API 正常 JSON 可返回", data.get("valid") is True,
          json.dumps(data, ensure_ascii=False)[:500])
    check("前端 API 坏 JSON 必须失败", data.get("badJsonRejected") is True,
          json.dumps(data, ensure_ascii=False)[:500])
    check("前端 API 超时必须失败",
          data.get("timeoutRejected") is True and "超时" in str(data.get("timeoutError", "")),
          json.dumps(data, ensure_ascii=False)[:500])


def sw_cache_status_checks():
    source = io.open(os.path.join(ROOT, "software", "sw.template.js"), encoding="utf-8").read()
    source = source.replace("__BUILD_VERSION__", "test-build", 1)
    source = source.replace("__APP_ASSET__", "./app.test.js", 1)
    source = source.replace("__DATA_ASSETS__", "[]", 1)
    script = r"""
import { pathToFileURL } from 'node:url';
let listeners = {};
let failPut = false;
let networkCalls = 0;
const store = new Map();
const cache = {
  async match(request) {
    const hit = store.get(String(request.url));
    return hit ? hit.clone() : undefined;
  },
  async put(request, response) {
    if (failPut) throw new Error('quota');
    store.set(String(request.url), response.clone());
  },
  async delete(request) { return store.delete(String(request.url)); },
  async keys() { return [...store.keys()].map(url => new Request(url)); },
  async add(request) {
    const response = await fetch(request);
    if (!response.ok) throw new Error('add failed');
    store.set(String(request.url), response.clone());
  },
};
globalThis.self = {
  location: { origin: 'https://example.com' },
  addEventListener(type, fn) { listeners[type] = fn; },
  clients: { matchAll: async () => [], claim: async () => {} },
  skipWaiting: async () => {},
};
globalThis.caches = {
  open: async () => cache,
  keys: async () => [],
  delete: async () => true,
};
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { storage: { estimate: async () => ({ usage: 0, quota: 1024 * 1024 * 1024 }) } } });
globalThis.fetch = async () => {
  networkCalls += 1;
  return new Response(new Uint8Array([73, 68, 51]), {
    status: 200,
    headers: { 'content-type': 'audio/mpeg', 'content-length': '3' },
  });
};
await import(pathToFileURL(process.env.KY_HARNESS_DIR + '/sw.mjs').href);
async function dispatch(url) {
  let responsePromise;
  const event = {
    request: new Request(url),
    respondWith(value) { responsePromise = Promise.resolve(value); },
    waitUntil() {},
  };
  listeners.fetch(event);
  if (!responsePromise) throw new Error('fetch listener did not respond');
  const response = await responsePromise;
  return {
    status: response.status,
    cache: response.headers.get('x-ky-cache'),
    type: response.headers.get('content-type'),
  };
}
const out = {};
out.stored = await dispatch('https://example.com/api/audio?word=alpha&offline=1');
out.hit = await dispatch('https://example.com/api/audio?word=alpha');
failPut = true;
out.storeFailed = await dispatch('https://example.com/api/audio?word=beta&offline=1');
out.networkCalls = networkCalls;

store.clear();
store.set('https://example.com/api/audio?word=zeta', new Response('zeta'));
store.set('https://example.com/api/audio?lang=zh&v=2&word=greeting', new Response('greeting'));
const sourceMessages = [];
const source = { postMessage(message) { sourceMessages.push(message); } };
async function query(data) {
  sourceMessages.length = 0;
  let task = Promise.resolve();
  listeners.message({
    data,
    source,
    waitUntil(value) { task = Promise.resolve(value); },
  });
  await task;
  if (!sourceMessages.length) throw new Error('snapshot response missing');
  return sourceMessages[0];
}
out.snapshot = await query({ type: 'ky:audio-cache-query', protocol: 1, requestId: 'q1', includeEntries: false });
out.snapshotWithEntries = await query({ type: 'ky:audio-cache-query', protocol: 1, requestId: 'q2', includeEntries: true });
console.log('RESULT:' + JSON.stringify(out));
"""
    data, proc = run_node_harness(script, {"sw.mjs": source})
    if data is None:
        detail = harness_detail(proc)
        for name in ("SW 缓存写入状态头", "SW 缓存命中状态头", "SW 缓存失败状态头"):
            check(name, False, detail)
        return
    check("SW 缓存写入状态头",
          (data.get("stored") or {}).get("cache") == "stored",
          json.dumps(data.get("stored"), ensure_ascii=False))
    check("SW 缓存命中状态头",
          (data.get("hit") or {}).get("cache") == "hit",
          json.dumps(data.get("hit"), ensure_ascii=False))
    check("SW 缓存失败状态头",
          (data.get("storeFailed") or {}).get("cache") == "store-failed",
          json.dumps(data.get("storeFailed"), ensure_ascii=False))
    snapshot = data.get("snapshot") or {}
    detailed = data.get("snapshotWithEntries") or {}
    check("SW snapshot query 返回完整快照",
          snapshot.get("type") == "ky:audio-cache-snapshot"
          and snapshot.get("protocol") == 1
          and snapshot.get("requestId") == "q1"
          and snapshot.get("complete") is True
          and snapshot.get("count") == 2
          and snapshot.get("markers") == ["en:zeta", "zh:greeting"]
          and "entries" not in snapshot
          and detailed.get("requestId") == "q2"
          and isinstance(detailed.get("entries"), list)
          and len(detailed.get("entries")) == 2,
          json.dumps({"snapshot": snapshot, "detailed": detailed}, ensure_ascii=False)[:800])


def page_offline_cache_checks():
    template = io.open(os.path.join(ROOT, "software", "template.html"), encoding="utf-8").read()
    audio_start = template.find("const AUDIO_CACHE_VERSION")
    audio_end = template.find("function refreshVoice", audio_start)
    run_start = template.find("async function runOfflineDownload", audio_end)
    auto_start = template.find("const AUTO_OFFLINE_KEY =", run_start)
    auto_end = template.find("function scheduleAutoOffline", auto_start)
    if min(audio_start, audio_end, run_start, auto_start, auto_end) < 0:
        check("离线缓存行为测试可准备", False, "未找到音频标记或自动下载函数边界")
        return
    run_end = auto_start
    setup = r"""
const storage = new Map();
const localStorage = {
  getItem(key) { return storage.has(String(key)) ? storage.get(String(key)) : null; },
  setItem(key, value) { storage.set(String(key), String(value)); },
  removeItem(key) { storage.delete(String(key)); },
};
const windowListeners = {};
const location = { protocol: 'file:' };
const window = {
  isSecureContext: true,
  addEventListener(type, fn) { windowListeners[type] = fn; },
};
let cacheKeys = [];
const fakeCache = {
  async match() { return undefined; },
  async put() {},
  async delete() { return true; },
  async keys() { return cacheKeys.slice(); },
  async add() {},
};
const caches = {
  async open() { return fakeCache; },
  async keys() { return []; },
  async delete() { return true; },
};
window.caches = caches;
function updateOfflineStatus() {}
let fakeTimer = 0;
function setTimeout() { return ++fakeTimer; }
function clearTimeout() {}
"""
    stubs = r"""
let offlineJob = null;
const offlinePermanent = new Set();
const OFFLINE_CONCURRENCY = 16;
const OFFLINE_PERMANENT_KEY = 'ky_audio_permanent_fail_v2';
const queue = [];
const DATA_META = { assets: { details: {} } };
let offlineWords = [];
const nodes = {
  offlineStart: { disabled: false },
  offlineStop: { classList: { add() {}, remove() {} } },
  offlineStat: { textContent: '' },
  zhVoiceStat: { textContent: '' },
};
function $(id) { return nodes[id] || (nodes[id] = { textContent: '', classList: { add() {}, remove() {} } }); }
async function offlineWordList() { return offlineWords; }
async function offlineZhTexts() { return []; }
function meaningForSpeech() { return ''; }
function warmChineseVoice() {}
function zhVoiceStatus() { return ''; }
function renderOfflineJob() {}
function responseIsPermanentAudioFailure() { return false; }
async function waitForServiceWorkerReady() {}
async function fetchOfflineAudio() {
  return new Response('audio', { status: 200, headers: { 'x-ky-cache': 'stored' } });
}
globalThis.fetch = async () => new Response('{}');
"""
    tests = r"""
const out = {};
replaceAudioMarkersFromStorage('["en:a","en:b"]');
localStorage.setItem(AUDIO_WORDS_KEY, '["en:a","en:b"]');
forgetAudio('en:b');
rememberAudio('en:c');
const externalMarkers = '["en:a","en:z"]';
localStorage.setItem(AUDIO_WORDS_KEY, externalMarkers);
replaceAudioMarkersFromStorage(externalMarkers);
flushAudioMarkers();
out.multiTab = [...audioCachedWords].sort().join(',');

replaceAudioMarkersFromStorage('["en:a","en:b","zh:gone"]');
localStorage.setItem(AUDIO_WORDS_KEY, '["en:a","en:b","zh:gone"]');
cacheKeys = [
  new Request('https://example.com/api/audio?word=a'),
  new Request('https://example.com/api/audio?lang=zh&word=greeting'),
];
markAutoOfflineDone(3);
const reconciled = await reconcileAudioCache();
out.reconciled = [...reconciled].sort().join(',');
out.reconcileClearsDone = readAutoOfflineDone() === null;

audioCachedWords = new Set();
audioMarkerBase = new Set();
audioMarkerAdds.clear();
audioMarkerRemoves.clear();
flushAudioMarkers();
localStorage.removeItem(AUTO_OFFLINE_KEY);
offlineWords = Array.from({ length: 801 }, (_, index) => 'word' + index);
await runOfflineDownload({ auto: true });
out.partialDone = localStorage.getItem(AUTO_OFFLINE_KEY);
await runOfflineDownload({ auto: true });
const done = readAutoOfflineDone();
out.finalDone = done && done.expected;
out.finalDisablesAuto = autoOfflineAllowed() === false;
console.log('RESULT:' + JSON.stringify(out));
"""
    source = setup + "\n" + template[audio_start:audio_end] + "\n" + template[auto_start:auto_end] + "\n" + stubs + "\n" + template[run_start:run_end] + "\n" + tests
    data, proc = run_node_harness(source, timeout=300)
    if data is None:
        detail = harness_detail(proc)
        for name in ("多标签音频 marker 同步", "缓存 reconcile 清理失效 marker", "auto-offline 分批未完成不写 done", "auto-offline 全部完成后写 done"):
            check(name, False, detail)
        return
    check("多标签音频 marker 同步", data.get("multiTab") == "en:a,en:c,en:z",
          "实际=%s" % data.get("multiTab"))
    check("缓存 reconcile 清理失效 marker", data.get("reconciled") == "en:a,zh:greeting",
          "实际=%s" % data.get("reconciled"))
    check("auto-offline 分批未完成不写 done", data.get("partialDone") is None,
          "实际=%s" % data.get("partialDone"))
    check("auto-offline 全部完成后写 done",
          data.get("finalDone") == 801 and data.get("finalDisablesAuto") is True,
          "done=%s allowed=%s" % (data.get("finalDone"), data.get("finalDisablesAuto")))


def worker_reset_import_checks():
    try:
        worker_source = materialized_worker_source()
    except Exception as exc:
        check("同步栅栏行为测试可准备", False, str(exc))
        return
    script = r"""
import { pathToFileURL } from 'node:url';
const { default: worker } = await import(pathToFileURL(process.env.KY_HARNESS_DIR + '/worker.mjs').href);
let remoteText = '{}';
let updatedAt = 100;
const db = {
  prepare(sql) {
    return {
      bind(...args) {
        return {
          async first() {
            if (sql.includes('p.payload') && sql.includes('FROM sessions')) {
              return {
                user_id: 1,
                expires_at: Date.now() + 3600000,
                username: 'u',
                payload: remoteText,
                updated_at: updatedAt,
              };
            }
            if (sql.includes('UPDATE progress SET payload')) {
              remoteText = String(args[0]);
              updatedAt = Math.max(updatedAt + 1, Date.now());
              return { updated_at: updatedAt };
            }
            if (sql.includes('INSERT INTO progress')) {
              if (sql.includes('ON CONFLICT(user_id) DO NOTHING')) return null;
              remoteText = String(args[1] || args[0]);
              updatedAt = Math.max(updatedAt + 1, Date.now());
              return { updated_at: updatedAt };
            }
            if (sql.includes('DELETE FROM sessions')) return null;
            return null;
          },
          async run() { return {}; },
          async all() { return { results: [] }; },
        };
      },
    };
  },
  async batch() { return []; },
};
const env = { DB: db, ASSETS: { fetch: async () => new Response('') } };
async function sync(body) {
  const response = await worker.fetch(new Request('https://example.com/api/state/sync', {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'cookie': 'ky_sid=test-token' },
    body: JSON.stringify({ expectedUsername: 'u', ...body }),
  }), env, {});
  const text = await response.text();
  let data = {};
  try { data = JSON.parse(text); } catch { data = { raw: text }; }
  return { status: response.status, data };
}
function emptyPayload() {
  return { state: {}, chapterData: {}, daily: {}, conf: {} };
}
const now = Date.now();
const out = {};

const resetAt = now - 3 * 86400000;
remoteText = JSON.stringify({
  state: {
    old: { t: resetAt - 3600000, mastered: true },
    after: { t: resetAt + 3600000, mastered: true },
    recent: { t: now - 3600000, mastered: true },
  },
  chapterData: {}, daily: {}, conf: {},
});
const reset = await sync({ payload: emptyPayload(), reset: true, mode: 'clear', resetAt });
out.resetStatus = reset.status;
out.resetOldDeleted = !!(reset.data.payload && reset.data.payload.state.old && reset.data.payload.state.old.del === 1);
out.resetAfterPreserved = !!(reset.data.payload && reset.data.payload.state.after && reset.data.payload.state.after.mastered === true && !reset.data.payload.state.after.del);

const clearAt = now - 2 * 86400000;
remoteText = JSON.stringify({
  state: {
    alpha: { del: 1, t: clearAt },
    beta: { del: 1, t: clearAt },
    between: { t: now - 30000, mastered: true },
  },
  chapterData: {}, daily: {},
  conf: { resetAt: clearAt, serverFenceAt: clearAt, serverFenceMode: 'clear' },
});
const importStartedAt = now - 60000;
const importOperationId = 'import-operation-20261029';
const importPayload = {
  state: {
    alpha: { t: clearAt - 3 * 86400000, mastered: true },
    gamma: { t: importStartedAt, mastered: true },
  },
  chapterData: {}, daily: {}, conf: {},
};
const imported = await sync({
  payload: importPayload,
  reset: true, mode: 'import', importStartedAt, operationId: importOperationId,
});
const importedPayload = imported.data.payload || {};
out.importStatus = imported.status;
out.importSelectedLive = !!(importedPayload.state && importedPayload.state.alpha && importedPayload.state.alpha.mastered === true && !importedPayload.state.alpha.del);
out.importBetweenPreserved = !!(importedPayload.state && importedPayload.state.between && importedPayload.state.between.mastered === true && !importedPayload.state.between.del);
out.importMode = importedPayload.conf && importedPayload.conf.serverFenceMode === 'import' && Number(importedPayload.conf.resetAt || 0) === 0;
out.importOperation = importedPayload.conf && importedPayload.conf.serverFenceOperationId === importOperationId;
out.importStableFence = importedPayload.conf && Number(importedPayload.conf.serverFenceAt) === importStartedAt;
out.importTransientStripped = importedPayload.conf && !('overwritePending' in importedPayload.conf)
  && !('overwriteMode' in importedPayload.conf) && !('importStartedAt' in importedPayload.conf)
  && !('importOperationId' in importedPayload.conf);
const between = await sync({
  payload: {
    state: { postImport: { t: importStartedAt + 20000, mastered: true } },
    chapterData: {}, daily: {}, conf: {},
  },
});
out.postImportLive = !!(between.data.payload && between.data.payload.state && between.data.payload.state.postImport && between.data.payload.state.postImport.mastered === true);
const retried = await sync({
  payload: importPayload,
  reset: true, mode: 'import', importStartedAt, operationId: importOperationId,
});
out.importRetryIdempotent = retried.status === 200 && retried.data.merged === false
  && !!(retried.data.payload && retried.data.payload.state.postImport && retried.data.payload.state.postImport.mastered === true)
  && retried.data.payload.conf && Number(retried.data.payload.conf.serverFenceAt) === importStartedAt;
const stale = await sync({
  payload: {
    state: { staleDevice: { t: importStartedAt - 30000, mastered: true } },
    chapterData: {}, daily: {}, conf: {},
  },
  reset: true, mode: 'import', importStartedAt: importStartedAt - 10000,
  operationId: 'stale-import-operation-1',
});
out.staleImportSuperseded = stale.status === 200
  && !!(stale.data.payload && stale.data.payload.state.postImport && stale.data.payload.state.postImport.mastered === true)
  && !(stale.data.payload && stale.data.payload.state.staleDevice);
const follow = await sync({
  payload: {
    state: { delta: { t: clearAt - 3600000, mastered: true } },
    chapterData: {}, daily: {}, conf: {},
  },
});
out.importFenceBlocksOld = !!(follow.data.payload && follow.data.payload.state.delta && follow.data.payload.state.delta.del === 1);
console.log('RESULT:' + JSON.stringify(out));
"""
    data, proc = run_node_harness(script, {"worker.mjs": worker_source}, timeout=120)
    if data is None:
        detail = harness_detail(proc)
        for name in ("reset 超 24h 不误删", "import 命中备份旧记录", "import 不留下长期 clear 栅栏", "import fence 拦截旧设备复活"):
            check(name, False, detail)
        return
    check("reset 超 24h 不误删",
          data.get("resetStatus") == 200 and data.get("resetOldDeleted") is True and data.get("resetAfterPreserved") is True,
          json.dumps(data, ensure_ascii=False))
    check("import 命中备份旧记录",
          data.get("importStatus") == 200 and data.get("importSelectedLive") is True,
          json.dumps(data, ensure_ascii=False))
    check("import 不留下长期 clear 栅栏", data.get("importMode") is True,
          json.dumps(data, ensure_ascii=False))
    check("import fence 拦截旧设备复活", data.get("importFenceBlocksOld") is True,
          json.dumps(data, ensure_ascii=False))
    check("\u5bfc\u5165\u4fdd\u7559\u53d1\u8d77\u540e\u7684\u5e76\u53d1\u8fdb\u5ea6", data.get("importBetweenPreserved") is True,
          json.dumps(data, ensure_ascii=False))
    check("\u5bfc\u5165\u4f7f\u7528\u70b9\u51fb\u65f6\u523b fence", data.get("importStableFence") is True and data.get("importOperation") is True,
          json.dumps(data, ensure_ascii=False))
    check("\u5bfc\u5165\u4e0d\u6c61\u67d3\u4e91\u7aef\u4e34\u65f6\u72b6\u6001", data.get("importTransientStripped") is True,
          json.dumps(data, ensure_ascii=False))
    check("\u5bfc\u5165\u91cd\u8bd5\u5e42\u7b49", data.get("importRetryIdempotent") is True and data.get("postImportLive") is True,
          json.dumps(data, ensure_ascii=False))
    check("\u8fc7\u671f\u7834\u574f\u64cd\u4f5c\u4e0d\u8d8a\u8fc7\u65b0 fence", data.get("staleImportSuperseded") is True,
          json.dumps(data, ensure_ascii=False))


def build_lock_ownership_checks():
    source_path = os.path.join(ROOT, "scripts", "make_html.py")
    source = io.open(source_path, encoding="utf-8").read()
    try:
        tree = ast.parse(source, filename=source_path)
        nodes = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in ("acquire_lock", "release_lock")
        ]
        if {node.name for node in nodes} != {"acquire_lock", "release_lock"}:
            raise RuntimeError("构建锁函数不完整")
        module = ast.Module(body=nodes, type_ignores=[])
        lock_path = os.path.join(tempfile.mkdtemp(prefix=".lock-test-", dir=os.path.join(ROOT, "scripts", "tools")), "deploy.lock")
        from pathlib import Path as LockPath
        class NoAtExit:
            def register(self, _fn):
                return None
        namespace = {
            "os": os,
            "time": time,
            "atexit": NoAtExit(),
            "LOCK": LockPath(lock_path),
            "LOCK_FD": None,
        }
        exec(compile(module, source_path, "exec"), namespace)
    except Exception as exc:
        check("构建锁 ownership", False, str(exc))
        return
    try:
        namespace["acquire_lock"]()
        namespace["release_lock"]()
        own_removed = not os.path.exists(lock_path)

        namespace["acquire_lock"]()
        old_fd = namespace["LOCK_FD"]
        os.close(old_fd)
        namespace["LOCK_FD"] = old_fd
        os.unlink(lock_path)
        with io.open(lock_path, "w", encoding="ascii") as f:
            f.write("other-owner")
        namespace["release_lock"]()
        owner_after = ""
        if os.path.exists(lock_path):
            with io.open(lock_path, encoding="ascii") as f:
                owner_after = f.read()
    except Exception as exc:
        check("构建锁 ownership", False, str(exc))
        return
    finally:
        try:
            if namespace.get("LOCK_FD") is not None:
                os.close(namespace["LOCK_FD"])
                namespace["LOCK_FD"] = None
        except Exception:
            pass
        try:
            os.unlink(lock_path)
        except OSError:
            pass
        shutil.rmtree(os.path.dirname(lock_path), ignore_errors=True)
    check("构建锁 ownership", own_removed and owner_after == "other-owner",
          "own_removed=%s owner_after=%s" % (own_removed, owner_after))


def behavior_checks():
    state_shard_behavior_checks()
    worker_audio_behavior_checks()
    frontend_api_behavior_checks()
    sw_cache_status_checks()
    page_offline_cache_checks()
    worker_reset_import_checks()
    build_lock_ownership_checks()


def runtime_checks():
    sw = os.path.join(ROOT, "software", "sw.js")
    # Worker 的合并逻辑是构建时从 shared/merge.js 注入的，
    # 所以能跑的产物是 deploy/_worker.js，源码 backend/worker.js 里只有占位符。
    worker = os.path.join(ROOT, "deploy", "_worker.js")
    if not os.path.exists(worker):
        check("Worker 产物存在", False, "先跑 make_html.py")
    for label, path in (("Service Worker", sw), ("Worker", worker)):
        if not os.path.exists(path):
            check(label + "存在", False)
            continue
        r = subprocess.run(["node", "--check", path], capture_output=True)
        check(label + "语法有效", r.returncode == 0, r.stderr.decode("utf-8", "replace")[:200])

    if os.path.exists(worker):
        worker_url = "file:///" + worker.replace("\\", "/")
        js = (
            "globalThis.fetch = async () => new Response(new Uint8Array([73,68,51]), "
            "{status:200, headers:{'content-type':'audio/mpeg','content-length':'3'}});"
            "globalThis.caches = {default:{match:async()=>null, put:async()=>{}}};"
            "const {default:worker} = await import(%r);"
            "const req = new Request('https://example.com/api/audio?word=hello');"
            "const res = await worker.fetch(req, {ASSETS:{fetch:async()=>new Response('')}});"
            "const n = (await res.arrayBuffer()).byteLength;"
            "if (res.status !== 200 || res.headers.get('content-type') !== 'audio/mpeg' || n !== 3) process.exit(1);"
            % worker_url
        )
        r = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True)
        check("发音代理可返回音频", r.returncode == 0, r.stderr.decode("utf-8", "replace")[:200])
        body_checks(worker_url)

    worker_text = io.open(worker, encoding="utf-8").read() if os.path.exists(worker) else ""
    check("同步写入合并为单次 D1", "RETURNING updated_at" in worker_text and "ON CONFLICT(user_id) DO UPDATE" in worker_text)
    check("同步支持增量拉取", "unchanged: true" in worker_text and "searchParams.get('since')" in worker_text)
    check("同步支持服务端合并", "/state/sync" in worker_text and "mergeSnapshots(incoming, base)" in worker_text)
    check("服务端合并每日节奏", "function mergeDaily(" in worker_text and "daily: mergeDaily(" in worker_text)
    check("删除用墓碑表达", "function isTombstone(" in worker_text and "del: 1" in worker_text)
    check("服务端补全清空墓碑", "mergeDestructiveSnapshot(local, remote, mergeOptions)" in worker_text)
    check("reset 以客户端快照为准", "mergeDestructiveSnapshot(local, remote, mergeOptions)" in worker_text and "function mergeDestructiveSnapshot" in io.open(os.path.join(ROOT, "shared", "merge.js"), encoding="utf-8").read())
    audio_source = io.open(os.path.join(ROOT, "software", "src", "app", "40-audio.js"), encoding="utf-8").read()
    check("\u97f3\u9891\u7f13\u5b58\u6807\u8bb0\u53ea\u8ba4\u670d\u52a1\u7aef\u786e\u8ba4",
          "if (source === 'cached') rememberAudio" not in audio_source)
    import importlib.util
    deploy_path = os.path.join(ROOT, "scripts", "deploy.py")
    deploy_spec = importlib.util.spec_from_file_location("ky_deploy_checks", deploy_path)
    deploy_module = importlib.util.module_from_spec(deploy_spec)
    deploy_spec.loader.exec_module(deploy_module)
    check("\u53d1\u5e03\u5b58\u5728 10 \u5206\u949f\u4e92\u65a5\u7a97\u53e3",
          deploy_module.RELEASE_COOLDOWN_SECONDS == 600
          and "recent_release_activity()" in io.open(deploy_path, encoding="utf-8").read())
    check("\u6570\u636e\u5e93\u8fc1\u79fb\u6709\u5df2\u6267\u884c\u8d26\u672c", not deploy_module.pending_migrations(),
          str([str(path) for path in deploy_module.pending_migrations()]))
    deploy_text = io.open(deploy_path, encoding="utf-8").read()
    check("发布 HTTP 验收使用系统网络栈",
          "Invoke-WebRequest" in deploy_text and "browser_detail" in deploy_text)
    check("合并键序规范化后比较", "const mergedText = stableJson(merged);" in worker_text
          and "mergedText === row.payload" in worker_text)
    check("版本号严格单调", "MAX(?, updated_at + 1)" in worker_text)
    check("用户名不区分大小写判重", "COLLATE NOCASE" in worker_text)
    check("服务端章节与 deckChapter 自洽", "deckChapter[deck] = chapter;" in worker_text)
    check("同步支持压缩上传", "DecompressionStream" in worker_text and "x-ky-encoding" in worker_text)
    check("流式读取有体积上限", "if (total > limit)" in worker_text and "reader.cancel()" in worker_text)


def body_checks(worker_url):
    """过大的请求体必须回 413，而不是把 isolate 读到 OOM。"""
    js = (
        "import zlib from 'node:zlib';"
        "globalThis.caches = {default:{match:async()=>null, put:async()=>{}}};"
        "const stmt = () => ({bind: () => ({first: async () => null, run: async () => ({}), all: async () => ({results: []})})});"
        "const {default:worker} = await import(%r);"
        "const env = {DB:{prepare: stmt, batch: async () => []}, ASSETS:{fetch:async()=>new Response('')}};"
        "const results = [];"
        # 64MB 全空格压缩后很小：解压前看不出问题，必须靠解压后的累计体积拦住
        "const bomb = zlib.gzipSync(Buffer.alloc(64 * 1024 * 1024, 32), {level: 9});"
        "results.push((await worker.fetch(new Request('https://example.com/api/state/sync', {"
        "method:'POST', headers:{'content-type':'application/octet-stream','x-ky-encoding':'gzip',"
        "'cookie':'ky_sid=deadbeef'}, body: bomb}), env, {})).status);"
        "const fat = JSON.stringify({payload:{state:{}}, pad:'x'.repeat(2 * 1024 * 1024)});"
        "results.push((await worker.fetch(new Request('https://example.com/api/state', {"
        "method:'PUT', headers:{'content-type':'application/json','cookie':'ky_sid=deadbeef'},"
        "body: fat}), env, {})).status);"
        "const fatLogin = JSON.stringify({username:'a', password:'b', pad:'x'.repeat(1024 * 1024)});"
        "results.push((await worker.fetch(new Request('https://example.com/api/login', {"
        "method:'POST', headers:{'content-type':'application/json','cf-connecting-ip':'9.9.9.9'},"
        "body: fatLogin}), env, {})).status);"
        "if (results.some(x => x !== 413)) { console.error('statuses=' + results.join(',')); process.exit(1); }"
        % worker_url
    )
    r = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, timeout=180)
    check("超大请求体一律 413", r.returncode == 0, r.stderr.decode("utf-8", "replace")[:300])


def browser_checks():
    if not os.path.exists(BUILT):
        return
    tmp = os.path.join(tempfile.gettempdir(), "_regression.html")
    html = io.open(BUILT, encoding="utf-8").read().replace("</body>", BROWSER_SUITE + "</body>")
    io.open(tmp, "w", encoding="utf-8").write(html)
    try:
        r = subprocess.run(
            [EDGE, "--headless=new", "--disable-gpu", "--virtual-time-budget=20000",
             "--window-size=390,840", "--dump-dom", "file:///" + tmp.replace("\\", "/")],
            capture_output=True, timeout=150,
        )
        dom = r.stdout.decode("utf-8", "replace")
        i = dom.find("RESULT:")
        if i < 0:
            check("浏览器测试返回", False, "未拿到结果")
            return
        raw = dom[i + 7:dom.find("</title>", i)]
        data = json.loads(raw)
        if "error" in data:
            check("浏览器测试执行", False, data["error"])
            return
        expect = {
            "flip_init": False, "flip_1": True, "flip_2": False,
            "flip_after_next": False,
            "left_mastered": True, "left_due": True, "undo_visible": True,
            "swipe_settled": True, "right_settled": True,
            "stat_due_ok": True, "snapshot_has_icon": True, "merge_icon_kept": True,
            "undo_cleared": True, "undo_back": True,
            "right_same": True, "right_weight": True, "weight_badge": True,
            "composite_weight": True, "unique_weights": True,
            "deck_chapter": True, "resume_ok": True,
            "order_stable": True, "order_shuffled": True, "order_restored": True,
            "shuffle_confirm_cancel": True, "restore_confirm_cancel": True,
            "confirm_messages": True,
            "weight_down": True, "weight_badge_val": True,
            "mastered_has_words": True, "mastered_restored": True,
            "restore_len_minus_one": True, "restore_on_next_word": True,
            "merge_tombstone_wins": True, "merge_delete_beats_older": True,
            "merge_relearn_beats_delete": True, "merge_tombstone_pruned": True,
            "tombstone_all_covers_cloud": True, "reset_prefers_client": True,
            "merge_preserves_post_reset_live": True,
            "merge_no_proto_pollution": True, "snapshot_slim": True, "live_entry_revives": True,
            "merge_position_latest": True,
            "daily_bump": True, "daily_master_bump": True,
            "streak_three": True, "streak_broken": True, "streak_yesterday": True,
            "merge_daily_max": True, "merge_daily_newer_t": True,
            "snapshot_has_daily": True, "daily_scoped": True,
            "undo_rolls_daily": True,
            "rhythm_rendered": True,
            "desktop_click_flips": True, "touch_synth_click_ignored": True,
            "cross_next": True, "cross_prev": True,
            "badge_no_flip": True, "word_touchend_reaches_card": True,
            "list_first_page": True, "list_has_more": True, "list_load_more": True,
            "icon_login_logo": True, "icon_preset": True, "icon_custom": True, "icon_restore": True,
            "header_compact": True, "header_deck_count": True,
            "wheel_next": True, "wheel_prev": True,
            "lazy_same_ref": True, "lazy_cached_before": "words",
            "lazy_after_has_insurance": True,
            "deck_meta_insurance": "1545 词", "deck_meta_core": "1342 词",
            "deck_meta_restored": True,
            "all_words_lazy_at_boot": True, "all_words_ready": True, "all_words_count": 3356,
            "lazy_words_count": 1342, "lazy_insurance_count": 1545,
            "first_card_marked": True, "word_location": "core",
        }
        for k, v in expect.items():
            check("行为·" + k, data.get(k) == v, "实际=%s" % data.get(k))
        check("卡片等级只显示单字母", data.get("priority_letter") is True,
              "实际=%s" % data.get("priority_letter"))
        check("长按详情词典默认展开", data.get("dict_open_default") is True,
              "实际=%s" % data.get("dict_open_default"))
        check("详情面板能开能关", data.get("detail_shown") is True and data.get("detail_hidden") is True,
              "开=%s 关=%s" % (data.get("detail_shown"), data.get("detail_hidden")))
        for key, label in (("flip_node_delta", "翻卡不重建 DOM"), ("navigate_node_delta", "切词不重建 DOM")):
            value = data.get(key)
            check("行为·" + label, isinstance(value, int) and abs(value) <= 2, "节点变化=%s" % value)
        check("行为·点开释义单词不下移", data.get("word_shift") == 0, "位移=%s" % data.get("word_shift"))
        check("行为·点开释义释义不位移", data.get("meaning_shift") == 0, "位移=%s" % data.get("meaning_shift"))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def perf_checks():
    """用 Edge headless 实测首屏，失败时按未达标记（不阻断其它检查）。"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import measure_perf
        data = measure_perf.measure()
    except Exception as e:
        data = None
        check("首屏性能可测量", False, str(e)[:120])
        return
    if not data:
        check("首屏性能可测量", False, "Edge headless 未返回性能标记")
        return
    check("首卡渲染 < %dms" % PERF_BUDGET_MS, 0 < data.get("firstCard", 0) < PERF_BUDGET_MS, "%sms" % data.get("firstCard"))
    check("首屏 DOM 节点 < 400", 0 < data.get("nodes", 0) < 400, "%s 个" % data.get("nodes"))
    check("DOMContentLoaded < %dms" % PERF_BUDGET_MS, 0 < data.get("dcl", 0) < PERF_BUDGET_MS, "%sms" % data.get("dcl"))


def main():
    print("=" * 56)
    print("静态检查")
    print("=" * 56)
    static_checks()
    print("=" * 56)
    print("数据完整性")
    print("=" * 56)
    data_checks()
    print("=" * 56)
    print("运行时资源")
    print("=" * 56)
    runtime_checks()
    print("=" * 56)
    print("关键行为回归")
    print("=" * 56)
    behavior_checks()
    print("=" * 56)
    print("浏览器行为")
    print("=" * 56)
    browser_checks()
    print("=" * 56)
    print("网页按需加载")
    print("=" * 56)
    web_browser_checks()
    print("=" * 56)
    print("首屏性能")
    print("=" * 56)
    perf_checks()

    print("=" * 56)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = [(n, d) for n, ok, d in results if not ok]
    for n, ok, d in results:
        print(("  PASS  " if ok else "  FAIL  ") + n + (("  [" + d + "]") if d and not ok else ""))
    print("=" * 56)
    print("通过 %d / %d" % (passed, len(results)))
    if failed:
        print("失败项:")
        for n, d in failed:
            print("  - %s  %s" % (n, d))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
