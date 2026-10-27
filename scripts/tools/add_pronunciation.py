# -*- coding: utf-8 -*-
"""加单词发音：点单词朗读（Web Speech API，无需联网资源）。"""
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


# 1. 单词元素加可点击样式与提示
rep('.word{font-size:clamp(40px,11vw,64px);line-height:1.05;font-weight:800;letter-spacing:-.025em;word-break:break-word;max-width:100%}',
    '.word{font-size:clamp(40px,11vw,64px);line-height:1.05;font-weight:800;letter-spacing:-.025em;\n'
    '  word-break:break-word;max-width:100%;cursor:pointer;transition:opacity .15s}\n'
    '.word:active{opacity:.6}\n'
    '.word::after{content:"🔊";font-size:.32em;margin-left:.28em;opacity:.28;vertical-align:super;font-weight:400}',
    "单词样式加发音提示")

# 2. 发音函数
rep("function toggleMeaning() {",
    """let speakCache = null;
function speak(word) {
  try {
    if (!window.speechSynthesis) return;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(word);
    u.lang = 'en-US';
    u.rate = 0.92;
    // 优先选英语母语发音
    const voices = window.speechSynthesis.getVoices() || [];
    const en = voices.find(v => /en[-_]US/i.test(v.lang) && /google|samantha|natural/i.test(v.name))
            || voices.find(v => /en[-_]US/i.test(v.lang))
            || voices.find(v => /^en/i.test(v.lang));
    if (en) u.voice = en;
    window.speechSynthesis.speak(u);
  } catch (e) {}
}
function toggleMeaning() {""", "发音函数")

# 3. 点单词触发发音（不触发翻面）
rep("""$('chapterSelect').onchange = event => gotoChapter(Number(event.target.value));""",
    """$('chapterSelect').onchange = event => gotoChapter(Number(event.target.value));
// 点单词朗读；阻止冒泡避免触发卡片的翻面
$('word').addEventListener('click', event => {
  event.stopPropagation();
  const w = queue[idx];
  if (w) speak(w.word);
});
$('word').addEventListener('touchend', event => {
  event.stopPropagation();
});""", "点单词朗读")

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
