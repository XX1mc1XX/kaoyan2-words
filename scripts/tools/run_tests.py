# -*- coding: utf-8 -*-
"""统一回归测试：把散落的验证点整合成一个可重复执行的套件。

用法：
    python scripts/tools/run_tests.py

全部通过返回 0，有失败返回 1（可用于 CI 或部署前门禁）。
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUILT = os.path.join(ROOT, "software", "考研核心词.html")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))


# ---------- 静态检查（不需要浏览器）----------
def static_checks():
    if not os.path.exists(BUILT):
        check("产物存在", False, "先跑 make_html.py")
        return
    t = io.open(BUILT, encoding="utf-8").read()

    check("产物大小 < 600KB", os.path.getsize(BUILT) < 600 * 1024,
          "%.0fKB" % (os.path.getsize(BUILT) / 1024))
    check("无 autoShow 残留", t.count("autoShow") <= 1,
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
    check("含恢复原序按钮", "restoreOrder" in t)
    check("含合成权重", "scoreOf" in t)


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
        for x in data:
            allw.setdefault(x["word"], []).append(d)
    dup = {w: v for w, v in allw.items() if len(v) > 1}
    check("跨库无重复词", not dup, str(list(dup.items())[:3]))
    check("总词数 > 3000", total > 3000, "%d 词" % total)


# ---------- 浏览器内行为测试 ----------
BROWSER_SUITE = r"""
<script>
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


def browser_checks():
    if not os.path.exists(BUILT):
        return
    tmp = os.path.join(tempfile.gettempdir(), "_regression.html")
    html = io.open(BUILT, encoding="utf-8").read().replace("</body>", BROWSER_SUITE + "</body>")
    io.open(tmp, "w", encoding="utf-8").write(html)
    try:
        r = subprocess.run(
            [EDGE, "--headless=new", "--disable-gpu", "--virtual-time-budget=8000",
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
            "undo_cleared": True, "undo_back": True,
            "right_same": True, "right_weight": True, "weight_badge": True,
            "deck_chapter": True, "resume_ok": True,
            "order_stable": True, "order_shuffled": True, "order_restored": True,
            "weight_down": True, "weight_badge_val": True,
            "mastered_has_words": True, "mastered_restored": True,
            "cross_next": True, "cross_prev": True,
            "badge_no_flip": True,
        }
        for k, v in expect.items():
            check("行为·" + k, data.get(k) == v, "实际=%s" % data.get(k))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


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
    print("浏览器行为")
    print("=" * 56)
    browser_checks()

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
