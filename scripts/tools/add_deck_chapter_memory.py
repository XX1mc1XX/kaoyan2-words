# -*- coding: utf-8 -*-
"""每个词库记住各自上次所在的章节，切换词库不再回到第 1 章。"""
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


# 1. conf 增加每库章节映射
rep("let conf = Object.assign({ deck: 'core' }, load(LS_CONF, {}));",
    "let conf = Object.assign({ deck: 'core', deckChapter: {} }, load(LS_CONF, {}));",
    "conf 增加 deckChapter")

# 2. 切章时同时记录当前词库的章节
rep("""function gotoChapter(i) {
  savePos();
  conf.chapter = i;
  save(LS_CONF, conf);
  loadChapter(i);
}""",
    """function gotoChapter(i) {
  savePos();
  conf.chapter = i;
  conf.deckChapter = conf.deckChapter || {};
  conf.deckChapter[activeDeck] = i;
  save(LS_CONF, conf);
  loadChapter(i);
}""", "切章记录到当前词库")

# 3. 切词库时恢复该词库上次的章节
rep("""  loadChapter(0);
  renderChapters();
  updateStats();
  updateDeckMeta();""",
    """  const resume = (conf.deckChapter && conf.deckChapter[value]) || 0;
  conf.chapter = resume;
  save(LS_CONF, conf);
  loadChapter(resume);
  renderChapters();
  updateStats();
  updateDeckMeta();""", "切词库恢复各自章节")

# 4. 启动时也按词库恢复
rep("loadChapter(conf.chapter || 0);\nrenderChapters();",
    "loadChapter((conf.deckChapter && conf.deckChapter[activeDeck]) || conf.chapter || 0);\nrenderChapters();",
    "启动按词库恢复章节")

# 5. 导出/导入带上 deckChapter
rep("    conf: { deck: conf.deck, chapter: conf.chapter || 0 }",
    "    conf: { deck: conf.deck, chapter: conf.chapter || 0, deckChapter: conf.deckChapter || {} }",
    "导出带 deckChapter")
rep("        conf.chapter = d.conf.chapter || 0;",
    "        conf.chapter = d.conf.chapter || 0;\n        if (d.conf.deckChapter) conf.deckChapter = d.conf.deckChapter;",
    "导入带 deckChapter")

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
