# -*- coding: utf-8 -*-
"""诊断页面宽度：注入测量脚本，用 dump-dom 读回真实数值。"""
import io
import subprocess

SRC = r"c:\my_project\单词\deploy\index.html"
OUT = r"c:\my_project\单词\output\_diag.html"

INJECT = """
<script>
setTimeout(function(){
  function w(el){ return el ? Math.round(el.scrollWidth) : -1; }
  var over = [];
  document.querySelectorAll('body *').forEach(function(el){
    var r = el.getBoundingClientRect();
    if (r.right > window.innerWidth + 1) over.push((el.className||el.tagName) + ':' + Math.round(r.right));
  });
  document.title = 'SW=' + document.documentElement.scrollWidth
    + ' BW=' + document.body.scrollWidth
    + ' VW=' + window.innerWidth
    + ' OVER=[' + over.slice(0,8).join(', ') + ']';
}, 1200);
</script>
"""

html = io.open(SRC, encoding="utf-8").read().replace("</body>", INJECT + "</body>")
io.open(OUT, "w", encoding="utf-8").write(html)

edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
res = subprocess.run(
    [edge, "--headless=new", "--disable-gpu", "--virtual-time-budget=3000",
     "--window-size=360,780", "--dump-dom", "file:///c:/my_project/单词/output/_diag.html"],
    capture_output=True, timeout=120,
)
out = res.stdout.decode("utf-8", "replace")
i = out.find("<title>")
print(out[i:i + 400] if i >= 0 else "no title found")
