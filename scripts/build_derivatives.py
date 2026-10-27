# -*- coding: utf-8 -*-
"""Build the optional core-derivative deck without changing the 1342-word core."""
from __future__ import annotations

import csv
import io
import json
import math
from collections import Counter
from pathlib import Path

from build_words import (
    EN1_WEIGHT,
    HARD_BASIC,
    SAFE_WORD_RE,
    STOP,
    book_tiers,
    build_forms,
    load_ecdict,
    load_five_books,
)

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CURATED = DATA / "derivatives_curated.tsv"
BOOK_EXTRA = DATA / "derivatives_book_extra.tsv"
CORE = DATA / "words.json"
OUT = DATA / "derivatives.json"
SUMMARY = DATA / "derivative_selection_summary.json"


def main() -> None:
    core_rows = json.loads(CORE.read_text(encoding="utf-8"))
    core = {row["word"] for row in core_rows}
    books = load_five_books()
    vocab, ecdict = load_ecdict()
    derived = json.loads((DATA / "derived.json").read_text(encoding="utf-8"))
    ky2 = json.loads((DATA / "ky2_freq.json").read_text(encoding="utf-8"))["words"]
    ky1 = json.loads((DATA / "ky1_freq.json").read_text(encoding="utf-8"))["words"]

    curated = []
    seen_curated = set()
    for source_path in (CURATED, BOOK_EXTRA):
        with io.open(source_path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                word = (row.get("word") or "").strip().lower()
                family = (row.get("family") or "").strip().lower()
                meaning = (row.get("meaning") or "").strip()
                if not word or not family or not meaning:
                    raise ValueError(f"incomplete derivative row: {row}")
                if word in seen_curated:
                    continue
                seen_curated.add(word)
                curated.append({"word": word, "family": family, "meaning": meaning})
    if len({row["word"] for row in curated}) != len(curated):
        raise ValueError("duplicate derivative word")

    selected = {row["word"] for row in curated}
    rows = []
    for item in curated:
        word = item["word"]
        family = item["family"]
        if word in core:
            raise ValueError(f"derivative duplicates a core word: {word}")
        if word in STOP or word in HARD_BASIC or not SAFE_WORD_RE.fullmatch(word):
            raise ValueError(f"low-value derivative retained: {word}")
        if word not in vocab:
            raise ValueError(f"derivative missing from ECDICT: {word}")

        k2 = ky2.get(word, {})
        k1 = ky1.get(word, {})
        coverage = int(k2.get("coverage", 0))
        en1_coverage = int(k1.get("coverage", 0))
        if coverage + en1_coverage < 1:
            raise ValueError(f"derivative has no English I/II evidence: {word}")

        count = int(k2.get("count", 0))
        en1_count = int(k1.get("count", 0))
        rank = int(books.get(word, {}).get("rank", 0))
        tier = book_tiers(books.get(word, {})).get("sg", "") or "派生核心"
        score = round(
            2.0 * (coverage + EN1_WEIGHT * en1_coverage)
            + 1.5 * rank
            + 1.2 * math.log1p(en1_count)
            + 0.8 * math.log1p(count),
            3,
        )
        rows.append({
            "word": word,
            "family": family,
            "meaning": item["meaning"],
            "freq": count,
            "coverage": coverage,
            "en1_freq": en1_count,
            "en1_coverage": en1_coverage,
            "weighted_coverage": round(coverage + EN1_WEIGHT * en1_coverage, 2),
            "priority_score": score,
            "book_rank": rank,
            "source_tier": tier,
            "band": "核心派生",
            "forms": [
                form for form in build_forms(
                    word,
                    ecdict.get(word, {}).get("exchange", ""),
                    derived,
                    selected | core,
                    ky2,
                )
                if form != family and (form in ky2 or form in ky1)
            ],
        })

    rows.sort(key=lambda row: (
        -row["priority_score"], -row["weighted_coverage"], -row["coverage"],
        -row["en1_coverage"], -row["book_rank"], row["word"],
    ))
    n = len(rows)
    for index, row in enumerate(rows, 1):
        pct = index / max(1, n)
        if pct <= 0.20:
            level = "S 必背"
        elif pct <= 0.50:
            level = "A 重点"
        else:
            level = "B 次重点"
        row["id"] = index
        row["priority"] = level
        row["priority_rank"] = index

    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rows, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")

    with io.open(DATA / "derivatives.csv", "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["序号", "派生词", "词族", "核心释义", "考查形式", "背诵优先级"])
        for row in rows:
            writer.writerow([
                row["id"], row["word"], row["family"], row["meaning"],
                " / ".join(row["forms"]), row["priority"],
            ])

    summary = {
        "total": n,
        "book_high_mid": sum(
            book_tiers(record).get("sg") in {"高频词", "中频词"}
            for record in books.values()
        ),
        "book_derivative_notes": sum(
            ("派生" in (record.get("usage") or "") or "[族]" in (record.get("usage") or ""))
            for record in books.values()
            if book_tiers(record).get("sg") in {"高频词", "中频词"}
        ),
        "priorities": Counter(row["priority"] for row in rows),
        "with_forms": sum(bool(row["forms"]) for row in rows),
        "with_english_2": sum(row["coverage"] > 0 for row in rows),
        "english_1_only": sum(row["coverage"] == 0 and row["en1_coverage"] > 0 for row in rows),
        "weights": {"english_2": 1.0, "english_1": EN1_WEIGHT},
        "note": "阶段二可选词库；只收词族中高频、词性或语义明显变化的核心派生词。",
    }
    with io.open(SUMMARY, "w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"derivatives={n}")
    print(f"priorities={dict(summary['priorities'])}")
    print(f"forms={summary['with_forms']} english2={summary['with_english_2']} english1_only={summary['english_1_only']}")
    print(f"book_high_mid={summary['book_high_mid']} book_notes={summary['book_derivative_notes']}")


if __name__ == "__main__":
    main()