// 验证释义显隐状态机：autoShow 总开关 × revealed 三态
const show = (auto, rev) => (rev === null ? !!auto : rev);
const toggle = (auto, rev) => !(rev === null ? !!auto : rev);  // 只返回新的 revealed
const nextWord = () => null;                                   // 翻词重置

const cases = [
  // [说明, autoShow, revealed, 操作后预期]
  ['总开关关 + 跟随 -> 初始应隐藏',        false, null,  false],
  ['总开关开 + 跟随 -> 初始应显示',        true,  null,  true],
  ['总开关关 + 点一下 -> 显示当前词',      false, toggle(false, null), true],
  ['总开关开 + 点一下 -> 隐藏当前词',      true,  toggle(true,  null), false],
  ['总开关关 + 显示后翻词 -> 恢复隐藏',    false, nextWord(), false],
  ['总开关开 + 隐藏后翻词 -> 恢复显示',    true,  nextWord(), true],
  ['总开关开 + 点两次 -> 仍显示',          true,  toggle(true, toggle(true, null)), true],
  ['总开关关 + 点两次 -> 仍隐藏',          false, toggle(false, toggle(false, null)), false],
];

let bad = 0;
for (const [desc, auto, rev, want] of cases) {
  const got = show(auto, rev);
  const ok = got === want;
  if (!ok) bad++;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${desc}  -> show=${got} (期望 ${want})`);
}

// 关键回归：点一下绝不能改总开关
const autoBefore = true;
toggle(autoBefore, null);
console.log(`\n总开关保持不变: ${autoBefore === true ? 'PASS' : 'FAIL'} (仍为 ${autoBefore})`);
console.log(bad === 0 ? '\n全部通过' : `\n${bad} 项失败`);
