# -*- coding: utf-8 -*-
"""Build English II exam frequency data from the 2010-2024 papers.

Output: data/ky2_freq.json
Schema:
{
  "meta": {"papers": [...], "count_unit": "occurrence", "coverage_unit": "paper"},
  "words": {
    "lemma": {
      "count": 23, "coverage": 7, "paper_counts": {"2010": 2, ...},
      "top_form": "consumers", "proper": false
    }
  }
}
"""
from __future__ import annotations

import glob
import io
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SRC = ROOT / "ref" / "ky2"
OUT = DATA / "ky2_freq.json"

# WordNet expands sense has a known false conversion here: number -> numb.
# Keep the surface headword in such ambiguous cases.
LEMMA_BLACKLIST = {("number", "numb")}

WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")
SECTION1_RE = re.compile(r"\bSection\s+I\b(?!I)", re.I)
YEAR_RE = re.compile(r"20(?:1\d|2\d)(?!\d)")

# Remove exam instructions and layout labels. Passages, questions and options remain.
NOISE_LINE_RE = re.compile(
    r"^(?:Directions?:|Section\s+[IVX]+\b|Part\s+[ABC]\b|Text\s+\d+\b|"
    r"Question\s+\d+\b|ANSWER SHEET(?:\s+\d+)?\b|Read the following\b|"
    r"Choose the best\b|Write your\b|Mark\b|points?\)?$|"
    r"\d+\s*points?\)?$)",
    re.I,
)


def load_lemma() -> dict[str, str]:
    """form -> lemma using the bundled WordNet-style lemma list."""
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
    """Remove exam instructions while keeping passages, questions and options."""
    # A Directions block normally ends at "(10 points)" or similar.
    text = re.sub(
        r"\bDirections?\s*:?.*?(?:\(\s*\d+\s*points?\s*\)|\bpoints?\s*\.)",
        " ",
        text,
        flags=re.I | re.S,
    )
    # Writing prompts are instructions rather than reading material and inflate
    # words such as essay/comment/chart/interpret.
    text = re.split(
        r"\bSection\s+[IVX\u2160-\u217fN]+\s+Writing\b|\bWriting\s+4[78]\s*\.",
        text,
        maxsplit=1,
        flags=re.I,
    )[0]

    text = re.sub(r"\bTranslation\s*\n?\s*46\s*\.", " ", text, flags=re.I)

    kept: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if NOISE_LINE_RE.search(line):
            continue
        # Remove ANSWER SHEET and page-number fragments without dropping the
        # surrounding sentence when PDF extraction puts them on one line.
        line = re.sub(r"\bANSWER\s+SHEET\s*\d*\b", " ", line, flags=re.I)
        line = re.sub(r"^-\s*\d+\s*-$", " ", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            kept.append(line)
    return "\n".join(kept)


def collect_papers() -> list[tuple[int, str]]:
    papers: list[tuple[int, str]] = []

    combined = SRC / "2010-2021年考研英语二真题合集.pdf"
    if combined.exists():
        doc = fitz.open(combined)
        starts = [i for i, page in enumerate(doc) if SECTION1_RE.search(page.get_text())]
        # The collection has one Section I start per year (2010-2021).
        if len(starts) == 12:
            for offset, start in enumerate(starts):
                end = starts[offset + 1] if offset + 1 < len(starts) else doc.page_count
                text = "\n".join(doc[i].get_text() for i in range(start, end))
                papers.append((2010 + offset, text))
        else:
            print(f"WARN: found {len(starts)} Section I starts in combined PDF; using whole file")
            papers.append((2010, "\n".join(page.get_text() for page in doc)))

    for path in sorted(SRC.glob("*.pdf")):
        if path == combined:
            continue
        year_match = YEAR_RE.search(path.stem)
        if not year_match:
            continue
        doc = fitz.open(path)
        papers.append((int(year_match.group(0)), "\n".join(page.get_text() for page in doc)))

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
            # A single sentence-initial capital is not enough to call it proper.
            "proper": (upper / total > 0.7 and total >= 2),
        }

    payload = {
        "meta": {
            "papers": expected,
            "paper_count": len(expected),
            "count_unit": "occurrence",
            "coverage_unit": "paper",
            "source": "2010-2024 考研英语二真题 PDF",
            "note": "count 为去除题型说明后的原始词次；coverage 为出现该词的真题套数。",
        },
        "words": dict(sorted(words.items())),
    }
    DATA.mkdir(parents=True, exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=0)
        f.write("\n")

    print(f"\nWrote {OUT}")
    print(f"papers={len(papers)} lemmas={len(words)} occurrences={sum(v['count'] for v in words.values())}")
    print("Top by coverage then count:")
    top = sorted(words.items(), key=lambda item: (-item[1]["coverage"], -item[1]["count"]))[:30]
    for word, info in top:
        print(f"  {word:<16} coverage={info['coverage']:>2}/15 count={info['count']:>4}")


if __name__ == "__main__":
    main()

