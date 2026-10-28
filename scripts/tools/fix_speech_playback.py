# -*- coding: utf-8 -*-
"""修「听不到声音」：去掉会破坏引擎状态的自动预热，cancel 后延迟再播，加错误反馈。"""
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


old = """// 预热：先合成一个空串，把语音引擎初始化掉，第一次点词才不会卡半秒
function warmUpSpeech() {
  try {
    const synth = window.speechSynthesis;
    if (!synth) return;
    refreshVoice();
    const u = new SpeechSynthesisUtterance(' ');
    u.volume = 0;
    u.rate = 1;
    u.lang = 'en-US';
    if (speakVoice) u.voice = speakVoice;
    synth.speak(u);
  } catch (e) {}
}
if (window.speechSynthesis) {
  refreshVoice();
  window.speechSynthesis.onvoiceschanged = refreshVoice;
  warmUpSpeech();
  // 移动端首次触摸时再预热一次（部分浏览器要求用户手势后才初始化）
  document.addEventListener('touchstart', warmUpSpeech, { once: true, passive: true });
  document.addEventListener('click', warmUpSpeech, { once: true });
}
function speak(word) {
  try {
    const synth = window.speechSynthesis;
    if (!synth) return;
    if (!voiceReady) refreshVoice();
    if (synth.speaking || synth.pending) synth.cancel();
    const u = new SpeechSynthesisUtterance(word);
    u.lang = 'en-US';
    u.rate = 1;
    u.pitch = 1;
    u.volume = 1;
    if (speakVoice) u.voice = speakVoice;
    synth.speak(u);
  } catch (e) {}
}"""

new = """let speakBroken = false;
function speechFail(msg) {
  if (speakBroken) return;
  speakBroken = true;
  const el = $('speakWarn');
  if (el) {
    el.textContent = '发音不可用：' + msg + '（可换用系统浏览器打开）';
    el.classList.remove('hidden');
  }
}
if (window.speechSynthesis) {
  refreshVoice();
  window.speechSynthesis.onvoiceschanged = refreshVoice;
}
// 关键：不要提前 speak 预热。部分浏览器在没有用户手势时 speak 会让引擎进入
// 错误状态，之后所有朗读都静默失败——这正是「听不到声音」的原因。
function speak(word) {
  try {
    const synth = window.speechSynthesis;
    if (!synth) { speechFail('浏览器不支持语音合成'); return; }
    if (!word) return;
    if (!voiceReady) refreshVoice();
    if (synth.speaking || synth.pending) synth.cancel();
    const u = new SpeechSynthesisUtterance(word);
    u.lang = 'en-US';
    u.rate = 0.95;
    u.pitch = 1;
    u.volume = 1;
    if (speakVoice) u.voice = speakVoice;
    u.onerror = event => {
      const err = event && event.error;
      if (err && err !== 'interrupted' && err !== 'canceled') speechFail(err);
    };
    // cancel() 之后同一轮里立刻 speak() 会被部分浏览器丢掉，隔一帧再播
    setTimeout(() => {
      try { synth.speak(u); } catch (err) { speechFail(err.message || String(err)); }
    }, 30);
  } catch (e) {
    speechFail(e.message || String(e));
  }
}"""

rep(old, new, "朗读逻辑重写")

# 拖进度条时不朗读
rep("  if (conf.speak && lastSpoken !== word.word) { lastSpoken = word.word; speak(word.word); }",
    "  if (conf.speak && !dragging && lastSpoken !== word.word) { lastSpoken = word.word; speak(word.word); }",
    "拖动进度条不朗读")

# 发音失败提示条
rep('<div class="storage-warn hidden" id="storageWarn">',
    '<div class="storage-warn hidden" id="speakWarn"></div>\n<div class="storage-warn hidden" id="storageWarn">', "发音提示条")

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
