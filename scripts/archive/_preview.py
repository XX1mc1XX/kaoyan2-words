# -*- coding: utf-8 -*-
"""生成临时预览页：自动展开一个有变形词的卡片，供截图验证。"""
import io

SRC = r"c:\my_project\单词\deploy\index.html"
OUT = r"c:\my_project\单词\output\_preview.html"

INJECT = """
<script>
setTimeout(function(){
  try {
    var i = WORDS.findIndex(function(w){ return w.forms && w.forms.length; });
    if (i < 0) { document.body.setAttribute('data-preview','no-forms'); return; }
    var w = WORDS[i];
    document.getElementById('word').textContent = w.word;
    document.getElementById('forms').textContent = (w.forms||[]).join(' / ');
    document.getElementById('formsBox').classList.remove('hidden');
    var m = document.getElementById('meaning');
    m.textContent = w.meaning;
    document.body.setAttribute('data-preview', w.word);
  } catch(e) { document.body.setAttribute('data-preview', 'err:'+e.message); }
}, 900);
</script>
"""

html = io.open(SRC, encoding="utf-8").read()
html = html.replace("</body>", INJECT + "</body>")
io.open(OUT, "w", encoding="utf-8").write(html)
print("written", OUT, len(html))
