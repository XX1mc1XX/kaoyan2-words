# -*- coding: utf-8 -*-
"""Build the optional basic-word self-test and high/mid-frequency safety decks."""
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
    clean_meaning,
    load_ecdict,
    load_five_books,
)

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CORE = DATA / "words.json"
DERIVATIVES = DATA / "derivatives.json"
BASIC_REMOVED = DATA / "basic_removed_words.json"
REVIEW = DATA / "selection_review.json"
MEANINGS = DATA / "meanings_curated.json"
MEANINGS_FINAL = DATA / "meanings_final.json"
CORRECTIONS = DATA / "meaning_corrections.json"


def load(path: Path, fallback):
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    core_rows = load(CORE, [])
    derivative_rows = load(DERIVATIVES, [])
    core = {row["word"] for row in core_rows}
    derivatives = {row["word"] for row in derivative_rows}
    basic_rows = load(BASIC_REMOVED, [])
    basic = {row["word"] for row in basic_rows}
    reviewed_out = {
        row["word"] for row in load(REVIEW, [])
        if isinstance(row, dict) and row.get("word")
    }
    books = load_five_books()
    vocab, ecdict = load_ecdict()
    derived = load(DATA / "derived.json", {})
    ky2 = load(DATA / "ky2_freq.json", {}).get("words", {})
    ky1 = load(DATA / "ky1_freq.json", {}).get("words", {})
    curated = load(MEANINGS, {})
    fallback = load(MEANINGS_FINAL, {})
    corrections = load(CORRECTIONS, {})

    def meaning_of(word: str) -> str:
        return (
            corrections.get(word)
            or curated.get(word)
            or fallback.get(word)
            or clean_meaning(
                books.get(word, {}).get("senses") or [],
                ecdict.get(word, {}).get("trans", ""),
            )
        )

    def forms_of(word: str, selected: set[str]) -> list[str]:
        return [
            form for form in build_forms(
                word,
                ecdict.get(word, {}).get("exchange", ""),
                derived,
                selected,
                ky2,
            )
            if form in ky2 or form in ky1
        ]

    # The basic list is deliberately a self-test deck, not a second core deck.
    normalized_basic = []
    selected_basic = basic | core | derivatives
    basic_index = 0
    for row in basic_rows:
        word = row["word"]
        if word in core or word in derivatives:
            continue
        basic_index += 1
        normalized_basic.append({
            "id": basic_index,
            "word": word,
            "family": "",
            "meaning": row.get("meaning") or meaning_of(word),
            "forms": forms_of(word, selected_basic),
            "freq": int(row.get("freq", 0)),
            "coverage": int(row.get("coverage", 0)),
            "en1_freq": 0,
            "en1_coverage": 0,
            "weighted_coverage": float(row.get("coverage", 0)),
            "book_rank": int(row.get("book_rank", 0)),
            "source_tier": row.get("tier", ""),
            "band": "基础自测",
            "priority": "C 自测",
            "priority_rank": basic_index,
        })

    candidates = []
    for word, record in books.items():
        tier = book_tiers(record)
        sg = tier.get("sg", "")
        hbs = tier.get("hbs", "")
        if word in core or word in derivatives or word in basic or word in reviewed_out:
            continue
        if sg not in {"高频词", "中频词"} or hbs == "超纲词":
            continue
        if not SAFE_WORD_RE.fullmatch(word) or word in STOP or word in HARD_BASIC:
            continue
        if word not in vocab:
            continue
        meaning = meaning_of(word)
        if not meaning:
            continue
        coverage = int(ky2.get(word, {}).get("coverage", 0))
        en1_coverage = int(ky1.get(word, {}).get("coverage", 0))
        count = int(ky2.get(word, {}).get("count", 0))
        en1_count = int(ky1.get(word, {}).get("count", 0))
        rank = int(record.get("rank", 0))
        score = round(
            2.0 * (coverage + EN1_WEIGHT * en1_coverage)
            + 1.5 * rank
            + 1.2 * math.log1p(en1_count)
            + 0.8 * math.log1p(count),
            3,
        )
        candidates.append({
            "word": word,
            "family": "",
            "meaning": meaning,
            "freq": count,
            "coverage": coverage,
            "en1_freq": en1_count,
            "en1_coverage": en1_coverage,
            "weighted_coverage": round(coverage + EN1_WEIGHT * en1_coverage, 2),
            "priority_score": score,
            "book_rank": rank,
            "source_tier": sg,
            "band": "基础补漏" if tier.get("hbs") == "基础词" else "高/中频保险库",
            "is_basic": tier.get("hbs") == "基础词",
        })

    candidates.sort(key=lambda row: (
        row["is_basic"], -row["priority_score"], -row["weighted_coverage"],
        -row["coverage"], -row["en1_coverage"], -row["book_rank"], row["word"],
    ))
    selected_insurance = derivatives | basic | core | {row["word"] for row in candidates}
    for index, row in enumerate(candidates, 1):
        row["id"] = index
        if row["is_basic"]:
            row["priority"] = "C 补漏"
        elif row["coverage"] >= 3:
            row["priority"] = "A 重点"
        elif row["coverage"] + row["en1_coverage"] > 0:
            row["priority"] = "B 次重点"
        else:
            row["priority"] = "C 补漏"
        row["priority_rank"] = index
        row["forms"] = forms_of(row["word"], selected_insurance)
        row.pop("is_basic", None)

    for path, rows in (
        (DATA / "basic.json", normalized_basic),
        (DATA / "insurance.json", candidates),
    ):
        with io.open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(rows, f, ensure_ascii=False, separators=(",", ":"))
            f.write("\n")

    with io.open(DATA / "insurance.csv", "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["序号", "单词", "核心释义", "考查形式", "补漏优先级"])
        for row in candidates:
            writer.writerow([row["id"], row["word"], row["meaning"], " / ".join(row["forms"]), row["priority"]])

    summary = {
        "basic_total": len(normalized_basic),
        "insurance_total": len(candidates),
        "insurance_priorities": Counter(row["priority"] for row in candidates),
        "insurance_english_2": sum(row["coverage"] > 0 for row in candidates),
        "insurance_english_1_only": sum(row["coverage"] == 0 and row["en1_coverage"] > 0 for row in candidates),
        "insurance_no_english_evidence": sum(row["coverage"] + row["en1_coverage"] == 0 for row in candidates),
        "note": "基础自测用于检验被默认视为已掌握的熟词；保险库保留闪过高/中频中未进入主线的词，仅作补漏。",
    }
    with io.open(DATA / "optional_decks_summary.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"basic={len(normalized_basic)} insurance={len(candidates)}")
    print(f"insurance_priorities={dict(summary['insurance_priorities'])}")
    print(
        f"english2={summary['insurance_english_2']} "
        f"english1_only={summary['insurance_english_1_only']} "
        f"no_evidence={summary['insurance_no_english_evidence']}"
    )


if __name__ == "__main__":
    main()
