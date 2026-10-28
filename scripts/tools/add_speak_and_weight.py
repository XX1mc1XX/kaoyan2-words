# -*- coding: utf-8 -*-
"""朗读总开关 + 点红点减权重 + 单词区上移。"""
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


# 1. 头部右侧两个按钮并排
rep('''      <button class="meaning-toggle" id="meaningToggle" aria-pressed="false">释义关</button>''',
    '''      <div class="head-btns">
        <button class="meaning-toggle" id="speakToggle" aria-pressed="true">朗读开</button>
        <button class="meaning-toggle" id="meaningToggle" aria-pressed="false">释义关</button>
      </div>''', "头部加朗读按钮")

rep('''.meaning-toggle{justify-self:end;border:1px solid color-mix(in srgb,var(--brand) 45%,var(--line));background:var(--card);
  color:var(--brand);font:inherit;font-size:12.5px;font-weight:750;border-radius:999px;padding:7px 10px;cursor:pointer;
  white-space:nowrap;max-width:100%;overflow:hidden;text-overflow:ellipsis}''',
    '''.head-btns{justify-self:end;display:flex;gap:5px;min-width:0}
.meaning-toggle{border:1px solid color-mix(in srgb,var(--brand) 45%,var(--line));background:var(--card);
  color:var(--brand);font:inherit;font-size:12.5px;font-weight:750;border-radius:999px;padding:7px 9px;cursor:pointer;
  white-space:nowrap}''', "头部按钮布局")

# 删掉后面重复的一份 .meaning-toggle 旧样式
rep('''.meaning-toggle{justify-self:end;border:1px solid color-mix(in srgb,var(--brand) 45%,var(--line));
  background:var(--card);color:var(--brand);font:inherit;font-size:12px;font-weight:700;
  border-radius:999px;padding:7px 10px;cursor:pointer;white-space:nowrap}
''', '', "删重复样式")

# 2. 权重角标变为可点按钮
rep('<span class="weight-badge hidden" id="weightBadge"></span>',
    '<button type="button" class="weight-badge hidden" id="weightBadge" title="点一下减 1 次权重"></button>',
    "红点改按钮")

rep('''.weight-badge{font-size:11px;font-weight:800;color:var(--bad);
  background:color-mix(in srgb,var(--bad) 15%,transparent);border-radius:999px;
  padding:4px 7px;line-height:1.1;min-width:20px;text-align:center}''',
    '''.weight-badge{font:inherit;font-size:11px;font-weight:800;color:var(--bad);
  background:color-mix(in srgb,var(--bad) 15%,transparent);border:0;border-radius:999px;
  padding:4px 8px;line-height:1.1;min-width:22px;text-align:center;cursor:pointer}
.weight-badge:active{transform:scale(.92)}''', "红点样式")

# 3. 单词区上移：底部留白加大
rep('box-shadow:var(--shadow);padding:36px 18px 40px;', 'box-shadow:var(--shadow);padding:20px 18px 58px;', "卡片内边距上移")
rep('.card{padding:15px 13px}', '.card{padding:12px 13px 42px}', "窄屏内边距")
rep('.card{padding:9px 12px;gap:5px}', '.card{padding:8px 12px 34px;gap:5px}', "矮屏内边距")

# 4. conf 加朗读开关
rep("let conf = Object.assign({ deck: 'core', deckChapter: {}, showByDefault: false }, load(LS_CONF, {}));",
    "let conf = Object.assign({ deck: 'core', deckChapter: {}, showByDefault: false, speak: true }, load(LS_CONF, {}));",
    "conf 加 speak")

# 5. 渲染时自动朗读 + 同步按钮
rep("""  $('meaningToggle').textContent = conf.showByDefault ? '释义开' : '释义关';
  $('meaningToggle').setAttribute('aria-pressed', String(!!conf.showByDefault));""",
    """  $('meaningToggle').textContent = conf.showByDefault ? '释义开' : '释义关';
  $('meaningToggle').setAttribute('aria-pressed', String(!!conf.showByDefault));
  $('speakToggle').textContent = conf.speak ? '朗读开' : '朗读关';
  $('speakToggle').setAttribute('aria-pressed', String(!!conf.speak));
  if (conf.speak && lastSpoken !== word.word) { lastSpoken = word.word; speak(word.word); }""",
    "渲染自动朗读")

rep("let speakCache = null;", "let speakCache = null;\nlet lastSpoken = '';", "加 lastSpoken")

# 6. 按钮事件 + 红点减权重
rep("""$('meaningToggle').onclick = () => {
  conf.showByDefault = !conf.showByDefault;
  save(LS_CONF, conf);
  revealed = null;
  renderStudy();
};""",
    """$('meaningToggle').onclick = () => {
  conf.showByDefault = !conf.showByDefault;
  save(LS_CONF, conf);
  revealed = null;
  renderStudy();
};
$('speakToggle').onclick = () => {
  conf.speak = !conf.speak;
  save(LS_CONF, conf);
  if (conf.speak) { const w = queue[idx]; if (w) speak(w.word); }
  renderStudy();
};
// 点红点：权重 -1，用于误判右滑后回退
$('weightBadge').onclick = event => {
  event.stopPropagation();
  const w = queue[idx];
  if (!w) return;
  const st = state[w.word];
  if (!st || !st.w) return;
  st.w = Math.max(0, st.w - 1);
  save(LS_STATE, state);
  renderStudy();
};""", "朗读/减权重事件")

# 7. 点单词：touchend 也读（移动端 click 可能不触发）
rep("""$('word').addEventListener('touchend', event => {
  event.stopPropagation();
  touchStart = null;      // 防止残留导致下一次手势误判
});""",
    """let wordTouchedAt = 0;
$('word').addEventListener('touchend', event => {
  event.stopPropagation();
  touchStart = null;      // 防止残留导致下一次手势误判
  const w = queue[idx];
  if (w) { wordTouchedAt = Date.now(); speak(w.word); }
});""", "触摸也朗读")

rep("""  event.stopPropagation();
  const w = queue[idx];
  if (w) speak(w.word);
});""",
    """  event.stopPropagation();
  if (Date.now() - wordTouchedAt < 500) return;   // touchend 已读过，避免读两遍
  const w = queue[idx];
  if (w) speak(w.word);
});""", "click 去重")

# 8. 导入导出带 speak
rep("conf: { deck: conf.deck, chapter: conf.chapter || 0, deckChapter: conf.deckChapter || {}, showByDefault: !!conf.showByDefault }",
    "conf: { deck: conf.deck, chapter: conf.chapter || 0, deckChapter: conf.deckChapter || {}, showByDefault: !!conf.showByDefault, speak: conf.speak !== false }",
    "导出带 speak")
rep("        conf.showByDefault = !!d.conf.showByDefault;",
    "        conf.showByDefault = !!d.conf.showByDefault;\n        if (typeof d.conf.speak === 'boolean') conf.speak = d.conf.speak;",
    "导入带 speak")

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
