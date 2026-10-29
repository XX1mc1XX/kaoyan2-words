# -*- coding: utf-8 -*-
"""Build the optional basic-word self-test and high/mid-frequency safety decks.

The existing insurance.json is treated as the authoritative snapshot when its
word set still matches the generated candidate set. This preserves manually
curated priority/order fields while rebuilding derived fields, insurance.csv,
and optional_decks_summary.json from that JSON.
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import sys
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
BASIC_REMOVED_ARCHIVE = DATA / "archive" / "basic_removed_words.json"
REVIEW = DATA / "selection_review.json"
MEANINGS = DATA / "meanings_curated.json"
MEANINGS_FINAL = DATA / "meanings_final.json"
CORRECTIONS = DATA / "meaning_corrections.json"
BASIC = DATA / "basic.json"
INSURANCE = DATA / "insurance.json"
INSURANCE_CSV = DATA / "insurance.csv"
SUMMARY = DATA / "optional_decks_summary.json"


def load_required(path: Path, expected_type=None):
    """Load a required, non-empty JSON input without fallback."""
    if not path.is_file():
        raise SystemExit(f"缺少必需输入: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"JSON 输入损坏: {path}: {exc}") from exc
    if value in (None, {}, []):
        raise SystemExit(f"必需输入为空: {path}")
    if expected_type is not None and not isinstance(value, expected_type):
        raise SystemExit(f"输入类型错误: {path} 应为 {expected_type.__name__}")
    return value


def write_json(path: Path, value: object) -> None:
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(value, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")


def insurance_score(row: dict) -> float:
    return round(
        2.0 * (int(row["coverage"]) + EN1_WEIGHT * int(row["en1_coverage"]))
        + 1.5 * int(row["book_rank"])
        + 1.2 * math.log1p(int(row["en1_freq"]))
        + 0.8 * math.log1p(int(row["freq"])),
        3,
    )


def normalize_insurance(rows: list[dict]) -> list[dict]:
    """Canonicalize every insurance row and recompute all derived fields."""
    normalized = []
    for index, row in enumerate(rows, 1):
        word = str(row.get("word", "")).strip()
        meaning = str(row.get("meaning", "")).strip()
        if not word or not meaning:
            raise SystemExit(f"insurance 第 {index} 条缺少 word/meaning")
        coverage = int(row.get("coverage", 0))
        en1_coverage = int(row.get("en1_coverage", 0))
        forms = row.get("forms")
        if not isinstance(forms, list):
            raise SystemExit(f"insurance {word} 的 forms 必须是数组")
        normalized.append({
            "id": index,
            "word": word,
            "family": str(row.get("family", "")),
            "meaning": meaning,
            "forms": forms,
            "freq": int(row.get("freq", 0)),
            "coverage": coverage,
            "en1_freq": int(row.get("en1_freq", 0)),
            "en1_coverage": en1_coverage,
            "weighted_coverage": round(coverage + EN1_WEIGHT * en1_coverage, 2),
            "book_rank": int(row.get("book_rank", 0)),
            "source_tier": str(row.get("source_tier", "")),
            "band": str(row.get("band", "")),
            "priority": str(row.get("priority", "")),
            "priority_rank": index,
        })
        normalized[-1]["priority_score"] = insurance_score(normalized[-1])
    return normalized


def rebuild_insurance_csv() -> list[dict]:
    """Rebuild insurance.csv entirely from the authoritative insurance.json."""
    rows = load_required(INSURANCE, list)
    for index, row in enumerate(rows, 1):
        required = (
            "id", "word", "meaning", "forms", "priority", "coverage",
            "en1_coverage", "weighted_coverage", "priority_score", "priority_rank",
        )
        if any(field not in row for field in required):
            raise SystemExit(f"insurance.json 第 {index} 条字段不完整")
        if row["id"] != index or row["priority_rank"] != index:
            raise SystemExit(f"insurance.json 第 {index} 条 id/priority_rank 不连续")
    words = [row["word"] for row in rows]
    if len(words) != len(set(words)):
        raise SystemExit("insurance.json 存在重复词")
    with io.open(INSURANCE_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "序号", "单词", "核心释义", "考查形式", "补漏优先级",
            "覆盖", "英一覆盖", "加权覆盖", "优先级分数",
        ])
        for row in rows:
            writer.writerow([
                row["id"], row["word"], row["meaning"],
                " / ".join(row.get("forms", [])), row["priority"],
                row["coverage"], row["en1_coverage"],
                row["weighted_coverage"], row["priority_score"],
            ])
    return rows


def main() -> None:
    force = "--force" in sys.argv or os.environ.get("KY_FORCE_DATA") == "1"
    existing_basic_rows = load_required(BASIC, list) if BASIC.exists() and not force else []
    core_rows = load_required(CORE, list)
    derivative_rows = load_required(DERIVATIVES, list)
    review_rows = load_required(REVIEW, list)
    ky2_payload = load_required(DATA / "ky2_freq.json", dict)
    ky1_payload = load_required(DATA / "ky1_freq.json", dict)
    ky2 = ky2_payload.get("words")
    ky1 = ky1_payload.get("words")
    if not isinstance(ky2, dict) or not ky2:
        raise SystemExit("ky2_freq.json 缺少非空 words 对象")
    if not isinstance(ky1, dict) or not ky1:
        raise SystemExit("ky1_freq.json 缺少非空 words 对象")

    basic_source = BASIC_REMOVED if BASIC_REMOVED.exists() else BASIC_REMOVED_ARCHIVE
    if not basic_source.exists():
        raise SystemExit(f"缺少必需输入: {BASIC_REMOVED} (或 {BASIC_REMOVED_ARCHIVE})")
    basic_rows = load_required(basic_source, list)

    core = {row["word"] for row in core_rows}
    derivatives = {row["word"] for row in derivative_rows}
    basic = {row["word"] for row in basic_rows}
    reviewed_out = {
        row["word"] for row in review_rows
        if isinstance(row, dict) and row.get("word")
    }
    books = load_five_books()
    vocab, ecdict = load_ecdict()
    derived = load_required(DATA / "derived.json", dict)
    curated = load_required(MEANINGS, dict)
    fallback = load_required(MEANINGS_FINAL, dict)
    corrections = load_required(CORRECTIONS, dict)

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
        meaning = row.get("meaning") or meaning_of(word)
        if not meaning:
            raise SystemExit(f"基础自测词 {word} 缺少释义")
        normalized_basic.append({
            "id": basic_index,
            "word": word,
            "family": "",
            "meaning": meaning,
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
    if not normalized_basic:
        raise SystemExit("基础自测词库为空；拒绝写 basic.json")

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
        candidates.append({
            "word": word,
            "family": "",
            "meaning": meaning,
            "freq": count,
            "coverage": coverage,
            "en1_freq": en1_count,
            "en1_coverage": en1_coverage,
            "weighted_coverage": round(coverage + EN1_WEIGHT * en1_coverage, 2),
            "priority_score": round(
                2.0 * (coverage + EN1_WEIGHT * en1_coverage)
                + 1.5 * rank
                + 1.2 * math.log1p(en1_count)
                + 0.8 * math.log1p(count),
                3,
            ),
            "book_rank": rank,
            "source_tier": sg,
            "band": "基础补漏" if hbs == "基础词" else "高/中频保险库",
            "is_basic": hbs == "基础词",
        })

    candidates.sort(key=lambda row: (
        row["is_basic"], -row["priority_score"], -row["weighted_coverage"],
        -row["coverage"], -row["en1_coverage"], -row["book_rank"], row["word"],
    ))
    selected_insurance = derivatives | basic | core | {row["word"] for row in candidates}
    for index, row in enumerate(candidates, 1):
        if row["is_basic"]:
            row["priority"] = "C 补漏"
        elif row["coverage"] >= 3:
            row["priority"] = "A 重点"
        elif row["coverage"] + row["en1_coverage"] > 0:
            row["priority"] = "B 次重点"
        else:
            row["priority"] = "C 补漏"
        row["forms"] = forms_of(row["word"], selected_insurance)
        row.pop("is_basic", None)
    normalized_candidates = normalize_insurance(candidates)
    if not normalized_candidates:
        raise SystemExit("保险词库为空；拒绝写 insurance.json")

    if INSURANCE.exists() and not force:
        # Keep the published/manual snapshot by default. The source books can
        # legitimately contain fragments not present in that snapshot; only an
        # explicit --force may replace the 1545-word curated deck.
        insurance_rows = normalize_insurance(load_required(INSURANCE, list))
    else:
        insurance_rows = normalized_candidates

    basic_output = existing_basic_rows or normalized_basic
    if not existing_basic_rows:
        write_json(BASIC, basic_output)
    write_json(INSURANCE, insurance_rows)
    # CSV and summary deliberately read the JSON just written, so JSON remains
    # the single source of truth for all insurance exports.
    insurance_rows = rebuild_insurance_csv()
    summary = {
        "basic_total": len(basic_output),
        "insurance_total": len(insurance_rows),
        "insurance_priorities": Counter(row["priority"] for row in insurance_rows),
        "insurance_english_2": sum(row["coverage"] > 0 for row in insurance_rows),
        "insurance_english_1_only": sum(row["coverage"] == 0 and row["en1_coverage"] > 0 for row in insurance_rows),
        "insurance_no_english_evidence": sum(row["coverage"] + row["en1_coverage"] == 0 for row in insurance_rows),
        "field_semantics": {
            "id": "insurance.json 数组中的 1-based 展示顺序",
            "priority_rank": "与 id 相同的 1-based 补漏优先级顺序",
            "weighted_coverage": "coverage + 0.35 * en1_coverage",
            "priority_score": "2*weighted_coverage + 1.5*book_rank + 1.2*log1p(en1_freq) + 0.8*log1p(freq)",
        },
        "note": "保险库保留人工确认的排序与优先级；派生字段、CSV 和 summary 均从 insurance.json 重建。",
    }
    write_json(SUMMARY, summary)

    print(f"basic={len(basic_output)} insurance={len(insurance_rows)}")
    print(f"insurance_priorities={dict(summary['insurance_priorities'])}")
    print(
        f"english2={summary['insurance_english_2']} "
        f"english1_only={summary['insurance_english_1_only']} "
        f"no_evidence={summary['insurance_no_english_evidence']}"
    )


if __name__ == "__main__":
    main()