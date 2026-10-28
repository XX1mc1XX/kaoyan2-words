# -*- coding: utf-8 -*-
"""用 iframe 强制 360px 视口截图，验证手机端布局。"""
import io
import os
import subprocess
import tempfile

ROOT = r"c:\my_project\单词"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
built = io.open(os.path.join(ROOT, "software", "考研核心词.html"), encoding="utf-8").read()

frame = """<!doctype html><meta charset="utf-8">
<style>html,body{margin:0;background:#111}iframe{width:360px;height:740px;border:0;display:block}</style>
<iframe src="file:///__TARGET__"></iframe>"""

tmp_dir = tempfile.mkdtemp()
target = os.path.join(tmp_dir, "_shot_target.html").replace("\\", "/")
io.open(target, "w", encoding="utf-8").write(built)
frame_path = os.path.join(tmp_dir, "_shot_frame.html")
io.open(frame_path, "w", encoding="utf-8").write(frame.replace("__TARGET__", target))

for name in ("_shot_a.png",):
    out = os.path.join(ROOT, "output", name)
    if os.path.exists(out):
        os.remove(out)
    subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--window-size=360,740", "--virtual-time-budget=3000",
                    "--screenshot=" + out, "file:///" + frame_path.replace("\\", "/")],
                   capture_output=True, timeout=90)
    print(name, os.path.exists(out))
