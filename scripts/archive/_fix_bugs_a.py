# -*- coding: utf-8 -*-
"""修 4 个 bug：右滑不解除掌握 / 进度按词定位 / done 持久化 / 完成页按钮看不见 + 删死代码。"""
import io

P = r"c:\my_project\单词\software\template.html"
t = io.open(P, encoding="utf-8").read()
log = []


def rep(old, new, label):
    global t
    if old in t:
        t = t.replace(old, new, 1)
        log.append("OK    " + label)
    else:
        log.append("MISS  " + label)


# 1. 右滑「不认识」要把 mastered 清掉，否则之前左滑标过的词永久消失
rep("""  if (known) st.mastered = true;
  else st.w = (st.w || 0) + 1;""",
    """  if (known) st.mastered = true;
  else { st.w = (st.w || 0) + 1; st.mastered = false; }""",
    "右滑解除掌握标记")

# 2. 进度改为「记词」而不是「记下标」：队列过滤后下标会错位
rep("""function savePos() {
  const key = chapterKey(curChapter);
  if (chapterData[key]) {
    chapterData[key].pos = idx;
    save('ky_chapter_v1', chapterData);
  }
}""",
    """function savePos() {
  const key = chapterKey(curChapter);
  if (!chapterData[key]) return;
  chapterData[key].pos = idx;
  chapterData[key].posWord = idx < queue.length ? queue[idx].word : null;
  chapterData[key].done = queue.length > 0 && idx >= queue.length;
  save('ky_chapter_v1', chapterData);
}""",
    "savePos 记词 + done")

rep("  idx = Math.min(Math.max(rec.pos || 0, 0), Math.max(queue.length - 1, 0));",
    """  if (rec.done && queue.length) {
    idx = queue.length;                       // 保持「已过完」状态
  } else if (rec.posWord) {
    const j = queue.findIndex(w => w.word === rec.posWord);
    idx = j >= 0 ? j : 0;                     // 按词定位，队列变短也不会错位
  } else {
    idx = Math.min(Math.max(rec.pos || 0, 0), Math.max(queue.length - 1, 0));
  }""",
    "loadChapter 按词恢复进度")

# 3. 完成页按钮：白字无底色，几乎看不见
rep(".btn{border:0;border-radius:14px;padding:13px 8px;font:inherit;font-size:15px;font-weight:750;color:#fff;cursor:pointer}",
    ".btn{border:0;border-radius:14px;padding:13px 8px;font:inherit;font-size:15px;font-weight:750;color:#fff;background:var(--brand);cursor:pointer}",
    "完成页按钮加底色")

# 4. 删掉引用已删除元素的死函数（一旦调用必抛 TypeError）
rep("""function renderDisplayOpts() {
  const box = $('displayOpts');
  box.replaceChildren();
  for (const opt of [{ v: false, t: '先隐藏，点开看' }, { v: true, t: '始终显示释义' }]) {
    const b = document.createElement('button');
    b.textContent = opt.t;
    b.classList.toggle('active', !!conf.autoShow === opt.v);
    b.onclick = () => {
      conf.autoShow = opt.v; save(LS_CONF, conf); revealed = null;
      renderDisplayOpts(); renderStudy();
    };
    box.append(b);
  }
}
""", "", "删除 renderDisplayOpts 死代码")

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
print("残留 renderDisplayOpts:", t.count("renderDisplayOpts"), "| posWord:", t.count("posWord"))
