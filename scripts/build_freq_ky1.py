# -*- coding: utf-8 -*-
"""Build English I exam frequency data from the 2010-2024 papers.

Output: data/ky1_freq.json

The schema intentionally mirrors data/ky2_freq.json. This file is an
independent low-weight corpus source; it does not modify the main word list.

Statistical scope:
- The 15 English I papers from 2010 through 2024.
- Passage text, question stems, and options are counted.
- Directions, section labels, writing prompts, and translation prompts are
  removed before tokenization.
"""
from __future__ import annotations

import io
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SRC = ROOT / "ref" / "ky1"
OUT = DATA / "ky1_freq.json"

# Keep the same known false-conversion guard as the English II builder.
LEMMA_BLACKLIST = {("number", "numb")}

WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")
YEAR_RE = re.compile(r"20(?:1\d|2\d)(?!\d)")
# A paper starts with a short heading containing both "Section" and "Use of
# English". Searching the whole page would falsely match translation passages.
SECTION_HEAD_RE = re.compile(r"\bSection\b", re.I)
USE_OF_ENGLISH_RE = re.compile(r"Use\s+of\s+English", re.I)

# Stop before the writing section. The heading can be on one line or split over
# two lines, and OCR sometimes renders "III" as "ill".
WRITING_SECTION_RE = re.compile(
    r"(?im)^\s*Section\s+[IVXIl1|]{1,6}\s*(?:\n\s*)?Writing\b.*$"
)

DIRECTIONS_START_RE = re.compile(
    r"^\s*(?:\d+\s*){0,2}\.?\s*Directions?\s*[:;]", re.I
)
DIRECTIONS_END_RE = re.compile(r"\bpoints?\s*\)", re.I)

# Residual instruction/layout lines when OCR splits a directions block.
NOISE_LINE_RE = re.compile(
    r"^(?:"
    r"Section\s+[^\n]{0,20}$|"
    r"Use\s+of\s+English$|"
    r"Reading\s+Comprehension$|"
    r"Part\s+[ABC]\b.*$|"
    r"Text\s+\d+\b.*$|"
    r"Directions?\s*[:;]?.*$|"
    r"Read\s+the\s+following\b.*$|"
    r"Choose\s+the\s+best\b.*$|"
    r"Answer\s+the\s+questions\b.*$|"
    r"Mark\s+your\s+answers?\b.*$|"
    r"Write\s+your\s+answers?\b.*$|"
    r"[A-D],\s*[A-D](?:,\s*[A-D])*\s+or\s+[A-D]\b.*$|"
    r"ANSWER\s+SHEET\b.*$|"
    r"points?\)?$|"
    r"\d+\s*points?\)?$"
    r")",
    re.I,
)


def load_lemma() -> dict[str, str]:
    """Return form -> lemma using the bundled WordNet-style lemma list."""
    out: dict[str, str] = {}
    path = DATA / "lemma.en.txt"
    with io.open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(";") or "->" not in line:
                continue
            left, right = line.split("->", 1)
            lemma = left.split("/")[0].strip().lower()
            if not lemma.isalpha():
                continue
            for form in right.split(","):
                form = form.strip().lower()
                if form.isalpha() and form != lemma:
                    out.setdefault(form, lemma)
    return out


def clean_text(text: str) -> str:
    """Remove instructions while retaining passages, stems, and options."""
    writing = WRITING_SECTION_RE.search(text)
    if writing:
        text = text[: writing.start()]

    lines = text.splitlines()
    kept: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue

        if DIRECTIONS_START_RE.match(line):
            # Remove only a directions block that reaches its points marker
            # nearby. Broken PDF layouts can place a Directions label far from
            # its marker; in that case never risk deleting a passage.
            end = min(len(lines), index + 20)
            marker = index
            while marker < end and not DIRECTIONS_END_RE.search(lines[marker]):
                marker += 1
            if marker < end:
                index = marker + 1
                continue
            index += 1
            continue

        if NOISE_LINE_RE.search(line):
            index += 1
            continue

        # Page footers and OCR page markers are layout, not exam content.
        line = re.sub(r"^-\s*\d+\s*-$", " ", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            kept.append(line)
        index += 1
    return "\n".join(kept)


def find_source_pdfs() -> tuple[Path, dict[int, Path]]:
    """Locate the combined 2010-2021 PDF and one full-paper PDF per year."""
    candidates = sorted(SRC.rglob("*.pdf"))
    combined_candidates = [p for p in candidates if "2010-2021" in p.name]
    if len(combined_candidates) != 1:
        raise SystemExit(
            f"Expected exactly one 2010-2021 English I combined PDF, got {combined_candidates}"
        )
    combined = combined_candidates[0]

    by_year: dict[int, list[Path]] = defaultdict(list)
    for path in candidates:
        if path == combined:
            continue
        match = YEAR_RE.search(path.name)
        if match:
            by_year[int(match.group(0))].append(path)

    # Duplicate years include both the paper and a large analysis PDF. Prefer
    # the smallest file for 2022-2024; the actual paper is the compact file.
    individual: dict[int, Path] = {}
    for year in (2022, 2023, 2024):
        if year not in by_year:
            raise SystemExit(f"Missing English I paper PDF for {year}")
        individual[year] = min(by_year[year], key=lambda p: p.stat().st_size)
    return combined, individual


def collect_papers() -> list[tuple[int, str]]:
    combined, individual = find_source_pdfs()
    papers: list[tuple[int, str]] = []

    doc = fitz.open(combined)
    starts: list[int] = []
    for i, page in enumerate(doc):
        nonempty = [line.strip() for line in page.get_text().splitlines() if line.strip()]
        head = "\n".join(nonempty[:6])
        if SECTION_HEAD_RE.search(head) and USE_OF_ENGLISH_RE.search(head):
            starts.append(i)
    if len(starts) != 12:
        raise SystemExit(
            f"Expected 12 English I papers in the 2010-2021 combined PDF, found {len(starts)}"
        )
    for offset, start in enumerate(starts):
        end = starts[offset + 1] if offset + 1 < len(starts) else doc.page_count
        text = "\n".join(doc[i].get_text() for i in range(start, end))
        papers.append((2010 + offset, text))

    for year, path in sorted(individual.items()):
        paper = fitz.open(path)
        text = "\n".join(page.get_text() for page in paper)
        papers.append((year, text))

    papers.sort(key=lambda item: item[0])
    return papers


def normalize_token(raw: str) -> str:
    word = raw.lower().strip("'-")
    word = re.sub(r"'s$", "", word)
    return word


def main() -> None:
    form2lemma = load_lemma()
    papers = collect_papers()
    expected = list(range(2010, 2025))
    years = [year for year, _ in papers]
    if years != expected:
        raise SystemExit(f"Expected papers {expected}, got {years}")

    counts: dict[str, Counter[str]] = defaultdict(Counter)
    raw_counts: dict[str, Counter[str]] = defaultdict(Counter)
    upper_counts: dict[str, Counter[str]] = defaultdict(Counter)

    for year, raw_text in papers:
        text = clean_text(raw_text)
        if "Directions:" in text or "Use of English" in text:
            raise SystemExit(f"Instruction residue remains in English I paper {year}")
        for match in WORD_RE.finditer(text):
            original = match.group(0)
            word = normalize_token(original)
            if len(word) < 2:
                continue
            lemma = form2lemma.get(word, word)
            if (word, lemma) in LEMMA_BLACKLIST:
                lemma = word
            counts[lemma][str(year)] += 1
            raw_counts[lemma][word] += 1
            if original[0].isupper():
                upper_counts[lemma][str(year)] += 1
        print(f"{year}: {len(text):>6} chars")

    words: dict[str, dict] = {}
    for lemma, by_year in counts.items():
        total = sum(by_year.values())
        upper = sum(upper_counts[lemma].values())
        top_form = raw_counts[lemma].most_common(1)[0][0]
        words[lemma] = {
            "count": total,
            "coverage": len(by_year),
            "paper_counts": dict(sorted(by_year.items())),
            "top_form": top_form,
            "proper": (upper / total > 0.7 and total >= 2),
        }

    payload = {
        "meta": {
            "papers": expected,
            "paper_count": len(expected),
            "count_unit": "occurrence",
            "coverage_unit": "paper",
            "source": "2010-2024 考研英语一真题 PDF",
            "note": "count 为去除题型说明、写作提示和翻译提示后的原始词次；coverage 为出现该词的真题套数。统计正文、题干和选项。",
        },
        "words": dict(sorted(words.items())),
    }
    DATA.mkdir(parents=True, exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=0)
        f.write("\n")

    print(f"\nWrote {OUT}")
    print(
        f"papers={len(papers)} lemmas={len(words)} "
        f"occurrences={sum(v['count'] for v in words.values())}"
    )
    print("Top by coverage then count:")
    top = sorted(
        words.items(), key=lambda item: (-item[1]["coverage"], -item[1]["count"])
    )[:30]
    for word, info in top:
        print(
            f"  {word:<16} coverage={info['coverage']:>2}/15 "
            f"count={info['count']:>4}"
        )


if __name__ == "__main__":
    main()