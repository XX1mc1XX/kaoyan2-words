#!/usr/bin/env python3
"""Build a small, trackable ECDICT subset for app detail rendering.

The full ECDICT CSV is large and gitignored. This script extracts only the
entries needed by the four published decks: every headword plus every form
referenced by a deck. The resulting JSON is deterministic and can be committed.

Contract (schema_version 1):
  field_names = ["phonetic", "translation", "tag", "exchange"]
  entries[word] = [phonetic, translation, tag, exchange]

All map keys and all four values are strings. Deck headwords and deck forms are
lowercased exactly as the existing detail builder does. Consumers may treat an
empty string as "field absent".
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
DEFAULT_ECDICT = DATA / "ecdict.csv"
DEFAULT_OUTPUT = DATA / "ecdict_subset.json"
DECK_FILES = ("words.json", "derivatives.json", "basic.json", "insurance.json")
FIELD_NAMES = ("phonetic", "translation", "tag", "exchange")
SCHEMA_VERSION = 1
MIN_DETAIL_HEADWORDS = 3350
MAX_OUTPUT_BYTES = 3 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024
DOMAIN_TAG_RE = re.compile(r"^(?:\[[^\]]+\]\s*)+")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def load_deck_words() -> tuple[dict[str, int], set[str], set[str]]:
    deck_counts: dict[str, int] = {}
    headwords: set[str] = set()
    forms: set[str] = set()
    owners: dict[str, str] = {}
    for filename in DECK_FILES:
        path = DATA / filename
        if not path.is_file():
            raise SystemExit(f"缺少必需词库输入: {path}")
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"词库 JSON 损坏: {path}: {exc}") from exc
        if not isinstance(rows, list) or not rows:
            raise SystemExit(f"词库输入必须是非空数组: {path}")
        deck_counts[path.stem] = len(rows)
        for row in rows:
            if not isinstance(row, dict):
                raise SystemExit(f"词库条目类型错误: {path}")
            word = str(row.get("word", "")).strip().lower()
            if not word:
                raise SystemExit(f"词库条目缺少 word: {path}")
            if word in owners and owners[word] != path.stem:
                raise SystemExit(f"四词库 headword 重复: {word} ({owners[word]} / {path.stem})")
            owners[word] = path.stem
            headwords.add(word)
            values = row.get("forms") or []
            if not isinstance(values, list):
                raise SystemExit(f"{path.stem}/{word} 的 forms 必须是数组")
            for value in values:
                form = str(value).strip().lower()
                if form and form != word:
                    forms.add(form)
    return deck_counts, headwords, forms


def read_ecdict(path: Path, needed: set[str]) -> dict[str, list[str]]:
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit(f"缺少必需重建源或文件为空: {path}")
    entries: dict[str, list[str]] = {}
    with path.open(encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        required_columns = {"word", *FIELD_NAMES}
        missing_columns = sorted(required_columns - set(reader.fieldnames or ()))
        if missing_columns:
            raise SystemExit(f"ECDICT 缺少列 {missing_columns}: {path}")
        for row in reader:
            word = (row.get("word") or "").strip().lower()
            if word not in needed or word in entries:
                continue
            entries[word] = [(row.get(field) or "").strip() for field in FIELD_NAMES]
    missing = sorted(needed - set(entries))
    if missing:
        raise SystemExit(f"ECDICT 缺少 {len(missing)} 个所需条目: {missing[:20]}")
    return entries


def has_detail(entry: list[str]) -> bool:
    translation = entry[1].replace("\\n", "\n")
    for line in translation.split("\n"):
        line = DOMAIN_TAG_RE.sub("", line.strip()).strip()
        if line:
            return True
    return False


def build_payload(ecdict_path: Path, output_path: Path) -> tuple[dict, bytes]:
    deck_counts, headwords, forms = load_deck_words()
    needed = headwords | forms
    entries = read_ecdict(ecdict_path, needed)
    detail_count = sum(has_detail(entries[word]) for word in headwords)
    if detail_count < MIN_DETAIL_HEADWORDS:
        raise SystemExit(
            f"详情覆盖不足: {detail_count}/{len(headwords)}，"
            f"要求至少 {MIN_DETAIL_HEADWORDS}"
        )
    coverage = {
        "headword_count": len(headwords),
        "unique_form_count": len(forms),
        "required_entry_count": len(needed),
        "entry_count": len(entries),
        "headwords_with_detail": detail_count,
        "detail_coverage": round(detail_count / len(headwords), 6),
    }
    try:
        source_name = ecdict_path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        source_name = ecdict_path.name
    payload = {
        "schema_version": SCHEMA_VERSION,
        "field_names": list(FIELD_NAMES),
        "entry_encoding": "entries[lowercase_word] = [phonetic, translation, tag, exchange]",
        "source": {
            "path": source_name,
            "size_bytes": ecdict_path.stat().st_size,
            "sha256": sha256(ecdict_path),
        },
        "decks": deck_counts,
        "coverage": coverage,
        "entries": {word: entries[word] for word in sorted(entries)},
    }
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    encoded = text.encode("utf-8")
    if len(encoded) >= MAX_OUTPUT_BYTES:
        raise SystemExit(f"subset 体积 {len(encoded)} bytes，必须小于 {MAX_OUTPUT_BYTES} bytes")
    print(
        f"decks={deck_counts} headwords={len(headwords)} forms={len(forms)} "
        f"entries={len(entries)} detail={detail_count}/{len(headwords)} "
        f"bytes={len(encoded)} output={output_path}",
        flush=True,
    )
    return payload, encoded


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ecdict", type=Path, default=DEFAULT_ECDICT, help="完整 ECDICT CSV 重建源")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="输出 subset JSON")
    parser.add_argument("--check", action="store_true", help="只校验现有 subset 是否可由当前输入精确复现")
    args = parser.parse_args()

    _, encoded = build_payload(args.ecdict, args.output)
    if args.check:
        if not args.output.is_file():
            raise SystemExit(f"subset 不存在: {args.output}")
        actual = args.output.read_bytes()
        if actual != encoded:
            raise SystemExit(f"subset 已过期，请重新运行 {Path(__file__).name}")
        print("subset check: exact match", flush=True)
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_name(args.output.name + ".tmp")
    try:
        temp.write_bytes(encoded)
        os.replace(temp, args.output)
    finally:
        temp.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())