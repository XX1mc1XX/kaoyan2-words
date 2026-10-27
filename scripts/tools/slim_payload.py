# -*- coding: utf-8 -*-
"""精简打包字段（9 个前端不用的字段直接丢掉，省约 60% 体积）+ 删死代码。"""
import io

P = r"c:\my_project\单词\scripts\make_html.py"
t = io.open(P, encoding="utf-8").read()
log = []


def rep(old, new, label):
    global t
    if old in t:
        t = t.replace(old, new, 1)
        log.append("OK    " + label)
    else:
        log.append("MISS  " + label)


# 1. slim_rows 只保留前端真正用到的字段
old_slim = '''def slim_rows(source):
    return [
        {
            "id": r["id"],
            "word": r["word"],
            "family": r.get("family", ""),
            "meaning": r["meaning"],
            "forms": r.get("forms", []),
            "freq": r["freq"],
            "coverage": r["coverage"],
            "en1_freq": r.get("en1_freq", 0),
            "en1_coverage": r.get("en1_coverage", 0),
            "weighted_coverage": r.get("weighted_coverage", r["coverage"]),
            "book_rank": r.get("book_rank", 0),
            "source_tier": r.get("source_tier", ""),
            "band": r["band"],
            "priority": r.get("priority", ""),
            "priority_rank": r.get("priority_rank", r["id"]),
        }
        for r in source
    ]'''

new_slim = '''def slim_rows(source):
    """只打包前端真正读取的字段（见 template.html 实际引用）。"""
    return [
        {
            "id": r["id"],
            "word": r["word"],
            "family": r.get("family", ""),
            "meaning": r["meaning"],
            "forms": r.get("forms", []),
            "priority": r.get("priority", ""),
        }
        for r in source
    ]'''

rep(old_slim, new_slim, "精简打包字段 15->6")

# 2. finalize_html 是死代码（补丁的目标元素不存在）
old_fin = '''def finalize_html(html: str) -> str:
    """Ensure optional UI guards survive template edits."""
    if "if (!box) return;" not in html:
        html = html.replace(
            "function renderDisplayOpts() {\\n  const box = $('displayOpts');",
            "function renderDisplayOpts() {\\n  const box = $('displayOpts');\\n  if (!box) return;",
            1,
        )
    return html

'''
rep(old_fin, "", "删除 finalize_html 死代码")
rep("html = finalize_html(html)\n", "", "移除 finalize_html 调用")

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
