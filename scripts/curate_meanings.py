# -*- coding: utf-8 -*-
"""Curate one-line English II core meanings with Claude, in resumable batches."""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BOOK_DIR = ROOT / "ref" / "kaoyan-vocab5" / "data"
OUT = DATA / "meanings_curated.json"
BATCH_SIZE = 60
WORKERS = 3
CLAUDE = shutil.which("claude.cmd") or shutil.which("claude")


def load_json(path: Path, default):
    if not path.exists():
        return default
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def load_books() -> dict[str, dict]:
    out = {}
    for path in sorted(BOOK_DIR.glob("c*.json")):
        out.update(load_json(path, {}).get("words", {}))
    return out


def parse_json_object(text: str) -> dict[str, str]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in response")
    obj = json.loads(text[start:end + 1])
    if not isinstance(obj, dict):
        raise ValueError("response is not a JSON object")
    return {str(k).strip().lower(): str(v).strip() for k, v in obj.items()}


def clean_meaning(value: str) -> str:
    value = value.replace("；", "；").replace(";", "；").strip()
    value = re.sub(r"\s+", " ", value)
    value = value.strip("； ,，。.")
    # Prefer at most two senses.
    parts = [p.strip() for p in value.split("；") if p.strip()]
    return "；".join(parts[:2])


def prompt_for(batch: list[dict]) -> str:
    payload = []
    for item in batch:
        payload.append({
            "word": item["word"],
            "draft": item["draft"],
            "senses": item["senses"][:5],
            "usage": item["usage"][:220],
            "phrases": item["phrases"][:4],
        })
    return f"""
你是考研英语二核心词库审校员。请为下面每个单词给出“看到英文时应反应出的中文核心义”。

规则：
1. 只输出严格 JSON 对象，格式 {{"单词":"释义"}}，不要 Markdown、解释或例句。
2. 默认只给 1 个核心义；只有多义都高频且无法合并时，才用“；”分隔最多 2 个义项。
3. 不写词性、音标、英文、括号说明、生僻义、超纲义。
4. 优先选择考研英语二阅读、翻译、写作中最常考的义项，而不是词典第一义。
5. 同义项合并，释义尽量 2-10 个汉字。
6. 参考示例：address=处理；解决；issue=问题；议题；approach=方法；途径；sustain=维持；支撑；yield=产生；产量；product=产品；productivity=生产率；consumer=消费者。
7. 必须覆盖输入中的每一个单词，键名保持原样。

输入：
{json.dumps(payload, ensure_ascii=False)}
""".strip()


def run_batch(batch: list[dict], index: int) -> dict[str, str]:
    prompt = prompt_for(batch)
    proc = subprocess.run(
        [CLAUDE, "-p", "--output-format", "text"],
        input=prompt,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=240,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"batch {index}: claude exited {proc.returncode}: {proc.stderr[-500:]}")
    result = parse_json_object(proc.stdout)
    wanted = {item["word"] for item in batch}
    cleaned = {}
    for word, meaning in result.items():
        if word not in wanted:
            continue
        meaning = clean_meaning(meaning)
        if meaning and len(meaning) <= 24:
            cleaned[word] = meaning
    missing = wanted - set(cleaned)
    if missing:
        print(f"  batch {index}: missing {len(missing)} words", flush=True)
    return cleaned


def main() -> None:
    if not CLAUDE:
        raise SystemExit("claude CLI not found")
    rows = load_json(DATA / "words.json", [])
    books = load_books()
    curated = load_json(OUT, {})

    pending = []
    for row in rows:
        word = row["word"]
        if word in curated:
            continue
        item = books.get(word, {})
        pending.append({
            "word": word,
            "draft": row.get("meaning", ""),
            "senses": item.get("senses") or [],
            "usage": item.get("usage") or "",
            "phrases": [p.get("p", "") + " " + p.get("m", "") for p in (item.get("phrases") or [])],
        })
    print(f"selected={len(rows)} cached={len(curated)} pending={len(pending)}", flush=True)
    if not pending:
        return

    batches = [pending[i:i + BATCH_SIZE] for i in range(0, len(pending), BATCH_SIZE)]
    print(f"batches={len(batches)} size={BATCH_SIZE} workers={WORKERS}", flush=True)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(run_batch, batch, i + 1): i + 1 for i, batch in enumerate(batches)}
        for future in as_completed(futures):
            i = futures[future]
            try:
                cleaned = future.result()
                curated.update(cleaned)
                with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
                    json.dump(curated, f, ensure_ascii=False, indent=1, sort_keys=True)
                    f.write("\n")
                print(f"batch {i:>2}/{len(batches)} +{len(cleaned)} total={len(curated)}", flush=True)
            except Exception as exc:
                print(f"batch {i:>2} ERROR {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)

    print(f"done curated={len(curated)}/{len(rows)}")


if __name__ == "__main__":
    main()

