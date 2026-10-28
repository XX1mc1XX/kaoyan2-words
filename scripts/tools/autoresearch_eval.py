# -*- coding: utf-8 -*-
"""autoresearch 评估器：输出结构化 JSON {pass, score, checks}。

用法：python scripts/tools/autoresearch_eval.py
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUILT = os.path.join(ROOT, "software", "考研核心词.html")
DECKS = ("words", "derivatives", "basic", "insurance")
STOP_CHARS = set("的了是在和与或也都很不有个这那之为以对从到把将被使于其")


def deck_rows():
    out = {}
    for d in DECKS:
        p = os.path.join(ROOT, "data", d + ".json")
        if os.path.exists(p):
            out[d] = json.load(io.open(p, encoding="utf-8"))
    return out


def load_ecdict(wanted):
    path = os.path.join(ROOT, "data", "ecdict.csv")
    tr = {}
    if not os.path.exists(path):
        return tr
    with io.open(path, encoding="utf-8", errors="replace", newline="") as f:
        r = csv.reader(f)
        next(r, None)
        for row in r:
            if len(row) > 3 and row[0].lower() in wanted:
                tr[row[0].lower()] = row[3]
    return tr


def run_tests():
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "tools", "run_tests.py")],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
    )
    tail = (r.stdout or "") + (r.stderr or "")
    m = re.search(r"通过\s+(\d+)\s*/\s*(\d+)", tail)
    if m:
        return int(m.group(1)), int(m.group(2))
    return 0, 0


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    checks = []
    data = deck_rows()

    # 1. 数据完整性
    total, words, dup, empty = 0, {}, [], []
    id_ok = True
    for d, rows in data.items():
        total += len(rows)
        if [x["id"] for x in rows] != list(range(1, len(rows) + 1)):
            id_ok = False
        for x in rows:
            if not (x.get("meaning") or "").strip():
                empty.append(x["word"])
            words.setdefault(x["word"], []).append(d)
    dup = [w for w, v in words.items() if len(v) > 1]

    checks.append({"name": "id 连续", "ok": id_ok, "weight": 0.5})
    checks.append({"name": "无空释义", "ok": not empty, "weight": 1.0, "detail": empty[:5]})
    checks.append({"name": "无重复词", "ok": not dup, "weight": 1.0, "detail": dup[:5]})
    checks.append({"name": "词数 > 3000", "ok": total > 3000, "weight": 0.5, "detail": "共 %d 词" % total})

    # 2. 释义与 ECDICT 一致性（零重合视为可疑）
    echo = load_ecdict(set(words))
    cjk = re.compile(r"[一-鿿]")
    compared, suspect = 0, []
    for w, decks in words.items():
        mine = next((x.get("meaning") or "" for x in data[decks[0]] if x["word"] == w), "")
        ecd = echo.get(w, "")
        if not mine or not ecd:
            continue
        a = {c for c in cjk.findall(mine) if c not in STOP_CHARS}
        b = {c for c in cjk.findall(ecd.split("[")[0]) if c not in STOP_CHARS}
        if not a or not b:
            continue
        compared += 1
        if not (a & b):
            suspect.append(w)
    ratio = len(suspect) / compared if compared else 1.0
    checks.append({
        "name": "释义可疑率 < 6%",
        "ok": ratio < 0.06,
        "weight": 2.0,
        "detail": "%d/%d = %.1f%%" % (len(suspect), compared, ratio * 100),
    })

    # 3. 产物体积
    size = os.path.getsize(BUILT) if os.path.exists(BUILT) else 0
    checks.append({"name": "体积 < 600KB", "ok": 0 < size < 600 * 1024, "weight": 1.0,
                   "detail": "%dKB" % (size // 1024)})

    # 4. 回归测试
    passed, tested = run_tests()
    checks.append({"name": "回归测试全过", "ok": tested > 0 and passed == tested, "weight": 3.0,
                   "detail": "%d/%d" % (passed, tested)})

    total_w = sum(c["weight"] for c in checks)
    got = sum(c["weight"] for c in checks if c["ok"])
    score = round(got / total_w, 4)
    result = {
        "pass": all(c["ok"] for c in checks),
        "score": score,
        "checks": checks,
        "metrics": {"words": total, "suspect_ratio": round(ratio, 4),
                    "suspect": len(suspect), "size_kb": size // 1024,
                    "tests": "%d/%d" % (passed, tested)},
    }
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
