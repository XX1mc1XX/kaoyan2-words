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

// 复制来自 JSON 的普通对象时同样绕开 __proto__，并让结果回到干净的原型。
function copyRecord(records) {
  const out = {};
  if (!isRecord(records)) return out;
  for (const [key, value] of Object.entries(records)) {
    if (key === '__proto__') continue;
    safeSet(out, key, value);
  }
  return out;
}

function normalizeOperationId(value) {
  const id = typeof value === 'string' ? value.trim() : '';
  return /^[A-Za-z0-9._:-]{8,96}$/.test(id) ? id : '';
}

// fence 时间只接受正数；客户端时钟超前时最多夹到服务端当前时刻。
// 关键：不能反过来用 now - 24h 抬高低界。设备离线超过一天再同步时，
// 那会把合法的 resetAt 改成更晚时刻，连带删掉清空之后的新学习记录。
function serverTimestamp(value, now) {
  const at = Number(value);
  if (!Number.isFinite(at) || at <= 0) return 0;
  const ceiling = Number(now);
  return Number.isFinite(ceiling) && ceiling > 0 ? Math.min(at, ceiling) : at;
}

function resolveResetFence(resetAt, now) {
  const current = serverTimestamp(now) || Date.now();
  return serverTimestamp(resetAt, current) || current;
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
    // 时间打平时必须以 winner 的 icon 为准，哪怕它是 null：
    // 用 `??` 会把「winner 主动恢复默认图标（icon:null）」跳过，退回另一端的旧图标。
    // 只有 winner 根本没有这个字段（老数据）时才借用另一端的。
    const icon = aIconAt === bIconAt
      ? (winner.icon === undefined ? other.icon : winner.icon)
      : (aIconAt > bIconAt ? a.icon : b.icon);
    out.icon = (icon && typeof icon === 'object') ? icon : null;
    out.iconAt = Math.max(aIconAt, bIconAt);
  }
  // fence 是服务端的安全元数据，不能跟着普通 conf 的「位置赢家」漂移。
  // serverFenceAt 只由破坏性操作写入；历史快照只有 clear 的 resetAt，按兼容 fence 读取。
  const explicitA = serverTimestamp(a.serverFenceAt);
  const explicitB = serverTimestamp(b.serverFenceAt);
  const explicit = explicitA || explicitB
    ? (explicitA > explicitB
      ? { at: explicitA, mode: a.serverFenceMode === 'import' ? 'import' : 'clear',
        operationId: normalizeOperationId(a.serverFenceOperationId) }
      : { at: explicitB, mode: b.serverFenceMode === 'import' ? 'import' : 'clear',
        operationId: normalizeOperationId(b.serverFenceOperationId) })
    : { at: 0, mode: '' };
  if (explicit.at) {
    out.serverFenceAt = explicit.at;
    out.serverFenceMode = explicit.mode;
    if (explicit.mode === 'import') {
      out.resetAt = 0;
      if (explicit.operationId) out.serverFenceOperationId = explicit.operationId;
      else delete out.serverFenceOperationId;
    } else {
      out.resetAt = explicit.at;
      delete out.serverFenceOperationId;
    }
  } else {
    const legacyReset = Math.max(serverTimestamp(a.resetAt), serverTimestamp(b.resetAt));
    if (legacyReset) out.resetAt = legacyReset;
    else delete out.resetAt;
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

// reset/import 的持久 fence 与具体数据分开保存：
// - serverFenceAt 由 Worker 用服务端权威时间生成，客户端只负责原样回传；
// - serverFenceMode 区分 clear 与 import，不能把 import 当成长期 clear；
// - 旧数据只有 conf.resetAt 时继续按 clear fence 解释。
function readServerFence(snapshot) {
  const s = isRecord(snapshot) ? snapshot : {};
  const conf = isRecord(s.conf) ? s.conf : {};
  const explicit = serverTimestamp(conf.serverFenceAt);
  if (explicit) {
    return {
      at: explicit,
      mode: conf.serverFenceMode === 'import' ? 'import' : 'clear',
      operationId: normalizeOperationId(conf.serverFenceOperationId),
    };
  }
  const legacy = serverTimestamp(conf.resetAt);
  return { at: legacy, mode: legacy ? 'clear' : '', operationId: '' };
}

// fence 只能前进不能回退；同毫秒的连续操作由 serverFenceMode 表示最新类型，
// 不再人为 +1，避免把紧接着 import 写入的新记录误判成 fence 之前的数据。
function nextServerFence(cloud, mode, resetAt, now, importStartedAt, operationId) {
  const current = serverTimestamp(now) || Date.now();
  const existing = readServerFence(cloud);
  const importAt = serverTimestamp(importStartedAt, current);
  const requested = mode === 'import'
    ? (importAt || current)
    : resolveResetFence(resetAt, current);
  return {
    at: Math.max(requested, existing.at),
    mode: mode === 'import' ? 'import' : 'clear',
    operationId: mode === 'import' ? normalizeOperationId(operationId) : '',
  };
}

function withServerFence(snapshot, at, mode, operationId) {
  const source = isRecord(snapshot) ? snapshot : {};
  const fenceAt = serverTimestamp(at);
  if (!fenceAt) return source;
  const out = copyRecord(source);
  const conf = copyRecord(source.conf);
  const fenceMode = mode === 'import' ? 'import' : 'clear';
  conf.serverFenceAt = fenceAt;
  conf.serverFenceMode = fenceMode;
  delete conf.serverFenceOperationId;
  if (fenceMode === 'import') {
    const id = normalizeOperationId(operationId);
    if (id) conf.serverFenceOperationId = id;
  }
  // import 的权威数据可以保留旧 t，因此不能复用 resetAt 作为记录时间过滤器。
  // resetAt 专门表示 clear；import 只使用独立的 serverFenceAt/Mode。
  if (fenceMode === 'clear') {
    // nextServerFence 已保证 fenceAt 不低于旧的 clear fence；这里写成同一个
    // 权威值，避免导入文件或旧客户端携带的 resetAt 把 legacy 字段带到未来。
    conf.resetAt = fenceAt;
  } else {
    conf.resetAt = 0;
  }
  out.conf = conf;
  return out;
}

// 清空 / 导入时客户端这份优先，但旧墓碑不能用旧时钟覆盖另一台设备
// 在 fence 之后刚写下的 live 记录。时间戳更高的 live 记录必须胜出。
function preferPayload(merged, payload, force) {
  const out = { ...merged };
  for (const field of ['state', 'chapterData', 'daily']) {
    const src = isRecord(payload && payload[field]) ? payload[field] : {};
    const dst = copyRecord(out[field]);
    for (const [key, rec] of Object.entries(src)) {
      if (key === '__proto__' || !isRecord(rec)) continue;
      const base = dst[key];
      const incomingT = Number(rec && rec.t) || 0;
      const baseT = Number(base && base.t) || 0;
      // force 允许 import 的同键旧数据覆盖云端 live，但任何情况下都不能让
      // 未通过 fence 的旧 live 记录覆盖服务端刚生成的更新墓碑。
      if (!force && isRecord(base) && baseT > incomingT) continue;
      if (force && isRecord(base) && isTombstone(base) && !isTombstone(rec) && baseT > incomingT) continue;
      safeSet(dst, key, rec);
    }
    out[field] = dst;
  }
  return out;
}

// 把普通同步请求按持久 fence 过一遍。clear 直接按记录 t 截断；
// import 额外允许「云端已经接受过的同键旧数据」，因为备份里的旧 t 是合法内容。
// 云端没有、且 t 不晚于 import fence 的键，只能是旧设备带来的未选记录，必须墓碑化。
function applyResetFence(snapshot, fence, baseline) {
  const info = isRecord(fence)
    ? { at: serverTimestamp(fence.at !== undefined ? fence.at : fence.resetAt), mode: fence.mode }
    : { at: serverTimestamp(fence), mode: 'clear' };
  const at = info.at;
  if (!at) return snapshot;
  const mode = info.mode === 'import' ? 'import' : 'clear';
  const s = isRecord(snapshot) ? snapshot : {};
  const base = isRecord(baseline) ? baseline : {};
  const out = copyRecord(s);
  for (const field of ['state', 'chapterData', 'daily']) {
    const records = isRecord(s[field]) ? s[field] : {};
    const accepted = isRecord(base[field]) ? base[field] : {};
    const clean = {};
    for (const [key, rec] of Object.entries(records)) {
      if (key === '__proto__') continue;
      const stamp = Number(rec && rec.t) || 0;
      const acceptedByImport = mode === 'import'
        && Object.prototype.hasOwnProperty.call(accepted, key)
        && isRecord(accepted[key]);
      if (mode === 'import' && stamp <= at) {
        // import 选中的旧记录已在云端快照里；另一台旧设备同键的旧状态
        // 不能靠更大的旧时钟覆盖它。fence 之后的新记录仍按 t 正常合并。
        if (acceptedByImport) safeSet(clean, key, accepted[key]);
        else if (isTombstone(rec)) safeSet(clean, key, rec);
        else safeSet(clean, key, tombstone(at));
      } else if (isTombstone(rec) || stamp > at) {
        safeSet(clean, key, rec);
      } else {
        safeSet(clean, key, tombstone(at));
      }
    }
    out[field] = clean;
  }
  return out;
}

// 「清空全部 / 导入覆盖」要删的键，服务端知道得比客户端全。
// 只在客户端写墓碑会漏掉「只在别的设备上出现过」的词，下次合并又原样活过来，
// 所以真正生效的墓碑由服务端在这一份云端快照上生成。
// keep 是本次 import 明确选中的快照；这些键先保留，再由覆盖规则处理。
function tombstoneAll(snapshot, now, keep) {
  const t = Number(now) || Date.now();
  const kept = isRecord(keep) ? keep : {};
  const s = isRecord(snapshot) ? snapshot : {};
  const mark = field => {
    const records = isRecord(s[field]) ? s[field] : {};
    const selected = isRecord(kept[field]) ? kept[field] : {};
    const out = {};
    for (const [key, rec] of Object.entries(records)) {
      if (key === '__proto__') continue;
      const stamp = Number(rec && rec.t) || 0;
      const keepRecord = Object.prototype.hasOwnProperty.call(selected, key)
        && isRecord(selected[key]);
      // 清空只删除 fence 之前的历史记录；fence 之后另一台设备的新进度必须保留。
      // import 选中的同键记录例外，否则备份里的旧 t 会在覆盖时被误删。
      out[key] = isTombstone(rec) || stamp > t ? rec : (keepRecord ? rec : tombstone(t));
    }
    return out;
  };
  return {
    state: mark('state'),
    chapterData: mark('chapterData'),
    daily: mark('daily'),
    conf: isRecord(s.conf) ? copyRecord(s.conf) : {},
  };
}

// import 是整份覆盖，而不是普通双向合并：payload 中明确出现的键（包括旧 t）
// 全部视为用户选中的权威内容；云端独有的历史键在 fence 处墓碑化。
// 之后普通同步再用 serverFenceMode='import' 拒绝旧设备独有的键复活。
function mergeImportSnapshot(local, cloud, fenceAt) {
  const l = isRecord(local) ? local : {};
  const c = isRecord(cloud) ? cloud : {};
  const at = serverTimestamp(fenceAt) || Date.now();
  const overwrite = field => {
    const src = isRecord(l[field]) ? l[field] : {};
    const base = isRecord(c[field]) ? c[field] : {};
    const out = {};
    // 先完整保留导入文件明确列出的键，不能按旧 t 再筛一次。
    for (const [key, rec] of Object.entries(src)) {
      if (key === '__proto__' || !isRecord(rec)) continue;
      safeSet(out, key, rec);
    }
    // 未出现在导入文件中的云端键才是「本次覆盖要删除」的候选。
    for (const [key, rec] of Object.entries(base)) {
      if (key === '__proto__' || Object.prototype.hasOwnProperty.call(src, key)) continue;
      const stamp = Number(rec && rec.t) || 0;
      // 操作发起后才在别的设备学到的词，不应被迟到的 import 请求删掉。
      safeSet(out, key, isTombstone(rec) || stamp > at ? rec : tombstone(at));
    }
    return out;
  };
  const out = copyRecord(l);
  out.state = pruneTombstones(overwrite('state'), at);
  out.chapterData = pruneTombstones(overwrite('chapterData'), at);
  out.daily = overwrite('daily');
  // 导入文件里的 conf 是本次覆盖的权威配置；服务端 fence 随后单独写入。
  out.conf = isRecord(l.conf) ? copyRecord(l.conf) : copyRecord(c.conf);
  return out;
}

// 破坏性操作（clear/import）的共享入口。
// resetAt 对 clear 精确保留（只防止未来时间）；绝不再用 now-24h 抬高下界。
// import 不读取客户端 resetAt，而是建立独立的服务端 import fence。
function mergeDestructiveSnapshot(local, cloud, options) {
  const opt = isRecord(options) ? options : {};
  const mode = opt.mode === 'import' ? 'import' : 'clear';
  const now = serverTimestamp(opt.now) || Date.now();
  const operationId = mode === 'import' ? normalizeOperationId(opt.operationId) : '';
  const existing = readServerFence(cloud);
  if (mode === 'import' && operationId
      && existing.mode === 'import' && existing.operationId === operationId) return copyRecord(cloud);
  const requestedAt = mode === 'import'
    ? serverTimestamp(opt.importStartedAt, now)
    : serverTimestamp(opt.resetAt, now);
  // ?????????????????? clear/import fence?
  if (existing.at && requestedAt && existing.at > requestedAt) return copyRecord(cloud);
  const fence = nextServerFence(cloud, mode, opt.resetAt, now, opt.importStartedAt, operationId);
  if (mode === 'import') {
    const imported = mergeImportSnapshot(local, cloud, fence.at);
    return withServerFence(imported, fence.at, 'import', fence.operationId);
  }
  const incoming = applyResetFence(local, fence, cloud);
  const base = tombstoneAll(cloud, fence.at);
  let merged = mergeSnapshots(incoming, base);
  // clear 不能再用“客户端整份强制覆盖”：时钟慢的旧墓碑会删掉别的设备
  // 在 resetAt 之后刚写下的新记录。过滤后的同刻/更新记录由普通时间戳规则裁决。
  merged = preferPayload(merged, incoming, false);
  return withServerFence(merged, fence.at, 'clear');
}

// Worker 的同步主入口：普通同步也要先套用云端持久 fence，
// 否则某台离线很久的设备从未触发 reset 请求，却能把旧独有记录重新带回来。
// reset/import 请求则走独立的破坏性覆盖逻辑，并生成新的服务端 fence。
function mergeSyncSnapshot(local, cloud, options) {
  const opt = isRecord(options) ? options : {};
  if (opt.reset === true) return mergeDestructiveSnapshot(local, cloud, opt);
  const fence = readServerFence(cloud);
  if (!fence.at) return mergeSnapshots(local, cloud);
  const incoming = applyResetFence(local, fence, cloud);
  const merged = mergeSnapshots(incoming, cloud);
  return withServerFence(merged, fence.at, fence.mode, fence.operationId);
}
