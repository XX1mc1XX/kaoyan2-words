# -*- coding: utf-8 -*-
"""降低朗读延迟：预热语音引擎、缓存音色、优先本地音色（在线 Natural 音色要联网合成，延迟大）。"""
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


old_block = """let speakCache = null;
let lastSpoken = '';
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
}"""

new_block = """let lastSpoken = '';
let speakVoice = null;
let voiceReady = false;
// 音色缓存：在线 Natural 音色每次合成要联网，延迟明显，优先选本地音色
function refreshVoice() {
  try {
    const synth = window.speechSynthesis;
    if (!synth) return;
    const voices = synth.getVoices() || [];
    if (!voices.length) return;
    const us = voices.filter(v => /en[-_]US/i.test(v.lang));
    const anyEn = voices.filter(v => /^en/i.test(v.lang));
    const pick = (list) => list.find(v => !/online|natural|network/i.test(v.name + ' ' + v.voiceURI))
                    || list[0];
    speakVoice = pick(us) || pick(anyEn) || null;
    voiceReady = true;
  } catch (e) {}
}
// 预热：先合成一个空串，把语音引擎初始化掉，第一次点词才不会卡半秒
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

rep(old_block, new_block, "朗读引擎优化")

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
