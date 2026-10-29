"""从 WordNet 导出派生词关系，供词表构建器做「词族折叠」。

输出：
  data/derived.json        {"word": ["derived1", ...], ...}
  data/derived_stats.txt   规模统计 + 抽样词完整派生列表
"""
from __future__ import annotations

import json
import re
from pathlib import Path

try:
    from nltk.corpus import wordnet as wn
except ImportError as exc:
    raise SystemExit("缺少 nltk；无法生成 derived.json。先安装 requirements.txt") from exc

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
OUT_JSON = DATA_DIR / "derived.json"
OUT_STATS = DATA_DIR / "derived_stats.txt"

VALID_WORD = re.compile(r"^[a-z]{3,}$")


def is_valid(word: str) -> bool:
    return bool(VALID_WORD.fullmatch(word))


def main() -> None:
    try:
        wn.ensure_loaded()
    except LookupError as exc:
        raise SystemExit("缺少 NLTK wordnet 语料；拒绝生成空 derived.json") from exc

    directed: set[tuple[str, str]] = set()

    for synset in wn.all_synsets():
        for lemma in synset.lemmas():
            a = lemma.name().lower()
            if not is_valid(a):
                continue
            for related in lemma.derivationally_related_forms():
                b = related.name().lower()
                if a == b or not is_valid(b):
                    continue
                directed.add((a, b))
                directed.add((b, a))

    if not directed:
        raise SystemExit("WordNet 未产生派生关系；拒绝写出空 derived.json")

    word_map: dict[str, set[str]] = {}
    for a, b in directed:
        word_map.setdefault(a, set()).add(b)
    if not word_map:
        raise SystemExit("WordNet 派生词映射为空；拒绝写出空 derived.json")

    sorted_map = {key: sorted(values) for key, values in sorted(word_map.items())}

    # 无向关系对数：每对 (a, b) 只计一次
    undirected = {(min(a, b), max(a, b)) for a, b in directed}

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_JSON.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(sorted_map, fh, ensure_ascii=False, indent=1)
        fh.write("\n")

    samples = ["care", "fine", "form", "take", "act", "nation"]
    lines = [
        "WordNet 派生词关系导出统计",
        f"总词条数: {len(sorted_map)}",
        f"总关系对数(无向，去重): {len(undirected)}",
        f"总关系对数(有向，含双向): {len(directed)}",
        "",
        "抽样词完整派生列表:",
    ]
    for word in samples:
        related = sorted_map.get(word, [])
        lines.append(f"{word} ({len(related)}): {', '.join(related) if related else '(无)'}")

    OUT_STATS.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"words={len(sorted_map)} undirected={len(undirected)} directed={len(directed)}")
    for word in samples:
        print(f"{word}: {', '.join(sorted_map.get(word, []))}")


if __name__ == "__main__":
    main()
