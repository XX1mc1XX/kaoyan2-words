# -*- coding: utf-8 -*-
"""验证：左滑显示撤销条 / 撤销后词回来且解除掌握 / 认识的词带 7 天到期。"""
import io
import subprocess

SRC = r"c:\my_project\单词\software\考研核心词.html"
OUT = r"c:\my_project\单词\output\_undo_test.html"

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
setTimeout(function () {
  const out = [];
  try {
    const card = document.getElementById('card');
    const word = queue[0];
    // 左滑
    fire(card, 'touchstart', 300, 400);
    fire(card, 'touchmove', 220, 402);
    fire(card, 'touchmove', 140, 403);
    fire(card, 'touchend', 140, 403);

    setTimeout(function () {
      const st = state[word.word] || {};
      const bar = document.getElementById('undoBar');
      out.push('mastered=' + !!st.mastered);
      out.push('due_set=' + (st.due > Date.now()));
      out.push('undo_visible=' + !bar.classList.contains('hidden'));
      out.push('undo_text=' + document.getElementById('undoText').textContent);

      // 点撤销
      document.getElementById('undoBtn').click();
      setTimeout(function () {
        const st2 = state[word.word] || {};
        out.push('after_undo_mastered=' + !!st2.mastered);
        out.push('after_undo_back=' + (document.getElementById('word').textContent === word.word));
        out.push('bar_hidden=' + document.getElementById('undoBar').classList.contains('hidden'));
        document.title = out.join(' | ');
      }, 150);
    }, 300);
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
    [edge, "--headless=new", "--disable-gpu", "--virtual-time-budget=8000",
     "--window-size=390,840", "--dump-dom", "file:///c:/my_project/单词/output/_undo_test.html"],
    capture_output=True, timeout=120,
)
dom = res.stdout.decode("utf-8", "replace")
i = dom.find("<title>")
print(dom[i:i + 420] if i >= 0 else "no title")
