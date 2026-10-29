// ---- 订阅：谁需要响应数据变化，就在这里登记，不再散落在各处 ----
bus.on('data:change', () => {
  if (applyingRemote) return;
  noteLocalChange();
  scheduleCloudSync();
});
bus.on('data:change', () => updateStats());
bus.on('deck:change', () => {
  renderChapters();
  updateDeckMeta();
  // 统计按「当前词书」算，统计页开着时切词书必须跟着重算，
  // 否则数字还停在上一个词库上。
  updateStats();
});

// ---- 错误上报 ----
// 线上出问题时至少要有能看到堆栈的收敛点；不落库，只进 Worker 日志。
let loggedErrors = 0;
function reportError(message, source, stack) {
  if (loggedErrors >= 5) return;   // 单页最多报 5 条，避免刷屏和打满限流
  loggedErrors += 1;
  try {
    console.error('[ky]', message, source, stack);
    if (location.protocol === 'file:') return;
    api('/log', {
      method: 'POST',
      body: {
        message: String(message == null ? '' : message).slice(0, 300),
        source: String(source || '').slice(0, 200),
        stack: String(stack || '').slice(0, 1200),
      },
    }).catch(() => {});
  } catch {}
}
window.addEventListener('error', event => {
  reportError(event.message, event.filename || '', event.error && event.error.stack);
});
window.addEventListener('unhandledrejection', event => {
  const reason = event.reason;
  reportError(reason && reason.message ? reason.message : String(reason),
    'unhandledrejection', reason && reason.stack);
});

