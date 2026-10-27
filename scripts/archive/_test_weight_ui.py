# -*- coding: utf-8 -*-
"""验证右滑后权重徽章实时出现，顶部显示本章进度。"""
import io
import subprocess

SRC = r"c:\my_project\单词\software\考研核心词.html"
OUT = r"c:\my_project\单词\output\_weight_test.html"

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
    const wb = document.getElementById('weightBadge');
    out.push('top_text=' + document.getElementById('wordId').textContent);
    out.push('badge_hidden_before=' + wb.classList.contains('hidden'));

    // 右滑两次
    for (let i = 0; i < 2; i++) {
      fire(card, 'touchstart', 100, 400);
      fire(card, 'touchmove', 190, 402);
      fire(card, 'touchmove', 280, 403);
      fire(card, 'touchend', 280, 403);
    }
    setTimeout(function () {
      out.push('badge_text=' + wb.textContent);
      out.push('badge_visible=' + !wb.classList.contains('hidden'));
      out.push('badge_pulsed=' + wb.classList.contains('pulse'));
      out.push('same_word=' + (queue[idx] ? queue[idx].word : '?'));
      document.title = out.join(' | ');
    }, 250);
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
    [edge, "--headless=new", "--disable-gpu", "--virtual-time-budget=6000",
     "--window-size=390,840", "--dump-dom", "file:///c:/my_project/单词/output/_weight_test.html"],
    capture_output=True, timeout=120,
)
dom = res.stdout.decode("utf-8", "replace")
i = dom.find("<title>")
print(dom[i:i + 350] if i >= 0 else "no title")
