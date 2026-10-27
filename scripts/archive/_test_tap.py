# -*- coding: utf-8 -*-
"""验证翻面：点一下显示、再点隐藏、翻词自动收起、按钮同样有效。"""
import io
import subprocess

SRC = r"c:\my_project\单词\software\考研核心词.html"
OUT = r"c:\my_project\单词\output\_tap_test.html"

INJECT = """
<script>
function tap(card) {
  const t = new Touch({ identifier: 1, target: card, clientX: 200, clientY: 400,
                        pageX: 200, pageY: 400, screenX: 200, screenY: 400 });
  card.dispatchEvent(new TouchEvent('touchstart', { touches: [t], targetTouches: [t], changedTouches: [t], bubbles: true, cancelable: true }));
  card.dispatchEvent(new TouchEvent('touchend', { touches: [], targetTouches: [], changedTouches: [t], bubbles: true, cancelable: true }));
}
setTimeout(function () {
  const out = [];
  try {
    const card = document.getElementById('card');
    const mean = document.getElementById('meaning');
    const btn = document.getElementById('meaningToggle');
    const vis = () => !mean.classList.contains('meaning-placeholder');

    out.push('init=' + vis());
    tap(card); out.push('tap1=' + vis());
    tap(card); out.push('tap2=' + vis());
    tap(card); out.push('tap3=' + vis());

    // 显示状态下翻词，应自动收起
    navigate(1);
    out.push('after_next=' + vis());
    out.push('btn_text=' + btn.textContent);

    // 用按钮翻
    btn.click(); out.push('btn_on=' + vis());
    btn.click(); out.push('btn_off=' + vis());

    // 再检查全局残留
    out.push('conf_autoShow=' + (typeof conf.autoShow));
    document.title = out.join(' | ');
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
     "--window-size=390,840", "--dump-dom", "file:///c:/my_project/单词/output/_tap_test.html"],
    capture_output=True, timeout=120,
)
dom = res.stdout.decode("utf-8", "replace")
i = dom.find("<title>")
print(dom[i:i + 350] if i >= 0 else "no title")
