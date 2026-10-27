# -*- coding: utf-8 -*-
"""Build the English II core word list.

Primary source:
  ref/kaoyan-vocab5/data/c*.json -- five-book union with:
    - sg: 考研词汇闪过 high/mid/low/basic tiers
    - rank: number of the five wordbooks containing the word

Calibration:
  data/ky2_freq.json -- 2010-2024 English II paper counts/coverage

Output:
  data/words.json
  data/words.csv
  data/selection_summary.json
"""
from __future__ import annotations

import csv
import glob
import io
import json
import math
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
REF = ROOT / "ref"
BOOK_DIR = REF / "kaoyan-vocab5" / "data"
CURATED = DATA / "meanings_final.json"
CURATED_FALLBACK = DATA / "meanings_curated.json"
CORRECTIONS = DATA / "meaning_corrections.json"
REVIEW = DATA / "selection_review.json"
KY1 = DATA / "ky1_freq.json"
EN1_WEIGHT = 0.35

HIGH = "高频词"
MID = "中频词"
LOW = "低频词"
BASIC = "基础词"
SUPER = "超纲词"

# These are known from junior/senior-high vocabulary or are function words. They
# may be frequent in papers, but they are not worth using as core study entries.
HARD_BASIC = set("""
go come get make take give find think know see look use work read write say tell ask help
want need try keep let put run move turn start stop show play live love like feel become seem
leave bring happen begin hold hear meet pay sit stand speak walk win buy sell send build stay
fall cut reach kill pass remain change grow open close break spend teach learn understand
remember forget mean set place point part home life time people person man woman child kid
thing way day year world country school student teacher family friend good bad big small high
low long short old young new right wrong same different easy hard important possible sure true
real lot bit kind sort type group number question problem answer word text page line story idea
fact case matter effect result reason cause example course job money price cost value
paragraph chart translation direction essay option section part blank sheet author title composition
""".split())

STOP = set("""
a an the and or but nor so if then than that this these those there here
of to in on at by for with from as into onto upon within without about above below under over
between among through during before after since until while because though although unless whether
is am are was were be been being do does did done doing have has had having
will would shall should can could may might must
i you he she it we they me him her us them my your his its our their mine yours hers ours theirs
myself yourself himself herself itself ourselves themselves who whom whose which what when where
why how not no yes very too also just only both each every all some any few many more most much
other another such own same up down off out again once ever never always often sometimes usually
zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen
sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred
thousand million billion trillion dozen half quarter percent percentage first second third fourth
fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth
seventeenth eighteenth nineteenth twentieth thirtieth
""".split())

SAFE_WORD_RE = re.compile(r"^[a-z][a-z-]{2,}$")
POS_RE = re.compile(
    r"(?<![A-Za-z])(?:n|v|vt|vi|adj|adv|a|prep|conj|pron|num|art|int)\s*\.?\s*",
    re.I,
)


def load_json(path: Path, default):
    if not path.exists():
        return default
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def load_five_books() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in sorted(BOOK_DIR.glob("c*.json")):
        out.update(load_json(path, {}).get("words", {}))
    return out


def load_ecdict() -> tuple[set[str], dict[str, dict]]:
    vocab: set[str] = set()
    records: dict[str, dict] = {}
    with io.open(DATA / "ecdict.csv", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) < 11:
                continue
            word = row[0].lower()
            vocab.add(word)
            records[word] = {
                "exchange": row[10].strip(),
                "trans": row[3].strip(),
                "tag": row[7].strip(),
            }
    return vocab, records


def book_tiers(item: dict) -> dict[str, str]:
    return {b.get("id", ""): b.get("tier", "") for b in item.get("books", [])}


def clean_meaning(raw_senses: list[str], fallback: str = "") -> str:
    """Rule-based fallback; Claude-curated meanings override this when available."""
    parts: list[str] = []
    for sense in raw_senses:
        sense = POS_RE.sub("", sense or "")
        sense = re.sub(r"^[①②③④⑤⑥⑦⑧⑨⑩]\s*", "", sense)
        sense = sense.replace("（", "(").replace("）", ")")
        for piece in re.split(r"[；;]", sense):
            piece = re.sub(r"\[[^\]]*\]|\([^)]*\)", "", piece)
            piece = piece.strip(" ,，。.;；:：")
            piece = re.sub(r"^(?:使|对|向|在|把|被|给|与|和)\s*", "", piece)
            if piece and piece not in parts:
                parts.append(piece)
        if len(parts) >= 3:
            break
    if not parts and fallback:
        return clean_meaning(fallback.split("\n"))[:18]
    if not parts:
        return ""
    first = "；".join(parts[:1])
    if len(parts[0]) <= 3 and len(parts) > 1:
        first += "；" + parts[1]
    return first[:24]


def parse_exchange(exchange: str) -> list[str]:
    forms: list[str] = []
    for segment in (exchange or "").split("/"):
        if ":" not in segment:
            continue
        key, value = segment.split(":", 1)
        if key.strip() in {"s", "p", "d", "i", "3", "r", "t"}:
            value = value.strip().lower()
            if value.isalpha():
                forms.append(value)
    return forms


def build_forms(
    word: str,
    exchange: str,
    derived: dict[str, list[str]],
    selected: set[str],
    freq: dict[str, dict],
) -> list[str]:
    inflections = set(parse_exchange(exchange))
    candidates = set(inflections)
    for related in derived.get(word, []):
        if related != word:
            candidates.add(related)

    # Add only tightly related forms that are themselves core entries. This
    # catches pairs such as social/socially, legal/legally and
    # particular/particularly when ECDICT has no exchange field.
    related_suffixes = {
        "ly", "ally", "al", "ity", "ities", "ment", "ments", "tion",
        "tions", "s", "es", "ed", "ing", "er", "ers", "ist", "ists",
        "ism", "ize", "ized", "izes", "izing", "ive", "ively", "ous",
        "ously", "ness", "ful", "fully", "less", "lessly",
    }
    for related in selected:
        if related.startswith(word) and related != word:
            if related[len(word):] in related_suffixes:
                candidates.add(related)

    ranked: list[tuple[int, int, str]] = []
    for form in candidates:
        if not form.isalpha() or form == word or form in STOP:
            continue
        info = freq.get(form, {})
        if form in selected:
            ranked.append((3, info.get("coverage", 0), form))
        elif form in inflections or info.get("coverage", 0) >= 1:
            ranked.append((2, info.get("coverage", 0), form))
    ranked.sort(key=lambda x: (-x[0], -x[1], x[2]))
    return [form for _, _, form in ranked[:5]]


def main() -> None:
    books = load_five_books()
    freq_payload = load_json(DATA / "ky2_freq.json", {})
    freq = freq_payload["words"]
    ky1_payload = load_json(KY1, {})
    ky1 = ky1_payload.get("words", {})
    vocab, ecdict = load_ecdict()
    derived = load_json(DATA / "derived.json", {})
    curated = load_json(CURATED, {})
    fallback_meanings = load_json(CURATED_FALLBACK, {})
    corrections = load_json(CORRECTIONS, {})
    review_rows = load_json(REVIEW, [])
    reviewed_out = {row["word"] for row in review_rows if isinstance(row, dict) and row.get("word")}

    def valid(word: str) -> bool:
        return bool(SAFE_WORD_RE.fullmatch(word)) and word in vocab and word not in STOP and word not in HARD_BASIC

    def tiers(word: str) -> dict[str, str]:
        return book_tiers(books.get(word, {}))

    def rank(word: str) -> int:
        return int(books.get(word, {}).get("rank", 0))

    def coverage(word: str) -> int:
        return int(freq.get(word, {}).get("coverage", 0))

    def count(word: str) -> int:
        return int(freq.get(word, {}).get("count", 0))

    def en1_coverage(word: str) -> int:
        return int(ky1.get(word, {}).get("coverage", 0))

    def en1_count(word: str) -> int:
        return int(ky1.get(word, {}).get("count", 0))

    def excluded(word: str) -> bool:
        return tiers(word).get("hbs") in {BASIC, SUPER}

    # Primary: 闪过 high/mid, had real English II evidence and is not a basic word.
    primary = {
        w for w in books
        if tiers(w).get("sg") in {HIGH, MID}
        and valid(w)
        and not excluded(w)
        and coverage(w) >= 1
    }
    # Cross-book consensus: appears in at least four of five books and in English II.
    cross_book = {
        w for w in books
        if valid(w) and not excluded(w) and rank(w) >= 4 and coverage(w) >= 1
    }
    # High-frequency words in English II with at least three wordbook votes.
    exam_high = {
        w for w in books
        if valid(w) and not excluded(w) and rank(w) >= 3 and coverage(w) >= 5
    }
    # A small override: a word marked 超纲 by one book but repeatedly used by
    # English II is clearly worth learning (e.g. sustainable).
    overridden = {
        w for w in books
        if valid(w) and rank(w) >= 4 and coverage(w) >= 3
    }

    selected = primary | cross_book | exam_high | overridden
    selected = {w for w in selected if coverage(w) >= 1 and w not in reviewed_out}
    # Safety net: keep every remaining high/mid wordbook entry that is not a
    # reviewed-out basic word, an hbs basic word, or an out-of-syllabus word.
    safe_high_mid = {
        w for w in books
        if tiers(w).get("sg") in {HIGH, MID}
        and valid(w)
        and not excluded(w)
        and w not in reviewed_out
        and (rank(w) >= 4 or tiers(w).get("hbs") == "\u5fc5\u8003\u8bcd")
    }
    selected |= safe_high_mid

    rows: list[dict] = []
    for word in selected:
        item = books[word]
        tier = tiers(word).get("sg", "")
        if tier == HIGH:
            band = "高频核心"
            tier_order = 0
        elif tier == MID:
            band = "中频核心"
            tier_order = 1
        elif rank(word) >= 5:
            band = "跨词书核心"
            tier_order = 2
        else:
            band = "真题补充"
            tier_order = 3

        source_senses = item.get("senses") or []
        meaning = corrections.get(word) or curated.get(word) or fallback_meanings.get(word) or clean_meaning(source_senses, ecdict.get(word, {}).get("trans", ""))
        rows.append(
            {
                "word": word,
                "meaning": meaning,
                "freq": count(word),
                "coverage": coverage(word),
                "en1_freq": en1_count(word),
                "en1_coverage": en1_coverage(word),
                "weighted_coverage": round(coverage(word) + EN1_WEIGHT * en1_coverage(word), 2),
                "priority_score": round(
                    2.0 * (coverage(word) + EN1_WEIGHT * en1_coverage(word))
                    + 2.5 * rank(word)
                    + {"\u9ad8\u9891\u6838\u5fc3": 8.0, "\u4e2d\u9891\u6838\u5fc3": 5.0, "\u8de8\u8bcd\u4e66\u6838\u5fc3": 2.0, "\u771f\u9898\u8865\u5145": 0.0}[band]
                    + 0.8 * math.log1p(count(word)),
                    3,
                ),
                "book_rank": rank(word),
                "source_tier": tier or "跨词书",
                "band": band,
                "forms": build_forms(word, ecdict.get(word, {}).get("exchange", ""), derived, selected, freq),
                "_tier_order": tier_order,
            }
        )

    rows.sort(key=lambda r: (
        -r["priority_score"], -r["weighted_coverage"], -r["coverage"], -r["freq"],
        -r["en1_coverage"], -r["en1_freq"], -r["book_rank"], r["word"],
    ))
    n = len(rows)
    for idx, row in enumerate(rows, 1):
        pct = idx / max(1, n)
        if row.get("coverage", 0) == 0:
            level = "C \u8865\u5145"
        elif pct <= 0.20:
            level = "S \u5fc5\u80cc"
        elif pct <= 0.50:
            level = "A \u91cd\u70b9"
        elif pct <= 0.80:
            level = "B \u6b21\u91cd\u70b9"
        else:
            level = "C \u8865\u5145"
        row["id"] = idx
        row["priority"] = level
        row["priority_rank"] = idx
        del row["_tier_order"]

    # Keep only necessary words: S/A/B. C was the optional supplement layer.
    for r in rows:
        if (
            r["priority"] == "C \u8865\u5145"
            and r.get("coverage", 0) >= 1
            and (r.get("source_tier") == "\u9ad8\u9891\u8bcd" or r.get("book_rank", 0) >= 4)
        ):
            r["priority"] = "B \u6b21\u91cd\u70b9"
    rows = [r for r in rows if r["priority"] != "C \u8865\u5145"]
    for idx, row in enumerate(rows, 1):
        row["id"] = idx
        row["priority_rank"] = idx

    DATA.mkdir(parents=True, exist_ok=True)
    with io.open(DATA / "words.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(rows, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")

    with io.open(DATA / "words.csv", "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["\u5e8f\u53f7", "\u5355\u8bcd", "\u6838\u5fc3\u91ca\u4e49", "\u8003\u67e5\u5f62\u5f0f", "\u80cc\u8bf5\u4f18\u5148\u7ea7"])
        for r in rows:
            writer.writerow([r["id"], r["word"], r["meaning"], " / ".join(r.get("forms", [])), r["priority"]])


    summary = {
        "total": len(rows),
        "papers": 15,
        "bands": Counter(r["band"] for r in rows),
        "priorities": Counter(r["priority"] for r in rows),
        "source_tiers": Counter(r["source_tier"] for r in rows),
        "coverage": {
            "min": min((r["coverage"] for r in rows), default=0),
            "max": max((r["coverage"] for r in rows), default=0),
            "at_least_5": sum(1 for r in rows if r["coverage"] >= 5),
        },
        "meaning_curated": sum(1 for r in rows if r["word"] in corrections or r["word"] in curated or r["word"] in fallback_meanings),
        "reviewed_out": len(reviewed_out),
        "weights": {"english_2": 1.0, "english_1": EN1_WEIGHT, "english_3": 0.0},
        "en1_available": bool(ky1),
        "notes": [
            "词频次数为 2010-2024 英语二真题去除题型说明后的原始词次。",
            "覆盖套数为该词在 15 套真题中出现的套数。",
            "选词以《考研词汇闪过》高频/中频为主，并用五书交集和英语二真题校准。",
            "经第二轮保守复核，剔除了仍属基础熟词、题型模板词、专名和偶然主题词的高置信项。",
        ],
    }
    with io.open(DATA / "selection_summary.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"selected={len(rows)}")
    print(f"bands={dict(summary['bands'])}")
    print(f"source_tiers={dict(summary['source_tiers'])}")
    print(f"curated_meanings={summary['meaning_curated']}/{len(rows)}")
    print("first 30:")
    for r in rows[:30]:
        print(f'  {r["id"]:>4} {r["priority"]:<7} {r["word"]:<18} {r["meaning"]}')


if __name__ == "__main__":
    main()
