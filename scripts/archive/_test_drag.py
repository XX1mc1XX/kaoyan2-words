# -*- coding: utf-8 -*-
"""验证拖动进度条时序号和卡片实时同步。"""
import io
import subprocess

SRC = r"c:\my_project\单词\deploy\index.html"
OUT = r"c:\my_project\单词\output\_test_drag.html"

INJECT = """
<script>
setTimeout(function () {
  const out = [];
  try {
    const pb = document.getElementById('progressBar');
    const word0 = document.getElementById('word').textContent;
    const pos0 = document.getElementById('position').textContent;
    // 模拟拖动到第 60 个
    pb.value = '59';
    pb.dispatchEvent(new Event('input', { bubbles: true }));
    const word1 = document.getElementById('word').textContent;
    const pos1 = document.getElementById('position').textContent;
    // 再拖到第 120 个
    pb.value = '119';
    pb.dispatchEvent(new Event('input', { bubbles: true }));
    const word2 = document.getElementById('word').textContent;
    const pos2 = document.getElementById('position').textContent;
    out.push('w0=' + word0, 'p0=' + pos0.trim());
    out.push('w1=' + word1, 'p1=' + pos1.trim());
    out.push('w2=' + word2, 'p2=' + pos2.trim());
    out.push('changed=' + (word0 !== word1 && word1 !== word2));
    out.push('pos_changed=' + (pos0 !== pos1 && pos1 !== pos2));
  } catch (e) { out.push('ERR=' + e.message); }
  document.title = out.join(' | ');
}, 1500);
</script>
"""

html = io.open(SRC, encoding="utf-8").read().replace("</body>", INJECT + "</body>")
io.open(OUT, "w", encoding="utf-8").write(html)

edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
res = subprocess.run([edge, "--headless=new", "--disable-gpu", "--virtual-time-budget=6000",
                      "--window-size=390,840", "--dump-dom", "file:///c:/my_project/单词/output/_test_drag.html"],
                     capture_output=True, timeout=120)
dom = res.stdout.decode("utf-8", "replace")
i = dom.find("<title>")
print(dom[i:i + 400] if i >= 0 else "no title")
