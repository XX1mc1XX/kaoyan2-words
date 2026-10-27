# -*- coding: utf-8 -*-
"""Embed the generated word list into the single-file mobile web app."""
from __future__ import annotations

import hashlib
import io
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOFT = ROOT / "software"
OUT = SOFT / "考研核心词.html"

rows = json.loads((DATA / "words.json").read_text(encoding="utf-8"))
derivatives = json.loads((DATA / "derivatives.json").read_text(encoding="utf-8"))
basic = json.loads((DATA / "basic.json").read_text(encoding="utf-8"))
insurance = json.loads((DATA / "insurance.json").read_text(encoding="utf-8"))
freq = json.loads((DATA / "ky2_freq.json").read_text(encoding="utf-8"))
ky1_path = DATA / "ky1_freq.json"
ky1 = json.loads(ky1_path.read_text(encoding="utf-8")) if ky1_path.exists() else {}
summary = json.loads((DATA / "selection_summary.json").read_text(encoding="utf-8"))

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

source_files = []
for exam, folder in (("english_2", "ky2"), ("english_1", "ky1")):
    folder_path = ROOT / "ref" / folder
    if not folder_path.exists():
        continue
    for path in sorted(folder_path.glob("*.pdf")):
        source_files.append({"exam": exam, "name": path.name, "sha256": sha256(path)})

meta = dict(freq.get("meta", {}))
meta.update({
    "generated_at": date.today().isoformat(),
    "selection_total": len(rows),
    "selection_bands": summary.get("bands", {}),
    "exam_weights": summary.get("weights", {"english_2": 1.0, "english_1": 0.35, "english_3": 0.0}),
    "english_1": ky1.get("meta", {}),
    "source_files": source_files,
})
def slim_rows(source):
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
    ]

slim = slim_rows(rows)
derivative_slim = slim_rows(derivatives)
basic_slim = slim_rows(basic)
insurance_slim = slim_rows(insurance)



template = (SOFT / "template.html").read_text(encoding="utf-8")
payload = json.dumps(slim, ensure_ascii=False, separators=(",", ":"))
derivative_payload = json.dumps(derivative_slim, ensure_ascii=False, separators=(",", ":"))
basic_payload = json.dumps(basic_slim, ensure_ascii=False, separators=(",", ":"))
insurance_payload = json.dumps(insurance_slim, ensure_ascii=False, separators=(",", ":"))
html = (
    template.replace("__DATA__", payload)
    .replace("__DERIVATIVES__", derivative_payload)
    .replace("__BASIC__", basic_payload)
    .replace("__INSURANCE__", insurance_payload)
    .replace("__META__", json.dumps(meta, ensure_ascii=False, separators=(",", ":")))
)
OUT.write_text(html, encoding="utf-8", newline="\n")

print(f"output={OUT}")
print(f"words={len(slim)} derivatives={len(derivative_slim)} basic={len(basic_slim)} insurance={len(insurance_slim)} size={OUT.stat().st_size / 1024:.0f}KB")
