# -*- coding: utf-8 -*-
"""截图翻面后的实际样子（含释义），并 dump 释义文本。"""
import io
import subprocess

SRC = r"c:\my_project\单词\software\考研核心词.html"
OUT = r"c:\my_project\单词\output\_reveal_preview.html"

INJECT = """
<script>
setTimeout(function () {
  try {
    revealed = true;
    renderStudy();
    var rows = [];
    for (var i = 0; i < 3; i++) {
      var w = queue[i];
      if (w) rows.push(w.word + ' => ' + w.meaning);
    }
    document.body.setAttribute('data-sample', rows.join(' || '));
  } catch (e) {
    document.body.setAttribute('data-sample', 'ERR=' + e.message);
  }
}, 1200);
</script>
"""

html = io.open(SRC, encoding="utf-8").read().replace("</body>", INJECT + "</body>")
io.open(OUT, "w", encoding="utf-8").write(html)

edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
subprocess.run([edge, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                "--virtual-time-budget=3500", "--window-size=390,840",
                "--screenshot=c:\\my_project\\单词\\output\\_reveal.png",
                "file:///c:/my_project/单词/output/_reveal_preview.html"],
               capture_output=True, timeout=120)

res = subprocess.run([edge, "--headless=new", "--disable-gpu", "--virtual-time-budget=3500",
                      "--window-size=390,840", "--dump-dom",
                      "file:///c:/my_project/单词/output/_reveal_preview.html"],
                     capture_output=True, timeout=120)
dom = res.stdout.decode("utf-8", "replace")
i = dom.find('data-sample=')
print(dom[i:i + 300] if i >= 0 else "no sample")
