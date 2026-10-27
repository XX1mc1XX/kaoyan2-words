# -*- coding: utf-8 -*-
"""Core regression checks for the English II vocabulary data and mobile app.

Run from the project root:
    python -m unittest -v scripts/test_core.py
"""
from __future__ import annotations

import collections
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WORDS_PATH = ROOT / "data" / "words.json"
SUMMARY_PATH = ROOT / "data" / "selection_summary.json"
DERIVATIVES_PATH = ROOT / "data" / "derivatives.json"
BASIC_PATH = ROOT / "data" / "basic.json"
INSURANCE_PATH = ROOT / "data" / "insurance.json"
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


class CoreRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.words = load_json(WORDS_PATH)
        cls.derivatives = load_json(DERIVATIVES_PATH)
        cls.basic = load_json(BASIC_PATH)
        cls.insurance = load_json(INSURANCE_PATH)
        cls.summary = load_json(SUMMARY_PATH)
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

    def test_07_embedded_html_data_matches_words_json(self) -> None:
        self.assertTrue(HTML_PATH.is_file(), f"generated HTML not found: {HTML_PATH}")
        match = re.search(
            r"const\s+WORDS\s*=\s*(\[.*?\]);",
            self.html,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "could not find embedded WORDS data in generated HTML")
        embedded = json.loads(match.group(1))
        self.assertEqual(len(embedded), len(self.words))
        self.assertEqual(
            [word.get("id") for word in embedded],
            [word.get("id") for word in self.words],
        )
        derivative_match = re.search(
            r"const\s+DERIVATIVES\s*=\s*(\[.*?\]);",
            self.html,
            re.DOTALL,
        )
        self.assertIsNotNone(derivative_match, "could not find embedded DERIVATIVES data")
        embedded_derivatives = json.loads(derivative_match.group(1))
        self.assertEqual(len(embedded_derivatives), len(self.derivatives))
        for constant, rows in (("BASIC", self.basic), ("INSURANCE", self.insurance)):
            match = re.search(rf"const\s+{constant}\s*=\s*(\[.*?\]);", self.html, re.DOTALL)
            self.assertIsNotNone(match, f"could not find embedded {constant} data")
            embedded_optional = json.loads(match.group(1))
            self.assertEqual(len(embedded_optional), len(rows))
            self.assertFalse(contains_key(embedded_optional, "phonetic"))
        self.assertFalse(contains_key(embedded, "phonetic"))
        self.assertFalse(contains_key(embedded_derivatives, "phonetic"))
        self.assertNotIn("phonetic", self.html.lower(), "generated HTML still mentions phonetic")

    def test_08_required_mobile_features_and_events_exist(self) -> None:
        required_strings = {
            "meaning toggle control": 'id="meaningToggle"',
            "meaning toggle implementation": "function toggleMeaning",
            "persistent meaning preference": "autoShow",
            "position display": 'id="position"',
            "position wording": "第 ",
            "navigation implementation": "function navigate",
            "vertical swipe direction": "navigate(dy < 0 ? 1 : -1)",
            "priority display": "word.priority",
            "priority rank": "priority_rank",
            "priority filter": "priorityFilter",
            "forms section": 'id="formsBox"',
            "forms rendering": "word.forms",
            "forms label": "考查形式",
            "keyboard previous": "'ArrowUp'",
            "keyboard next": "'ArrowDown'",
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

if __name__ == "__main__":
    unittest.main(verbosity=2)
