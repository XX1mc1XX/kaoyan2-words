# -*- coding: utf-8 -*-
"""权重只显示数字；优先级徽章移到左上角并缩小，不再居中抢眼。"""
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


# 1. 徽章区挪到卡片左上角，不再占据居中位置
rep(".badges{display:flex;gap:6px;align-items:center;justify-content:center;flex-wrap:wrap}",
    ".badges{position:absolute;top:10px;left:10px;display:flex;gap:5px;align-items:center;z-index:2}",
    "徽章区移到左上角")

# 2. 优先级徽章缩小
rep(".priority{font-size:15px;font-weight:800;border-radius:999px;padding:7px 13px;line-height:1;letter-spacing:.02em}",
    ".priority{font-size:11px;font-weight:700;border-radius:999px;padding:4px 8px;line-height:1.1;letter-spacing:.02em}",
    "优先级徽章缩小")

# 3. 权重徽章只显示数字
rep(".weight-badge{font-size:11.5px;font-weight:800;color:var(--bad);\n  background:color-mix(in srgb,var(--bad) 15%,transparent);border-radius:999px;padding:6px 10px;line-height:1}",
    ".weight-badge{font-size:11px;font-weight:800;color:var(--bad);\n  background:color-mix(in srgb,var(--bad) 15%,transparent);border-radius:999px;\n  padding:4px 7px;line-height:1.1;min-width:20px;text-align:center}",
    "权重徽章样式")

# 4. 渲染时只写数字
rep("  wb.textContent = wt > 0 ? '错 ' + wt + ' 次' : '';",
    "  wb.textContent = wt > 0 ? String(wt) : '';", "权重只显示数字")

rep("      wb.textContent = '错 ' + st.w + ' 次';",
    "      wb.textContent = String(st.w);", "右滑反馈只显示数字")

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
