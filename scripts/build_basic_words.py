# -*- coding: utf-8 -*-
"""Build a separate list of basic words removed from the core list, plus PDF/CSV."""
from __future__ import annotations

import csv
import io
import json
import os
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT / "scripts"))
from build_words import HARD_BASIC, STOP, clean_meaning  # noqa: E402

DATA_JSON = DATA / "basic_removed_words.json"
DATA_CSV = DATA / "basic_removed_words.csv"
PDF_OUT = OUT / "考研英语二_初高中基础词_已移出核心表.pdf"


def load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def load_books():
    out = {}
    for path in sorted((ROOT / "ref" / "kaoyan-vocab5" / "data").glob("c*.json")):
        out.update(load(path, {}).get("words", {}))
    return out


def load_ecdict():
    out = {}
    with io.open(DATA / "ecdict.csv", encoding="utf-8", errors="replace", newline="") as f:
        r = csv.reader(f)
        next(r, None)
        for row in r:
            if len(row) > 10:
                out[row[0].lower()] = row[3].strip()
    return out


def simple_core(value: str) -> str:
    value = (value or "").replace("\\n", " ").replace("&", " ")
    value = re.sub(
        r"^\s*(?:(?:vt|vi|v|n|adj|adv|a|prep|conj|pron|num|art|int|modal|aux|det|t|i)\s*[.&]?\s*)+",
        "", value, flags=re.I,
    )
    value = re.sub(r"\[[^\]]*\]|\([^)]*\)|\uff08[^\uff09]*\uff09", "", value)
    value = value.replace("\uff1b", "\uff0c").replace(";", "\uff0c")
    value = re.split(r"[\uff0c,\u3002.]", value)[0].strip()
    value = re.sub(r"\s+", "", value)
    return value[:18]


def meaning_for(word, books, ecdict, meanings):
    if word in meanings:
        return simple_core(meanings[word]) or "\u57fa\u7840\u8bcd"
    item = books.get(word, {})
    for sense in item.get("senses") or []:
        cleaned = simple_core(sense)
        if cleaned:
            return cleaned
    return simple_core(ecdict.get(word, "")) or "\u57fa\u7840\u8bcd"


def main():
    core = {x["word"] for x in load(DATA / "words.json", [])}
    review = load(DATA / "selection_review.json", [])
    books = load_books()
    ecdict = load_ecdict()
    meanings = load(DATA / "meanings_curated.json", {})
    freq = load(DATA / "ky2_freq.json", {}).get("words", {})

    rows_by_word = {}

    def add(word, origin, reason):
        word = word.lower().strip()
        if not word or word in core or word in rows_by_word:
            return
        if word not in books and word not in ecdict:
            return
        item = books.get(word, {})
        tiers = {b.get("id", ""): b.get("tier", "") for b in item.get("books", [])}
        info = freq.get(word, {})
        rows_by_word[word] = {
            "word": word,
            "meaning": meaning_for(word, books, ecdict, meanings),
            "freq": int(info.get("count", 0)),
            "coverage": int(info.get("coverage", 0)),
            "tier": tiers.get("sg") or tiers.get("hbs") or "基础词",
            "book_rank": int(item.get("rank", 0)),
            "origin": origin,
            "reason": reason,
        }

    for row in review:
        if row.get("category") == "基础词":
            add(row["word"], "二轮复核删除", row.get("reason", "初高中基础词"))

    for word in sorted(HARD_BASIC):
        if word not in STOP and len(word) >= 3:
            add(word, "筛选阶段排除", "基础功能词或初中熟词")

    rows = sorted(rows_by_word.values(), key=lambda r: (-r["coverage"], -r["freq"], r["word"]))
    for i, row in enumerate(rows, 1):
        row["id"] = i

    DATA_JSON.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    with io.open(DATA_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["序号", "单词", "核心释义", "英语二真题次数", "覆盖套数", "原分层", "词书收录数", "删除来源", "删除原因"])
        for r in rows:
            writer.writerow([r["id"], r["word"], r["meaning"], r["freq"], r["coverage"], r["tier"], f'{r["book_rank"]}/5', r["origin"], r["reason"]])

    # -------- PDF --------
    fonts = [("CJK", r"C:\Windows\Fonts\msyh.ttc", 0), ("CJK", r"C:\Windows\Fonts\simhei.ttf", None)]
    font = ""
    for name, path, index in fonts:
        if not os.path.exists(path):
            continue
        try:
            pdfmetrics.registerFont(TTFont(name, path, subfontIndex=index) if index is not None else TTFont(name, path))
            font = name
            break
        except Exception:
            continue
    if not font:
        raise RuntimeError("No Chinese font available")

    teal = colors.HexColor("#0F766E")
    line = colors.HexColor("#D7E3DE")
    zebra = colors.HexColor("#F6FAF8")
    ink = colors.HexColor("#17211E")
    muted = colors.HexColor("#52625D")

    S_WORD = ParagraphStyle("word", fontName=font, fontSize=9.2, leading=11, textColor=ink)
    S_MEAN = ParagraphStyle("mean", fontName=font, fontSize=8.2, leading=10.2)
    S_CELL = ParagraphStyle("cell", fontName=font, fontSize=7.6, leading=9.2, alignment=TA_CENTER)
    S_LEFT = ParagraphStyle("left", fontName=font, fontSize=7.6, leading=9.2, alignment=TA_LEFT)
    S_H1 = ParagraphStyle("h1", fontName=font, fontSize=18, leading=24, textColor=teal, spaceAfter=8)
    S_BODY = ParagraphStyle("body", fontName=font, fontSize=9.5, leading=16, textColor=muted)
    S_HEAD = ParagraphStyle("head", fontName=font, fontSize=7.6, leading=9.2, alignment=TA_CENTER, textColor=colors.white)

    doc = SimpleDocTemplate(str(PDF_OUT), pagesize=A4, leftMargin=15*mm, rightMargin=15*mm,
                            topMargin=14*mm, bottomMargin=15*mm,
                            title="考研英语二初高中基础词（已移出核心表）", author="自制")
    story = [
        Paragraph("考研英语二 · 初高中基础词", S_H1),
        Paragraph("已从核心背诵表移出，单独保留供查漏补缺", S_BODY),
        Spacer(1, 8),
        Paragraph(f"共 <b>{len(rows)}</b> 个词。默认不进入 1399 核心词学习队列；如果这些词对你不是熟词，可以单独过一遍。", S_BODY),
        Paragraph("频次口径：2010–2024 考研英语二 15 套真题；count 为去题型说明后的原始词次，coverage 为出现套数。", S_BODY),
        Paragraph("本清单不含音标。删除来源包括二轮复核删除和筛选阶段直接排除的基础功能词/初中熟词。", S_BODY),
        Spacer(1, 10),
    ]

    header = [Paragraph(h, S_HEAD) for h in ("序号", "单词", "核心释义", "真题次数", "覆盖套数", "原分层", "删除来源/原因")]
    data = [header]
    for r in rows:
        reason = f'{r["origin"]}：{r["reason"]}'
        data.append([
            Paragraph(str(r["id"]), S_CELL),
            Paragraph(escape(r["word"]), S_WORD),
            Paragraph(escape(r["meaning"]), S_MEAN),
            Paragraph(str(r["freq"]), S_CELL),
            Paragraph(str(r["coverage"]), S_CELL),
            Paragraph(escape(r["tier"]), S_CELL),
            Paragraph(escape(reason), S_LEFT),
        ])
    table = Table(data, colWidths=[11*mm, 30*mm, 40*mm, 17*mm, 17*mm, 24*mm, 41*mm], repeatRows=1)
    style = [
        ("BACKGROUND", (0,0), (-1,0), teal),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("LEFTPADDING", (0,0), (-1,-1), 3),
        ("RIGHTPADDING", (0,0), (-1,-1), 3),
        ("LINEBELOW", (0,0), (-1,-1), 0.35, line),
        ("BOX", (0,0), (-1,-1), 0.6, line),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0,i), (-1,i), zebra))
    table.setStyle(TableStyle(style))
    story.append(table)
    doc.build(story)

    print(f"words={len(rows)} json={DATA_JSON} csv={DATA_CSV} pdf={PDF_OUT} pdf_bytes={PDF_OUT.stat().st_size}")
    print("sample:", ", ".join(r["word"] for r in rows[:30]))


if __name__ == "__main__":
    main()
