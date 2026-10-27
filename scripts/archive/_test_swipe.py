# -*- coding: utf-8 -*-
"""验证：右滑不跳词只加权重、左滑滑出后前进并标记掌握。"""
import io
import subprocess

SRC = r"c:\my_project\单词\deploy\index.html"
OUT = r"c:\my_project\单词\output\_swipe_test2.html"

INJECT = """
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
function swipe(card, x1, x2) {
  fire(card, 'touchstart', x1, 400);
  fire(card, 'touchmove', (x1 + x2) / 2, 401);
  fire(card, 'touchmove', x2, 402);
  fire(card, 'touchend', x2, 402);
}
setTimeout(function () {
  const card = document.getElementById('card');
  const out = [];
  try {
    const first = document.getElementById('word').textContent;

    // 右滑：应留在原词、权重 +1
    swipe(card, 100, 260);
    const afterRight = document.getElementById('word').textContent;
    const stR = state[first] || {};
    out.push('right_same_word=' + (first === afterRight));
    out.push('right_weight=' + (stR.w || 0));
    out.push('right_mastered=' + !!stR.mastered);

    // 左滑：130ms 后应切到下一词、标记掌握
    swipe(card, 300, 120);
    setTimeout(function () {
      const afterLeft = document.getElementById('word').textContent;
      const stL = state[first] || {};
      out.push('left_moved=' + (first !== afterLeft));
      out.push('left_mastered=' + !!stL.mastered);
      out.push('mastered_deck_has=' + (deckWords().length));
      document.title = out.join(' | ');
    }, 260);
  } catch (e) {
    document.title = 'ERR=' + e.message;
  }
}, 1500);
</script>
"""

html = io.open(SRC, encoding="utf-8").read().replace("</body>", INJECT + "</body>")
io.open(OUT, "w", encoding="utf-8").write(html)

edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
res = subprocess.run(
    [edge, "--headless=new", "--disable-gpu", "--virtual-time-budget=7000",
     "--window-size=390,840", "--dump-dom", "file:///c:/my_project/单词/output/_swipe_test2.html"],
    capture_output=True, timeout=120,
)
dom = res.stdout.decode("utf-8", "replace")
i = dom.find("<title>")
print(dom[i:i + 300] if i >= 0 else "no title")
