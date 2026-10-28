# -*- coding: utf-8 -*-
"""自动同步：登录后按词合并云端与本机，定时轮询，不再需要手动点上传/下载。"""
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


# 1. 每处改动 state 都盖时间戳，供合并时判断谁更新
rep("""  const st = state[word.word] || { w: 0, mastered: false, seen: 0 };
  st.seen = (st.seen || 0) + 1;""",
    """  const st = state[word.word] || { w: 0, mastered: false, seen: 0 };
  st.t = Date.now();
  st.seen = (st.seen || 0) + 1;""", "mark 打时间戳")

rep("""  st.w = Math.max(0, st.w - 1);
  save(LS_STATE, state);""",
    """  st.w = Math.max(0, st.w - 1);
  st.t = Date.now();
  save(LS_STATE, state);""", "降权重打时间戳")

rep("""  const st = state[word.word];
  if (st) { st.mastered = false; st.due = 0; save(LS_STATE, state); }
  queue = queue.filter(w => w.word !== word.word);""",
    """  const st = state[word.word];
  if (st) { st.mastered = false; st.due = 0; st.t = Date.now(); save(LS_STATE, state); }
  queue = queue.filter(w => w.word !== word.word);""", "恢复打时间戳")

rep("""    if (undoKind === 'restored') { st.mastered = true; st.due = todayTs() + 7 * DAY; }
    else { st.mastered = false; st.due = 0; }
    state[word.word] = st;""",
    """    if (undoKind === 'restored') { st.mastered = true; st.due = todayTs() + 7 * DAY; }
    else { st.mastered = false; st.due = 0; }
    st.t = Date.now();
    state[word.word] = st;""", "撤销打时间戳")

# 2. 替换 afterLogin / uploadProgress：合并式自动同步
rep("""async function uploadProgress(silent) {
  if (!authUser) return;
  syncing = true;
  try {
    await api('/state', { method: 'PUT', body: { payload: snapshot() } });
    if (!silent) authSay('已上传到云端', 'ok');
  } catch (e) {
    if (!silent) authSay(e.message, 'err');
  } finally {
    syncing = false;
  }
}""",
    """let pendingSync = false;
let lastSyncAt = 0;

// 按词合并：同一词取修改时间较新的那份，谁都不会被整体覆盖
function mergeState(local, cloud) {
  const out = {};
  const keys = new Set([...Object.keys(local || {}), ...Object.keys(cloud || {})]);
  for (const k of keys) {
    const a = (local || {})[k];
    const b = (cloud || {})[k];
    if (!a) { out[k] = b; continue; }
    if (!b) { out[k] = a; continue; }
    const ta = a.t || 0, tb = b.t || 0;
    if (tb !== ta) { out[k] = tb > ta ? b : a; continue; }
    // 都没有时间戳（老数据）：掌握优先，其次取更晚到期
    if (a.mastered !== b.mastered) { out[k] = a.mastered ? a : b; continue; }
    out[k] = { ...a, w: Math.max(a.w || 0, b.w || 0), due: Math.max(a.due || 0, b.due || 0) };
  }
  return out;
}
// 章节记录取更新更靠后的那份，超出范围的用本机
function mergeChapters(local, cloud) {
  const out = {};
  const keys = new Set([...Object.keys(local || {}), ...Object.keys(cloud || {})]);
  for (const k of keys) {
    const a = (local || {})[k];
    const b = (cloud || {})[k];
    if (!a) { out[k] = b; continue; }
    if (!b) { out[k] = a; continue; }
    const pa = (a.order || []).length ? (a.pos || 0) : 0;
    const pb = (b.order || []).length ? (b.pos || 0) : 0;
    out[k] = pa >= pb ? a : b;
  }
  return out;
}
function mergeSnapshots(local, cloud) {
  return {
    state: mergeState(local.state, cloud.state),
    chapterData: mergeChapters(local.chapterData, cloud.chapterData),
    conf: local.conf,
  };
}
function sameJson(a, b) {
  try { return JSON.stringify(a) === JSON.stringify(b); } catch { return false; }
}

async function putState(payload) {
  const r = await api('/state', { method: 'PUT', body: { payload } });
  lastSyncAt = r.updatedAt || Date.now();
  return r;
}

// 微信式：登录后自动双向合并，用户不需要点任何按钮
async function syncNow(quiet) {
  if (!authUser) return;
  if (syncing) { pendingSync = true; return; }
  syncing = true;
  try {
    const remote = await api('/state');
    const local = snapshot();
    if (!remote.payload) {
      await putState(local);
      if (!quiet) authSay('已把本机进度同步到云端', 'ok');
    } else {
      const merged = mergeSnapshots(local, remote.payload);
      const changedLocally = !sameJson(merged.state, local.state) || !sameJson(merged.chapterData, local.chapterData);
      if (changedLocally) applySnapshot(merged);
      await putState(merged);
      if (!quiet) authSay(changedLocally ? '已合并云端进度' : '进度已同步', 'ok');
    }
  } catch (e) {
    if (!quiet) authSay('同步失败：' + e.message, 'err');
  } finally {
    syncing = false;
    if (pendingSync) { pendingSync = false; scheduleCloudSync(); }
  }
}
const uploadProgress = quiet => syncNow(quiet);""", "合并式同步")

# 3. afterLogin 直接走自动同步
rep("""async function afterLogin(username) {
  authUser = username;
  renderAuth();
  authSay('已登录，正在比对云端进度…');
  try {
    const r = await api('/state');
    const localStamp = Number(localStorage.getItem(LS_STAMP) || 0);
    if (!r.payload) {
      await uploadProgress(true);
      authSay('已把本机进度上传到云端', 'ok');
    } else if (r.updatedAt > localStamp) {
      const words = Object.keys(r.payload.state || {}).length;
      authSay('云端有 ' + words + ' 个词的进度（较新）。点下面按钮选择保留哪一份。');
    } else {
      await uploadProgress(true);
      authSay('本机进度较新，已上传到云端', 'ok');
    }
  } catch (e) {
    authSay(e.message, 'err');
  }
}""",
    """async function afterLogin(username) {
  authUser = username;
  renderAuth();
  authSay('正在同步…');
  scheduleCloudSync(0);
}""", "登录后自动同步")

# 4. 定时轮询（微信式后台同步）
rep("// 微信扫码：需要开放平台网站应用资质，未配置时按钮保持禁用",
    """// 后台定时同步：每 40 秒，页面可见时静默合并一次
setInterval(() => {
  if (!authUser || document.visibilityState !== 'visible') return;
  syncNow(true);
}, 40000);
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && authUser) syncNow(true);
});

// 微信扫码：需要开放平台网站应用资质，未配置时按钮保持禁用""", "定时同步")

# 5. 登录后隐藏手动按钮，只留退出
rep("""      <button class="btn" id="syncUp">用本机进度覆盖云端</button>
      <button class="btn" id="syncDown">用云端进度覆盖本机</button>
      <button class="auth-switch danger-link" id="authLogout">退出登录</button>""",
    """      <div class="sync-note">进度会自动同步，不用手动操作</div>
      <button class="btn" id="syncNowBtn">立即同步</button>
      <button class="auth-switch danger-link" id="authLogout">退出登录</button>""", "简化同步按钮")

rep("""$('syncUp').onclick = () => uploadProgress(false);
$('syncDown').onclick = async () => {
  try {
    const r = await api('/state');
    if (!r.payload) { authSay('云端还没有进度', 'err'); return; }
    applySnapshot(r.payload);
    localStorage.setItem(LS_STAMP, String(Date.now()));
    save(LS_CONF, conf);
    authSay('已用云端进度覆盖本机', 'ok');
  } catch (e) {
    authSay(e.message, 'err');
  }
};""",
    """$('syncNowBtn').onclick = () => syncNow(false);""", "立即同步按钮")

rep(".auth-pair{display:flex;flex-direction:column;gap:8px}",
    """.auth-pair{display:flex;flex-direction:column;gap:8px}
.sync-note{font-size:12px;color:var(--muted);text-align:center;line-height:1.5}""", "同步说明样式")

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
