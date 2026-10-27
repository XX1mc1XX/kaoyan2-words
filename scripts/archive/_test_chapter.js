// 验证加权洗牌 + 章节队列逻辑
const CHAPTER_SIZE = 200;
const state = {};

const isMastered = w => !!(state[w] && state[w].mastered);
const weightOf = w => (state[w] ? (state[w].w || 0) : 0);

function shuffleByWeight(list) {
  const arr = list.map(word => ({ word, key: Math.pow(Math.random(), 1 / (weightOf(word) + 1)) }));
  arr.sort((a, b) => b.key - a.key);
  return arr.map(x => x.word);
}

// --- 1. 权重高的应显著靠前 ---
const words = Array.from({ length: 200 }, (_, i) => 'w' + i);
words.slice(0, 10).forEach(w => { state[w] = { w: 4, mastered: false }; });   // 高权重
words.slice(10, 30).forEach(w => { state[w] = { w: 1, mastered: false }; });  // 低权重

let sumHigh = 0, sumZero = 0, nHigh = 0, nZero = 0;
for (let t = 0; t < 200; t++) {
  const order = shuffleByWeight(words);
  order.forEach((w, pos) => {
    if (weightOf(w) === 4) { sumHigh += pos; nHigh++; }
    else if (weightOf(w) === 0) { sumZero += pos; nZero++; }
  });
}
const avgHigh = sumHigh / nHigh, avgZero = sumZero / nZero;
console.log(`权重4平均位次 ${avgHigh.toFixed(1)}  权重0平均位次 ${avgZero.toFixed(1)}  (理论中位 99.5)`);
console.log(avgHigh < avgZero - 40 ? 'PASS 权重高显著靠前' : 'FAIL 权重没起作用');

// --- 2. 左滑掌握后不再进队列 ---
function loadPending(slice) { return slice.filter(w => !isMastered(w)); }
state['w0'] = { w: 4, mastered: true };
const after = loadPending(words);
console.log(after.includes('w0') ? 'FAIL 已掌握的词还在队列' : 'PASS 已掌握的词被剔除');

// --- 3. 右滑权重累加 ---
function mark(word, known) {
  const st = state[word] || { w: 0, mastered: false, seen: 0 };
  st.seen = (st.seen || 0) + 1;
  if (known) st.mastered = true; else st.w = (st.w || 0) + 1;
  state[word] = st;
}
mark('w50', false); mark('w50', false); mark('w50', false);
console.log(weightOf('w50') === 3 ? 'PASS 右滑三次权重=3' : `FAIL 权重=${weightOf('w50')}`);
mark('w51', true);
console.log(isMastered('w51') ? 'PASS 左滑标记掌握' : 'FAIL 左滑没生效');

// --- 4. 全部掌握后 pending 为空 ---
const all = Array.from({ length: 200 }, (_, i) => 'w' + i);
all.forEach(w => { state[w] = state[w] || {}; state[w].mastered = true; });
console.log(loadPending(all).length === 0 ? 'PASS 全掌握后队列为空' : 'FAIL 队列未清空');
