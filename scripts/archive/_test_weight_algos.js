// 对比不同权重算法的"温和度"：权重高的应该更可能靠前，但不能霸榜
const N = 200, TRIALS = 3000;
const weights = Array.from({ length: N }, (_, i) => (i < 10 ? 4 : (i < 30 ? 1 : 0)));

const algos = {
  'A 当前 random^(1/(w+1))': w => Math.pow(Math.random(), 1 / (w + 1)),
  'B random + w*0.08':       w => Math.random() + w * 0.08,
  'C random + w*0.12':       w => Math.random() + w * 0.12,
  'D random^(1/(1+w*0.2))':  w => Math.pow(Math.random(), 1 / (1 + w * 0.2)),
  'E random^(1/(1+w*0.5))':  w => Math.pow(Math.random(), 1 / (1 + w * 0.5)),
};

for (const [name, fn] of Object.entries(algos)) {
  let sum = { 0: 0, 1: 0, 4: 0 }, cnt = { 0: 0, 1: 0, 4: 0 }, top = { 0: 0, 1: 0, 4: 0 };
  for (let t = 0; t < TRIALS; t++) {
    const arr = weights.map((w, i) => ({ i, w, k: fn(w) }));
    arr.sort((a, b) => b.k - a.k);
    arr.forEach((x, pos) => { sum[x.w] += pos; cnt[x.w]++; if (pos < N * 0.25) top[x.w]++; });
  }
  const avg = lv => (sum[lv] / cnt[lv]).toFixed(1);
  const pct = lv => ((top[lv] / cnt[lv]) * 100).toFixed(1);
  console.log(`${name}
   平均位次    w0=${avg(0)}  w1=${avg(1)}  w4=${avg(4)}   (中位 99.5)
   进前25%比例 w0=${pct(0)}%  w1=${pct(1)}%  w4=${pct(4)}%`);
}
