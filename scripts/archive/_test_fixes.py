# -*- coding: utf-8 -*-
"""验证三个修复：右滑解除掌握 / 进度按词恢复 / done 持久化。"""
import io
import subprocess

SRC = r"c:\my_project\单词\software\考研核心词.html"
OUT = r"c:\my_project\单词\output\_fix_test.html"

INJECT = """
<script>
setTimeout(function () {
  const out = [];
  try {
    // --- 1. 右滑解除掌握 ---
    const w0 = queue[0];
    mark(w0, true);
    const afterLeft = !!state[w0.word].mastered;
    mark(w0, false);
    out.push('left_mastered=' + afterLeft);
    out.push('right_clears=' + (state[w0.word].mastered === false));
    out.push('right_weight=' + state[w0.word].w);

    // --- 2. 进度按词恢复（队列变短也不跳词）---
    const key = chapterKey(curChapter);
    const target = queue[Math.min(5, queue.length - 1)];
    chapterData[key] = { order: queue.map(w => w.word), pos: 5, posWord: target.word };
    // 模拟前面有词被掌握，队列会变短
    state[queue[0].word] = { w: 0, mastered: true, seen: 1 };
    loadChapter(curChapter);
    const shown = queue[idx] ? queue[idx].word : '(done)';
    out.push('resume_expect=' + target.word);
    out.push('resume_actual=' + shown);
    out.push('resume_ok=' + (shown === target.word));

    // --- 3. done 持久化 ---
    idx = queue.length;
    savePos();
    loadChapter(curChapter);
    out.push('done_persist=' + (idx >= queue.length));
    out.push('idx=' + idx + '/len=' + queue.length);
  } catch (e) {
    out.push('ERR=' + e.message);
  }
  document.title = out.join(' | ');
}, 1500);
</script>
"""

html = io.open(SRC, encoding="utf-8").read().replace("</body>", INJECT + "</body>")
io.open(OUT, "w", encoding="utf-8").write(html)

edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
res = subprocess.run(
    [edge, "--headless=new", "--disable-gpu", "--virtual-time-budget=6000",
     "--window-size=390,840", "--dump-dom", "file:///c:/my_project/单词/output/_fix_test.html"],
    capture_output=True, timeout=120,
)
dom = res.stdout.decode("utf-8", "replace")
i = dom.find("<title>")
print(dom[i:i + 400] if i >= 0 else "no title")
