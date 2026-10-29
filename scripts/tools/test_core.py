# -*- coding: utf-8 -*-
"""Core regression checks for the English II vocabulary data and mobile app.

Run from the project root:
    python -m unittest -v scripts.tools.test_core
"""
from __future__ import annotations

import collections
import csv
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORDS_PATH = ROOT / "data" / "words.json"
SUMMARY_PATH = ROOT / "data" / "selection_summary.json"
DERIVATIVES_PATH = ROOT / "data" / "derivatives.json"
BASIC_PATH = ROOT / "data" / "basic.json"
INSURANCE_PATH = ROOT / "data" / "insurance.json"
WORDS_ORDER_PATH = ROOT / "data" / "words_order.json"
WORDS_CSV_PATH = ROOT / "data" / "words.csv"
INSURANCE_CSV_PATH = ROOT / "data" / "insurance.csv"
OPTIONAL_SUMMARY_PATH = ROOT / "data" / "optional_decks_summary.json"
ECDICT_SUBSET_PATH = ROOT / "data" / "ecdict_subset.json"
HTML_PATH = ROOT / "software" / "考研核心词.html"

REQUIRED_FIELDS = ("word", "meaning", "priority", "priority_rank", "forms")
BANDS = ("高频核心", "中频核心", "跨词书核心", "真题补充")

# Function words, school-level basics, and exam-rubric words that must not be
# presented as English II core vocabulary.
BANNED_WORDS = {
    "a", "an", "the", "go", "one", "make", "take", "get", "use", "good",
    "be", "is", "are", "was", "were", "do", "does", "did", "have", "has",
    "had", "this", "that", "these", "those", "i", "you", "he", "she", "it",
    "we", "they", "and", "or", "but", "in", "on", "at", "to", "of", "for",
    "with", "by", "from",
    "text", "answer", "paragraph", "chart", "translation", "essay",
    "composition", "question", "section", "option", "blank",
}

POS_RESIDUE_RE = re.compile(
    r"(?<![A-Za-z])(?:vt|vi|v|n|adj|adv|prep|conj|pron|num|art|det|aux|a)\.\s*",
    re.IGNORECASE,
)
DICTIONARY_TAG_RE = re.compile(r"\[(?:计|化|电|医|法|商|经)\]")


def contains_key(value: object, key: str) -> bool:
    """Return whether a JSON-like value contains *key* at any depth."""
    if isinstance(value, dict):
        return key in value or any(contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(contains_key(item, key) for item in value)
    return False


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def load_csv(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.reader(f))


def priority_sort_key(row: dict) -> tuple:
    return (
        -float(row.get("priority_score", 0)),
        -float(row.get("weighted_coverage", 0)),
        -int(row.get("coverage", 0)),
        -int(row.get("freq", 0)),
        -int(row.get("en1_coverage", 0)),
        -int(row.get("en1_freq", 0)),
        -int(row.get("book_rank", 0)),
        str(row["word"]),
    )


def embedded_json(html: str, element_id: str) -> object:
    match = re.search(
        r'<script\b[^>]*\bid="' + re.escape(element_id) + r'"[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        raise AssertionError(f"embedded JSON block not found: {element_id}")
    return json.loads(match.group(1))


class CoreRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.words = load_json(WORDS_PATH)
        cls.derivatives = load_json(DERIVATIVES_PATH)
        cls.basic = load_json(BASIC_PATH)
        cls.insurance = load_json(INSURANCE_PATH)
        cls.summary = load_json(SUMMARY_PATH)
        cls.words_order = load_json(WORDS_ORDER_PATH)
        cls.optional_summary = load_json(OPTIONAL_SUMMARY_PATH)
        cls.ecdict_subset = load_json(ECDICT_SUBSET_PATH)
        cls.html = HTML_PATH.read_text(encoding="utf-8")

    def test_01_words_nonempty_and_no_phonetic_field(self) -> None:
        self.assertIsInstance(self.words, list)
        self.assertGreater(len(self.words), 0)
        self.assertTrue(all(isinstance(word, dict) for word in self.words))
        for index, word in enumerate(self.words):
            with self.subTest(index=index, word=word.get("word")):
                self.assertNotIn("phonetic", word)
        self.assertFalse(
            contains_key(self.words, "phonetic"),
            "words.json must not contain a phonetic field at any depth",
        )

    def test_02_every_word_has_required_fields(self) -> None:
        for index, word in enumerate(self.words):
            with self.subTest(index=index, word=word.get("word")):
                for field in REQUIRED_FIELDS:
                    self.assertIn(field, word)
                self.assertIsInstance(word["word"], str)
                self.assertTrue(word["word"].strip())
                self.assertIsInstance(word["meaning"], str)
                self.assertIsInstance(word["band"], str)
                self.assertTrue(word["band"].strip())
                self.assertIsInstance(word["forms"], list)
                self.assertTrue(
                    all(isinstance(form, str) and form.strip() for form in word["forms"]),
                    "forms must contain only non-empty strings",
                )

    def test_03_freq_and_coverage_types_and_ranges(self) -> None:
        papers = self.summary.get("papers", 15)
        self.assertIsInstance(papers, int)
        self.assertGreater(papers, 0)

        for index, word in enumerate(self.words):
            with self.subTest(index=index, word=word["word"]):
                freq = word["freq"]
                coverage = word["coverage"]
                self.assertIs(type(freq), int)
                self.assertIs(type(coverage), int)
                self.assertGreaterEqual(freq, 0)
                self.assertLessEqual(freq, 1000)
                self.assertGreaterEqual(coverage, 0)
                self.assertLessEqual(coverage, papers)
                if coverage == 0:
                    self.assertTrue(word["priority"].startswith("C"), "zero-coverage words must stay in C supplement")
                else:
                    self.assertGreaterEqual(freq, 1)
                if coverage:
                    self.assertGreaterEqual(
                        freq,
                        coverage,
                        "a word cannot occur fewer times than the number of papers it covers",
                    )

    def test_04_band_counts_match_selection_summary(self) -> None:
        actual_bands = collections.Counter(word["band"] for word in self.words)
        expected_bands = self.summary.get("bands")
        self.assertIsInstance(expected_bands, dict)
        self.assertEqual(set(expected_bands), set(BANDS))
        self.assertEqual(dict(actual_bands), expected_bands)
        actual_priorities = collections.Counter(word["priority"] for word in self.words)
        expected_priorities = self.summary.get("priorities")
        self.assertIsInstance(expected_priorities, dict)
        self.assertEqual(dict(actual_priorities), expected_priorities)
        self.assertEqual(len(self.words), self.summary.get("total"))
        self.assertEqual(sum(actual_bands.values()), len(self.words))

    def test_05_meanings_are_clean_and_reasonably_short(self) -> None:
        for index, word in enumerate(self.words):
            meaning = word["meaning"]
            with self.subTest(index=index, word=word["word"], meaning=meaning):
                stripped = meaning.strip()
                self.assertGreater(len(stripped), 0)
                self.assertLessEqual(
                    len(stripped),
                    30,
                    "core meaning should be concise, not a dictionary dump",
                )
                self.assertNotIn("\\", meaning, "backslash residue is not allowed")
                self.assertNotIn("/", meaning, "phonetic/slash residue is not allowed")
                self.assertNotIn("\n", meaning, "core meaning must be one line")
                self.assertIsNone(POS_RESIDUE_RE.search(meaning), "part-of-speech residue is not allowed")
                self.assertIsNone(DICTIONARY_TAG_RE.search(meaning), "dictionary domain tags are not allowed")

    def test_06_basic_and_rubric_words_are_absent(self) -> None:
        present = sorted(
            word["word"].lower()
            for word in self.words
            if word["word"].lower() in BANNED_WORDS
        )
        self.assertEqual(present, [], f"non-core/basic words found in vocabulary: {present}")

    def test_07_embedded_html_data_matches_json(self) -> None:
        self.assertTrue(HTML_PATH.is_file(), f"generated HTML not found: {HTML_PATH}")
        decks = {
            "words": self.words,
            "derivatives": self.derivatives,
            "basic": self.basic,
            "insurance": self.insurance,
        }
        for deck, source in decks.items():
            with self.subTest(deck=deck):
                embedded = embedded_json(self.html, f"ky-deck-{deck}")
                self.assertIsInstance(embedded, list)
                self.assertEqual(len(embedded), len(source))
                self.assertEqual(
                    [(row.get("id"), row.get("word"), row.get("priority")) for row in embedded],
                    [(row.get("id"), row.get("word"), row.get("priority")) for row in source],
                )
                self.assertFalse(contains_key(embedded, "phonetic"))
                expected_weights = [
                    round((len(source) - index + 1) * 100 / len(source), 2)
                    for index in range(1, len(source) + 1)
                ]
                self.assertEqual([row.get("weight") for row in embedded], expected_weights)

    def test_08_required_mobile_features_and_events_exist(self) -> None:
        required_strings = {
            "meaning toggle control": 'id="meaningToggle"',
            "meaning toggle implementation": "function toggleMeaning",
            "persistent meaning preference": "autoShow",
            "position display": 'id="position"',
            "position wording": "第 ",
            "navigation implementation": "function navigate",
            "priority filter": "priorityFilter",
            "forms section": 'id="formsBox"',
        }
        for label, needle in required_strings.items():
            with self.subTest(feature=label):
                self.assertIn(needle, self.html)

        required_events = {
            "touchstart": r"addEventListener\(\s*['\"]touchstart['\"]",
            "touchmove": r"addEventListener\(\s*['\"]touchmove['\"]",
            "touchend": r"addEventListener\(\s*['\"]touchend['\"]",
            "touchcancel": r"addEventListener\(\s*['\"]touchcancel['\"]",
        }
        for label, pattern in required_events.items():
            with self.subTest(event=label):
                self.assertRegex(self.html, pattern)


    def test_09_derivative_deck_is_valid(self) -> None:
        self.assertIsInstance(self.derivatives, list)
        self.assertGreaterEqual(len(self.derivatives), 50)
        core = {row["word"] for row in self.words}
        derivative_words = {row["word"] for row in self.derivatives}
        self.assertEqual(core & derivative_words, set(), "decks must not overlap")
        for index, row in enumerate(self.derivatives):
            with self.subTest(index=index, word=row.get("word")):
                for field in REQUIRED_FIELDS + ("family", "coverage", "en1_coverage"):
                    self.assertIn(field, row)
                self.assertTrue(row["family"].strip())
                self.assertTrue(row["meaning"].strip())
                self.assertLessEqual(len(row["meaning"]), 30)
                self.assertGreater(row["coverage"] + row["en1_coverage"], 0)
                self.assertNotIn("phonetic", row)
                self.assertTrue(all(isinstance(form, str) and form.strip() for form in row["forms"]))
        self.assertFalse(contains_key(self.derivatives, "phonetic"))

    def test_10_optional_decks_are_valid_and_disjoint(self) -> None:
        self.assertGreaterEqual(len(self.basic), 300)
        self.assertGreater(len(self.insurance), 1000)
        core = {row["word"] for row in self.words}
        derivatives = {row["word"] for row in self.derivatives}
        basic = {row["word"] for row in self.basic}
        insurance = {row["word"] for row in self.insurance}
        self.assertEqual(core & derivatives, set())
        self.assertEqual(core & basic, set())
        self.assertEqual(core & insurance, set())
        self.assertEqual(derivatives & basic, set())
        self.assertEqual(derivatives & insurance, set())
        self.assertEqual(basic & insurance, set())
        for deck_name, rows in (("basic", self.basic), ("insurance", self.insurance)):
            for index, row in enumerate(rows):
                with self.subTest(deck=deck_name, index=index, word=row.get("word")):
                    for field in REQUIRED_FIELDS:
                        self.assertIn(field, row)
                    self.assertTrue(row["word"].strip())
                    self.assertTrue(row["meaning"].strip())
                    self.assertLessEqual(len(row["meaning"]), 30)
                    self.assertNotIn("phonetic", row)
                    self.assertIsNone(POS_RESIDUE_RE.search(row["meaning"]))
                    self.assertTrue(all(isinstance(form, str) and form.strip() for form in row["forms"]))
            self.assertFalse(contains_key(rows, "phonetic"))


    def test_11_words_order_and_export_contract(self) -> None:
        self.assertIsInstance(self.words_order, list)
        self.assertEqual(len(self.words_order), len(self.words))
        self.assertEqual(len(self.words_order), len(set(self.words_order)))
        self.assertEqual([row["word"] for row in self.words], self.words_order)
        self.assertEqual([row["id"] for row in self.words], list(range(1, len(self.words) + 1)))
        self.assertEqual(len({tuple(row.keys()) for row in self.words}), 1)

        ranked = sorted(self.words, key=priority_sort_key)
        self.assertEqual(
            {row["word"]: row["priority_rank"] for row in ranked},
            {row["word"]: index for index, row in enumerate(ranked, 1)},
        )
        self.assertEqual(
            sorted(row["priority_rank"] for row in self.words),
            list(range(1, len(self.words) + 1)),
        )
        for row in self.words:
            self.assertAlmostEqual(
                row["weighted_coverage"],
                round(row["coverage"] + 0.35 * row["en1_coverage"], 2),
                places=6,
            )

        semantics = self.summary.get("field_semantics")
        self.assertIsInstance(semantics, dict)
        self.assertEqual(set(semantics), {"id", "priority_rank", "weight", "weighted_coverage"})
        self.assertEqual(self.summary.get("word_order"), {"path": "data/words_order.json", "total": len(self.words)})
        self.assertEqual(self.summary.get("total"), len(self.words))
        self.assertEqual(dict(collections.Counter(row["band"] for row in self.words)), self.summary["bands"])
        self.assertEqual(dict(collections.Counter(row["priority"] for row in self.words)), self.summary["priorities"])
        self.assertEqual(dict(collections.Counter(row["source_tier"] for row in self.words)), self.summary["source_tiers"])

        csv_rows = load_csv(WORDS_CSV_PATH)
        self.assertEqual(csv_rows[0], ["序号", "单词", "核心释义", "考查形式", "背诵优先级"])
        expected = [
            [str(row["id"]), row["word"], row["meaning"], " / ".join(row["forms"]), row["priority"]]
            for row in self.words
        ]
        self.assertEqual(csv_rows[1:], expected)

    def test_12_optional_deck_exports_are_complete(self) -> None:
        insurance_fields = {
            "id", "word", "family", "meaning", "forms", "freq", "coverage",
            "en1_freq", "en1_coverage", "weighted_coverage", "priority_score",
            "book_rank", "source_tier", "band", "priority", "priority_rank",
        }
        self.assertEqual(len({tuple(row.keys()) for row in self.insurance}), 1)
        for index, row in enumerate(self.insurance, 1):
            with self.subTest(word=row.get("word")):
                self.assertEqual(set(row), insurance_fields)
                self.assertEqual(row["id"], index)
                self.assertEqual(row["priority_rank"], index)
                self.assertAlmostEqual(
                    row["weighted_coverage"],
                    round(row["coverage"] + 0.35 * row["en1_coverage"], 2),
                    places=6,
                )
                self.assertAlmostEqual(
                    row["priority_score"],
                    round(
                        2.0 * (row["coverage"] + 0.35 * row["en1_coverage"])
                        + 1.5 * row["book_rank"]
                        + 1.2 * __import__("math").log1p(row["en1_freq"])
                        + 0.8 * __import__("math").log1p(row["freq"]),
                        3,
                    ),
                    places=6,
                )

        csv_rows = load_csv(INSURANCE_CSV_PATH)
        self.assertEqual(csv_rows[0], [
            "序号", "单词", "核心释义", "考查形式", "补漏优先级",
            "覆盖", "英一覆盖", "加权覆盖", "优先级分数",
        ])
        expected = [
            [
                str(row["id"]), row["word"], row["meaning"], " / ".join(row["forms"]),
                row["priority"], str(row["coverage"]), str(row["en1_coverage"]),
                str(row["weighted_coverage"]), str(row["priority_score"]),
            ]
            for row in self.insurance
        ]
        self.assertEqual(csv_rows[1:], expected)

        actual_summary = {
            "basic_total": len(self.basic),
            "insurance_total": len(self.insurance),
            "insurance_priorities": dict(collections.Counter(row["priority"] for row in self.insurance)),
            "insurance_english_2": sum(row["coverage"] > 0 for row in self.insurance),
            "insurance_english_1_only": sum(row["coverage"] == 0 and row["en1_coverage"] > 0 for row in self.insurance),
            "insurance_no_english_evidence": sum(row["coverage"] + row["en1_coverage"] == 0 for row in self.insurance),
        }
        for key, value in actual_summary.items():
            self.assertEqual(self.optional_summary.get(key), value)
        self.assertEqual(
            set(self.optional_summary.get("field_semantics", {})),
            {"id", "priority_rank", "weighted_coverage", "priority_score"},
        )
        self.assertEqual(len(self.words) + len(self.derivatives) + len(self.basic) + len(self.insurance), 3356)

    def test_13_detail_coverage_and_domain_labels(self) -> None:
        detail = embedded_json(self.html, "ky-deck-detail")
        self.assertIsInstance(detail, dict)
        all_rows = self.words + self.derivatives + self.basic + self.insurance
        all_words = {row["word"] for row in all_rows}
        self.assertEqual(set(detail), all_words)
        for word, item in detail.items():
            with self.subTest(word=word):
                self.assertIsInstance(item, dict)
                self.assertTrue(str(item.get("t", "")).strip())
                self.assertIsNone(DICTIONARY_TAG_RE.search(item["t"]))
                self.assertNotRegex(item["t"], r"(?m)^\s*\[[^\]]+\]")
        self.assertFalse(contains_key(detail, "phonetic"))

        forms_total = forms_noted = 0
        for row in all_rows:
            notes = (detail.get(row["word"]) or {}).get("f") or {}
            for form in row.get("forms") or []:
                if form and form.lower() != row["word"]:
                    forms_total += 1
                    forms_noted += bool(notes.get(form.lower()))
        self.assertGreater(forms_total, 0)
        self.assertGreaterEqual(forms_noted / forms_total, 0.99)



    def test_14_ecdict_subset_contract_and_detail_coverage(self) -> None:
        self.assertLess(ECDICT_SUBSET_PATH.stat().st_size, 3 * 1024 * 1024)
        subset = self.ecdict_subset
        self.assertEqual(subset.get("schema_version"), 1)
        self.assertEqual(subset.get("field_names"), ["phonetic", "translation", "tag", "exchange"])
        entries = subset.get("entries")
        self.assertIsInstance(entries, dict)

        all_rows = self.words + self.derivatives + self.basic + self.insurance
        headwords = {row["word"].strip().lower() for row in all_rows}
        forms = {
            str(form).strip().lower()
            for row in all_rows
            for form in (row.get("forms") or [])
            if str(form).strip().lower() != row["word"].strip().lower()
        }
        self.assertEqual(set(entries), headwords | forms)
        for word, values in entries.items():
            with self.subTest(word=word):
                self.assertIsInstance(values, list)
                self.assertEqual(len(values), 4)
                self.assertTrue(all(isinstance(value, str) for value in values))

        def subset_detail_text(entry: list[str]) -> str:
            translation = entry[1].replace("\\n", "\n")
            groups = []
            for line in translation.split("\n"):
                line = re.sub(r"^(?:\[[^\]]+\]\s*)+", "", line.strip()).strip()
                if line:
                    groups.append(line[:46] + "…" if len(line) > 46 else line)
            return "\n".join(groups[:2])

        current_detail = embedded_json(self.html, "ky-deck-detail")
        for word in headwords:
            self.assertEqual(subset_detail_text(entries[word]), current_detail[word]["t"])
        detail_count = sum(bool(subset_detail_text(entries[word])) for word in headwords)
        coverage = subset.get("coverage", {})
        self.assertGreaterEqual(detail_count, 3350)
        self.assertEqual(coverage.get("headword_count"), len(headwords))
        self.assertEqual(coverage.get("unique_form_count"), len(forms))
        self.assertEqual(coverage.get("required_entry_count"), len(headwords | forms))
        self.assertEqual(coverage.get("entry_count"), len(entries))
        self.assertEqual(coverage.get("headwords_with_detail"), detail_count)
        self.assertEqual(coverage.get("detail_coverage"), round(detail_count / len(headwords), 6))
        self.assertRegex(subset.get("source", {}).get("sha256", ""), r"^[0-9A-F]{64}$")


if __name__ == "__main__":
    unittest.main(verbosity=2)
