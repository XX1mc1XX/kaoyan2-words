// 进度合并的唯一实现：Worker 与前端都从这里注入，禁止各自再写一份。
// 本文件是「脚本片段」，不要写 import/export —— 两边都不是模块上下文。

// 每日节奏只保留最近 120 天
const MERGE_DAILY_KEEP_DAYS = 120;
// 墓碑（删除标记）保留天数。超过之后删除记录被清掉以控制 payload 体积；
// 离线超过这个天数的设备再同步，理论上能把旧词带回来，用一年换体积上限。
const TOMBSTONE_KEEP_DAYS = 400;

// 删除用墓碑表达：{ del: 1, t: 删除时间 }。
// 逐词合并必须能表达「删」这个动作，否则一端清空后另一端会把词拼回来。
function isTombstone(rec) {
  return !!rec && typeof rec === 'object' && rec.del === 1;
}

function tombstone(now) {
  return { del: 1, t: Number(now) || Date.now() };
}

// 键名来自 JSON，直接 obj['__proto__'] = x 会改掉结果对象的原型，
// 表现为「合并后多出幽灵词」或「明明有的词查不到」。
function safeSet(obj, key, value) {
  if (key === '__proto__') return;
  obj[key] = value;
}

// 记录可能来自老版本或手改的备份，null / 字符串 / 数组都可能出现，
// 一律当成「这一端没有这条记录」，别让合并因为一条脏数据整份 500。
function isRecord(v) {
  return !!v && typeof v === 'object' && !Array.isArray(v);
}

// 键排序后的 JSON：合并结果的键序取决于「本机键序 + 云端补充键序」，
// 用原始字节比较会让两台设备交替同步时每次都判定「有变化」，
// 于是每次都重写 updated_at，另一台的 since 轮询永远失效。
function stableJson(value) {
  const norm = v => {
    if (v === null || typeof v !== 'object') return v;
    if (Array.isArray(v)) return v.map(norm);
    const out = {};
    for (const k of Object.keys(v).sort()) {
      if (k === '__proto__') continue;
      safeSet(out, k, norm(v[k]));
    }
    return out;
  };
  try { return JSON.stringify(norm(value)); } catch { return null; }
}

// 单个词的记录合并：时间戳较新的胜出，删除参与同一套时间比较。
// 时间相同（老数据没有 t）时掌握优先、权重与到期时间取大。
function mergeWordRecord(a, b) {
  if (!isRecord(a)) return isRecord(b) ? b : undefined;
  if (!isRecord(b)) return a;
  const aDel = isTombstone(a), bDel = isTombstone(b);
  const ta = Number(a.t) || 0, tb = Number(b.t) || 0;
  if (aDel || bDel) {
    if (ta !== tb) return ta > tb ? a : b;
    // 同一毫秒：删除是明确的用户动作，优先保留删除
    return aDel ? a : b;
  }
  if (ta !== tb) return tb > ta ? b : a;
  if (!!a.mastered !== !!b.mastered) return a.mastered ? a : b;
  // 时间相同（老数据）：权重与到期取大，但为 0 就不要把键重新写回去，
  // 否则 snapshot() 省下来的字段又被合并加回来，payload 白胖一圈。
  const w = Math.max(a.w | 0, b.w | 0);
  const due = Math.max(Number(a.due) || 0, Number(b.due) || 0);
  const out = { ...a };
  if (w) out.w = w; else delete out.w;
  if (due) out.due = due; else delete out.due;
  return out;
}

function mergeState(local, cloud) {
  const out = {};
  const l = local || {}, c = cloud || {};
  for (const k of new Set([...Object.keys(l), ...Object.keys(c)])) {
    const merged = mergeWordRecord(l[k], c[k]);
    if (merged !== undefined) safeSet(out, k, merged);
  }
  return out;
}

function mergeChapterRecord(a, b) {
  if (!isRecord(a)) return isRecord(b) ? b : undefined;
  if (!isRecord(b)) return a;
  const aDel = isTombstone(a), bDel = isTombstone(b);
  const ta = Number(a.t) || 0, tb = Number(b.t) || 0;
  if (aDel || bDel) {
    if (ta !== tb) return ta > tb ? a : b;
    return aDel ? a : b;
  }
  if (ta !== tb) return tb > ta ? b : a;
  const pa = (a.order || []).length ? (a.pos || 0) : 0;
  const pb = (b.order || []).length ? (b.pos || 0) : 0;
  return pa >= pb ? a : b;
}

function mergeChapters(local, cloud) {
  const out = {};
  const l = local || {}, c = cloud || {};
  for (const k of new Set([...Object.keys(l), ...Object.keys(c)])) {
    const merged = mergeChapterRecord(l[k], c[k]);
    if (merged !== undefined) safeSet(out, k, merged);
  }
  return out;
}

// 每日学习节奏：两端是同一份进度的快照，不能相加。
// 带 t 时按 t 取新（撤销才能生效），任一端是老数据时才退回取大。
function mergeDailyRecord(a, b) {
  if (!isRecord(a)) return isRecord(b) ? b : undefined;
  if (!isRecord(b)) return a;
  const aDel = isTombstone(a), bDel = isTombstone(b);
  const ta = Number(a.t) || 0, tb = Number(b.t) || 0;
  if (aDel || bDel) {
    if (ta !== tb) return ta > tb ? a : b;
    return aDel ? a : b;
  }
  if (ta && tb && ta !== tb) return tb > ta ? b : a;
  return {
    s: Math.max(a.s | 0, b.s | 0),
    m: Math.max(a.m | 0, b.m | 0),
    t: Math.max(ta, tb),
  };
}

function mergeDaily(local, cloud, todayTs) {
  const out = {};
  const base = Number(todayTs) || Date.now();
  // 客户端按「本地零点」算窗口，服务端只能按 UTC 毫秒算，两者差几个小时。
  // 服务端多留一天，才不会把客户端边界那天剪掉又被客户端加回来、每轮多写一次库。
  const keep = Number(todayTs) ? MERGE_DAILY_KEEP_DAYS : MERGE_DAILY_KEEP_DAYS + 1;
  const cut = base - (keep - 1) * 864e5;
  const l = local || {}, c = cloud || {};
  for (const key of new Set([...Object.keys(l), ...Object.keys(c)])) {
    if (key === '__proto__') continue;
    const ts = new Date(key + 'T00:00:00').getTime();
    if (!Number.isFinite(ts) || ts < cut) continue;
    const merged = mergeDailyRecord(l[key], c[key]);
    if (merged !== undefined) safeSet(out, key, merged);
  }
  return out;
}

function latestChapterTime(chapterData) {
  let latest = 0;
  for (const rec of Object.values(chapterData || {})) {
    latest = Math.max(latest, Number(rec && rec.t) || 0);
  }
  return latest;
}

// 这一端「真的在学习」的最近时间：词进度和当天节奏里最大的 t。
// 用来判断位置该听谁的，比只看 progressAt 更接近用户体感。
function latestActivity(state, daily) {
  let latest = 0;
  for (const rec of Object.values(state || {})) {
    if (isTombstone(rec)) continue;
    latest = Math.max(latest, Number(rec && rec.t) || 0);
  }
  for (const rec of Object.values(daily || {})) {
    if (isTombstone(rec)) continue;
    latest = Math.max(latest, Number(rec && rec.t) || 0);
  }
  return latest;
}

function mergeConf(local, cloud, localChapters, cloudChapters, localActivityAt, cloudActivityAt) {
  const a = isRecord(local) ? local : {};
  const b = isRecord(cloud) ? cloud : {};
  // conf.progressAt 是用户「切库 / 切章 / 翻词」动作的权威时间；
  // 章节记录里的 t 会包含程序化恢复，不能拿来反推当前该用哪本词书。
  let localAt = Number(a.progressAt) || 0;
  let cloudAt = Number(b.progressAt) || 0;
  if (!localAt && !cloudAt) {
    // 兼容旧数据：只有完全没有位置时间时，才退回章节活动时间。
    localAt = latestChapterTime(localChapters);
    cloudAt = latestChapterTime(cloudChapters);
  }
  // 位置时间打平时，谁真正背过词听谁的：只切了个章的一端不该抢走位置
  const chooseCloud = cloudAt === localAt
    ? (Number(cloudActivityAt) || 0) > (Number(localActivityAt) || 0)
    : cloudAt > localAt;
  const winner = chooseCloud ? b : a;
  const other = chooseCloud ? a : b;
  const deck = winner.deck || other.deck || 'core';
  const deckChapter = { ...(other.deckChapter || {}), ...(winner.deckChapter || {}) };
  delete deckChapter.__proto__;
  // winner.chapter 是最后一次落盘时所在的章，比 deckChapter 里的旧值新。
  // 老快照 / 手改的导入文件里可能是字符串，统一转成整数再判断。
  const asChapter = v => (v === null || v === undefined || v === '')
    ? null
    : (Number.isInteger(Number(v)) ? Number(v) : null);
  const chapter = asChapter(winner.chapter) ?? asChapter(deckChapter[deck]) ?? 0;
  // 两者必须一致，否则恢复时前端会从另一边读到别的章
  deckChapter[deck] = chapter;
  const out = { ...other, ...winner, deck, chapter, deckChapter, progressAt: Math.max(localAt, cloudAt) };
  // 图标是本机偏好，不能跟着「位置时间」走：游客从没设过图标时 icon 是 null，
  // 用整对象仲裁会把账号那边的自定义图标一起洗成默认。
  const aIconAt = Number(a.iconAt) || 0;
  const bIconAt = Number(b.iconAt) || 0;
  if (aIconAt || bIconAt) {
    const icon = aIconAt === bIconAt
      ? (winner.icon ?? other.icon)
      : (aIconAt > bIconAt ? a.icon : b.icon);
    out.icon = (icon && typeof icon === 'object') ? icon : null;
    out.iconAt = Math.max(aIconAt, bIconAt);
  }
  delete out.forceAt;   // 删除改用墓碑表达后，这个字段已经没有语义
  return out;
}

// 合并两份完整快照。删除由墓碑表达，因此不再需要「谁清空过就整份覆盖」的特殊分支。
function mergeSnapshots(local, cloud) {
  const l = local || {};
  const c = cloud || {};
  const merged = {
    state: mergeState(l.state, c.state),
    chapterData: mergeChapters(l.chapterData, c.chapterData),
    daily: mergeDaily(l.daily, c.daily),
    conf: mergeConf(l.conf, c.conf, l.chapterData, c.chapterData,
      latestActivity(l.state, l.daily), latestActivity(c.state, c.daily)),
  };
  return {
    ...merged,
    state: pruneTombstones(merged.state),
    chapterData: pruneTombstones(merged.chapterData),
  };
}

// 清掉过老的删除标记，避免 payload 被永久撑大
function pruneTombstones(records, now, keepDays) {
  const cut = (Number(now) || Date.now()) - (Number(keepDays) || TOMBSTONE_KEEP_DAYS) * 864e5;
  const out = {};
  for (const [key, rec] of Object.entries(records || {})) {
    if (key === '__proto__') continue;
    if (isTombstone(rec) && (Number(rec.t) || 0) < cut) continue;
    out[key] = rec;
  }
  return out;
}

// 清空 / 导入时客户端这份就是权威：它有的键一律以它为准。
// 只靠墓碑时间戳裁决不够——两台设备的时钟差几秒，
// 就会把「清空之后马上又背的几个词」当成旧记录删掉。
function preferPayload(merged, payload) {
  const out = { ...merged };
  for (const field of ['state', 'chapterData', 'daily']) {
    const src = isRecord(payload && payload[field]) ? payload[field] : {};
    const dst = { ...(out[field] || {}) };
    for (const [key, rec] of Object.entries(src)) {
      if (key === '__proto__') continue;
      dst[key] = rec;
    }
    out[field] = dst;
  }
  return out;
}

// 「清空全部 / 导入覆盖」要删的键，服务端知道得比客户端全。
// 只在客户端写墓碑会漏掉「只在别的设备上出现过」的词，下次合并又原样活过来，
// 所以真正生效的墓碑由服务端在这一份云端快照上生成。
function tombstoneAll(snapshot, now) {
  const t = Number(now) || Date.now();
  const mark = records => {
    const out = {};
    for (const [key, rec] of Object.entries(records || {})) {
      if (key === '__proto__') continue;
      out[key] = isTombstone(rec) ? rec : tombstone(t);
    }
    return out;
  };
  const s = isRecord(snapshot) ? snapshot : {};
  return {
    state: mark(s.state),
    chapterData: mark(s.chapterData),
    daily: mark(s.daily),
    conf: isRecord(s.conf) ? s.conf : {},
  };
}
