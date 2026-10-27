# -*- coding: utf-8 -*-
"""Ask Claude for a conservative second-pass review of core-list entries."""
from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "selection_review.json"
CLAUDE = shutil.which("claude.cmd") or shutil.which("claude")
BATCH = 400
WORKERS = 2


def load(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def parse_obj(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        raise ValueError("no JSON object")
    return json.loads(text[a:b + 1])


def prompt(items: list[dict]) -> str:
    payload = [{k: x[k] for k in ("word", "meaning", "band", "source_tier", "coverage", "book_rank")} for x in items]
    return f"""
你是考研英语二词库的保守审校员。请从下面词表中只标出“明确不该占用核心背诵时间”的词。

删除类别仅限：
1. 初中/高中绝对基础词，且没有英语二特殊常考义（例如 go/get/make/take/good/answer）。
2. 题型模板词或卷面操作词（例如 paragraph/title/author 这类只因题干反复出现而高频的词）。
3. 专有名词、国家/机构/人名。
4. 单篇偶然主题词，明显不具备跨文章价值。
5. 明显超纲且英语二核心价值很低的生僻词。

必须保留：
- economy, economic, research, policy, technology, education, environment, government, business, industry, society, culture 等虽然常见但属于考研核心的学术词。
- address, issue, approach, sustain, yield 等有英语二特殊常考义的多义词。
- 学术、经济、社会、教育、科技、心理、环境、管理类核心词。
- 你不确定的词一律不要删。

只输出严格 JSON：{{"remove":[{{"word":"单词","category":"基础词|题型词|专名|偶然主题词|不值得背","reason":"不超过15字"}}]}}
不要输出未删除的词，不要 Markdown。

输入：
{json.dumps(payload, ensure_ascii=False)}
""".strip()


def run(batch: list[dict], i: int) -> list[dict]:
    proc = subprocess.run(
        [CLAUDE, "-p", "--output-format", "text"],
        input=prompt(batch), text=True, encoding="utf-8", errors="replace",
        capture_output=True, timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-400:])
    obj = parse_obj(proc.stdout)
    wanted = {x["word"] for x in batch}
    result = []
    for row in obj.get("remove", []):
        word = str(row.get("word", "")).lower().strip()
        if word in wanted:
            result.append({
                "word": word,
                "category": str(row.get("category", "不值得背"))[:20],
                "reason": str(row.get("reason", ""))[:40],
            })
    return result


def main() -> None:
    rows = load(DATA / "words.json", [])
    batches = [rows[i:i + BATCH] for i in range(0, len(rows), BATCH)]
    merged = load(OUT, {})
    if isinstance(merged, list):
        merged = {x["word"]: x for x in merged}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(run, batch, i + 1): i + 1 for i, batch in enumerate(batches)}
        for future in as_completed(futures):
            i = futures[future]
            try:
                result = future.result()
                for row in result:
                    merged[row["word"]] = row
                OUT.write_text(json.dumps(sorted(merged.values(), key=lambda x: x["word"]), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
                print(f"batch {i}/{len(batches)} flagged={len(result)} total={len(merged)}")
            except Exception as exc:
                print(f"batch {i} ERROR {type(exc).__name__}: {exc}")
    print("done", len(merged))


if __name__ == "__main__":
    main()
