# -*- coding: utf-8 -*-
"""引入极简事件总线（观察者模式），把「数据变化 → 统计 / 云同步」解耦成订阅。"""
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


# 1. 总线本体
rep('''const load = (key, fallback) =>''',
    '''// 极简事件总线（发布/订阅）：数据一变就广播，谁关心谁订阅，避免到处手动串调用
const bus = (() => {
  const subs = new Map();
  return {
    on(type, fn) {
      if (!subs.has(type)) subs.set(type, new Set());
      subs.get(type).add(fn);
      return () => subs.get(type).delete(fn);
    },
    emit(type, payload) {
      const set = subs.get(type);
      if (!set) return;
      for (const fn of [...set]) { try { fn(payload); } catch (e) {} }
    },
  };
})();
const load = (key, fallback) =>''', "事件总线")

# 2. save 只负责落盘 + 广播，不再硬编码云同步
rep('''    localStorage.setItem(key, JSON.stringify(value));
    try { localStorage.setItem(LS_STAMP, String(Date.now())); } catch {}
    scheduleCloudSync();''',
    '''    localStorage.setItem(key, JSON.stringify(value));
    try { localStorage.setItem(LS_STAMP, String(Date.now())); } catch {}
    bus.emit('data:change', key);''', "save 改为广播")

# 3. 统一在末尾订阅
rep('''refreshAuth();
</script>''',
    '''refreshAuth();

// ---- 订阅：谁需要响应数据变化，就在这里登记，不再散落在各处 ----
bus.on('data:change', () => scheduleCloudSync());
bus.on('data:change', () => updateStats());
bus.on('deck:change', () => {
  renderChapters();
  updateDeckMeta();
});
</script>''', "订阅登记")

# 4. 切词库时广播一次
rep('''  loadChapter(resume);
  renderChapters();
  updateStats();
  updateDeckMeta();''',
    '''  loadChapter(resume);
  bus.emit('deck:change');''', "切库广播")

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
