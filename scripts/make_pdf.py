# -*- coding: utf-8 -*-
"""Generate a priority-only English II core vocabulary PDF."""
from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ROWS = json.loads((DATA / "words.json").read_text(encoding="utf-8"))
ROWS.sort(key=lambda x: x["id"])
OUT = ROOT / "output" / f"\u8003\u7814\u82f1\u8bed\u4e8c\u6838\u5fc3\u8bcd{len(ROWS)}.pdf"

TEAL = colors.HexColor("#0f766e")
LINE = colors.HexColor("#d7e3de")
ZEBRA = colors.HexColor("#f6faf8")
INK = colors.HexColor("#17211e")
MUTED = colors.HexColor("#52625d")


def register_font():
    candidates = [
        ("CJK", r"C:\Windows\Fonts\msyh.ttc", 0),
        ("CJK", r"C:\Windows\Fonts\simhei.ttf", None),
        ("CJK", r"C:\Windows\Fonts\simsun.ttc", 0),
    ]
    for name, path, index in candidates:
        if not os.path.exists(path):
            continue
        try:
            pdfmetrics.registerFont(TTFont(name, path, subfontIndex=index) if index is not None else TTFont(name, path))
            return name
        except Exception:
            continue
    raise RuntimeError("No Chinese font available")


FONT = register_font()
S_WORD = ParagraphStyle("word", fontName=FONT, fontSize=9.5, leading=11.5, textColor=INK)
S_MEAN = ParagraphStyle("mean", fontName=FONT, fontSize=8.7, leading=10.8, textColor=INK)
S_FORMS = ParagraphStyle("forms", fontName=FONT, fontSize=7.5, leading=9.2, textColor=MUTED)
S_CELL = ParagraphStyle("cell", fontName=FONT, fontSize=8.0, leading=9.6, alignment=TA_CENTER)
S_HEAD = ParagraphStyle("head", fontName=FONT, fontSize=8.2, leading=10, alignment=TA_CENTER, textColor=colors.white)
S_H1 = ParagraphStyle("h1", fontName=FONT, fontSize=20, leading=27, textColor=TEAL, spaceAfter=10)
S_BODY = ParagraphStyle("body", fontName=FONT, fontSize=9.8, leading=17, textColor=MUTED)


def cover(canvas, doc):
    canvas.saveState()
    w, h = A4
    canvas.setFillColor(TEAL)
    canvas.rect(0, 0, w, h, stroke=0, fill=1)
    canvas.setFillColor(colors.white)
    canvas.setFont(FONT, 44)
    canvas.drawCentredString(w / 2, h * 0.61, "考研英语二核心词")
    canvas.setFont(FONT, 18)
    canvas.drawCentredString(w / 2, h * 0.55, "只按背诵优先级学习")
    canvas.setStrokeColor(colors.white)
    canvas.setLineWidth(1.2)
    canvas.line(w * 0.33, h * 0.51, w * 0.67, h * 0.51)
    canvas.setFont(FONT, 14)
    canvas.drawCentredString(w / 2, h * 0.34, f"{len(ROWS)} \u4e2a\u6838\u5fc3\u8bcd\u6761  \u00b7  S / A / B")
    canvas.setFont(FONT, 10)
    canvas.drawCentredString(w / 2, h * 0.30, "英语二主权重  ·  英语一低权重  ·  五书共识")
    canvas.restoreState()


def footer(canvas, doc):
    canvas.saveState()
    w, _ = A4
    canvas.setFont(FONT, 8)
    canvas.setFillColor(colors.HexColor("#94a39c"))
    canvas.drawCentredString(w / 2, 11 * mm, str(doc.page))
    canvas.restoreState()


def intro():
    counts = Counter(x["priority"] for x in ROWS)
    story = [
        Spacer(1, 10),
        Paragraph("使用说明", S_H1),
        Paragraph("这份词表只回答一个问题：这个词现在该不该优先背。", S_BODY),
        Spacer(1, 6),
        Paragraph("<b>S \u5fc5\u80cc</b> \u2192 <b>A \u91cd\u70b9</b> \u2192 <b>B \u6b21\u91cd\u70b9</b>", S_BODY),
        Spacer(1, 4),
        Paragraph(
            "优先级由系统综合英语二真题（主权重 100%）、英语一真题（低权重 35%）、"
            "词书分层、五本书收录共识和词频计算。你不需要自己比较次数、覆盖套数或频段。",
            S_BODY,
        ),
        Spacer(1, 6),
        Paragraph(
            f"\u5171 {len(ROWS)} \u8bcd\uff1aS \u5fc5\u80cc {counts.get('S \u5fc5\u80cc', 0)}\uff1bA \u91cd\u70b9 {counts.get('A \u91cd\u70b9', 0)}\uff1bB \u6b21\u91cd\u70b9 {counts.get('B \u6b21\u91cd\u70b9', 0)}\u3002",
            S_BODY,
        ),
        Spacer(1, 6),
        Paragraph("表中保留五个字段：序号、单词、核心释义、考查形式、背诵优先级。不含音标。", S_BODY),
        Spacer(1, 12),
        Paragraph("按优先级顺序学习；同优先级内也按综合得分排序。", S_BODY),
        Spacer(1, 24),
    ]
    stat = Table(
        [
            [Paragraph("优先级", S_HEAD), Paragraph("数量", S_HEAD)],
            [Paragraph("S 必背", S_CELL), Paragraph(str(counts.get("S 必背", 0)), S_CELL)],
            [Paragraph("A 重点", S_CELL), Paragraph(str(counts.get("A 重点", 0)), S_CELL)],
            [Paragraph("B 次重点", S_CELL), Paragraph(str(counts.get("B 次重点", 0)), S_CELL)],
        ],
        colWidths=[55 * mm, 55 * mm],
        hAlign="CENTER",
    )
    stat.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), TEAL),
        ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#fee4e2")),
        ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#fff2df")),
        ("BACKGROUND", (0, 3), (-1, 3), colors.HexColor("#e5f4f1")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(stat)
    return story


def word_table():
    headers = ["序号", "单词", "核心释义", "考查形式", "背诵优先级"]
    data = [[Paragraph(h, S_HEAD) for h in headers]]
    for row in ROWS:
        data.append([
            Paragraph(str(row["id"]), S_CELL),
            Paragraph(escape(str(row["word"])), S_WORD),
            Paragraph(escape(str(row["meaning"])), S_MEAN),
            Paragraph(escape(" / ".join(row.get("forms", []))), S_FORMS),
            Paragraph(escape(str(row["priority"])), S_CELL),
        ])
    table = Table(data, colWidths=[10 * mm, 32 * mm, 68 * mm, 49 * mm, 21 * mm], repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), TEAL),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.35, LINE),
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
    table.setStyle(TableStyle(style))
    return table

def main():
    doc = SimpleDocTemplate(
        str(OUT), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=14 * mm, bottomMargin=16 * mm,
        title="考研英语二核心词（按背诵优先级）", author="自制",
    )
    story = [Spacer(1, 1)]
    from reportlab.platypus import PageBreak
    story.append(PageBreak())
    story += intro()
    story.append(PageBreak())
    story.append(word_table())
    doc.build(story, onFirstPage=cover, onLaterPages=footer)
    print(f"output={OUT}")
    print(f"bytes={OUT.stat().st_size} words={len(ROWS)} priorities={dict(Counter(x['priority'] for x in ROWS))}")


if __name__ == "__main__":
    main()
