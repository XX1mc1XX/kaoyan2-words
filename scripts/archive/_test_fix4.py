# -*- coding: utf-8 -*-
"""验证：左滑后进度总数减少、已认识词库有内容、恢复能跳回原章节。"""
import io
import subprocess

SRC = r"c:\my_project\单词\deploy\index.html"
OUT = r"c:\my_project\单词\output\_test4.html"

INJECT = """
<script>
function fire(card, type, x, y) {
  const t = new Touch({ identifier: 1, target: card, clientX: x, clientY: y, pageX: x, pageY: y, screenX: x, screenY: y });
  card.dispatchEvent(new TouchEvent(type, {
    touches: type === 'touchend' ? [] : [t], targetTouches: type === 'touchend' ? [] : [t],
    changedTouches: [t], bubbles: true, cancelable: true }));
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
    out.push('total_before=' + queue.length);
    const known = document.getElementById('word').textContent;
    swipe(card, 300, 120);
    setTimeout(function () {
      out.push('total_after=' + queue.length);
      out.push('mastered_word=' + known);
      // 切到已认识词库
      switchDeck('mastered');
      out.push('mastered_deck_count=' + deckWords().length);
      out.push('owner=' + deckOfWord(known));
      out.push('owner_index=' + ownerIndex(deckOfWord(known), known));
      // 恢复
      state[known].mastered = false; save(LS_STATE, state);
      out.push('after_restore_deck_count=' + deckWords().length);
      document.title = out.join(' | ');
    }, 280);
  } catch (e) { document.title = 'ERR=' + e.message; }
}, 1500);
</script>
"""

html = io.open(SRC, encoding="utf-8").read().replace("</body>", INJECT + "</body>")
io.open(OUT, "w", encoding="utf-8").write(html)

edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
res = subprocess.run([edge, "--headless=new", "--disable-gpu", "--virtual-time-budget=7000",
                      "--window-size=390,840", "--dump-dom", "file:///c:/my_project/单词/output/_test4.html"],
                     capture_output=True, timeout=120)
dom = res.stdout.decode("utf-8", "replace")
i = dom.find("<title>")
print(dom[i:i + 400] if i >= 0 else "no title")
