# -*- coding: utf-8 -*-
"""Audit curated meanings for clearly wrong or dangerously narrow core senses."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BOOK_DIR = ROOT / "ref" / "kaoyan-vocab5" / "data"
OUT = DATA / "meaning_corrections.json"
CLAUDE = shutil.which("claude.cmd") or shutil.which("claude")
BATCH = 90
WORKERS = 3


def load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def load_books():
    out = {}
    for path in sorted(BOOK_DIR.glob("c*.json")):
        out.update(load(path, {}).get("words", {}))
    return out


def parse(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        raise ValueError("no JSON object")
    return json.loads(text[a:b + 1])


def prompt(items):
    return f"""
你是考研英语一/英语二核心释义审校员。输入包含单词、当前核心义、词书义项和用法。
任务：只修“明显错误、过度狭窄、会误导读者”的核心义；如果当前释义可接受，直接省略该词。

重点检查：
1. 只写了名词义，却漏掉高频形容词/动词义，例如 auto=汽车 漏掉“自动”。
2. 只写了字面义，却漏掉考研阅读常考引申义，例如 address 应优先“处理”。
3. 两个词性都常考且无法合并时，最多保留两个义项，用“；”分隔。
4. 不要添加生僻义、专业义、词性标记、音标、英文、括号、例句。
5. 不确定就不要改。大部分词应原样保留。
6. 目标：给出看到英文时最能让考研读者理解文章的核心中文义。

只输出严格 JSON 对象：{{"单词":"修正后的释义"}}。不要输出未修改词，不要 Markdown。
参考：auto=自动；汽车；address=处理；issue=问题；发行；yield=产生；产量；firm=公司；坚定的。

输入：
{json.dumps(items, ensure_ascii=False)}
""".strip()


def run(batch, i):
    proc = subprocess.run(
        [CLAUDE, "-p", "--output-format", "text"],
        input=prompt(batch), text=True, encoding="utf-8", errors="replace",
        capture_output=True, timeout=240,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-500:])
    obj = parse(proc.stdout)
    wanted = {x["word"] for x in batch}
    result = {}
    for word, value in obj.items():
        word = str(word).strip().lower()
        if word not in wanted:
            continue
        value = str(value).replace(";", "；").strip()
        parts = [p.strip() for p in value.split("；") if p.strip()]
        if parts:
            result[word] = "；".join(parts[:2])[:24]
    return result


def main():
    words = load(DATA / "words.json", [])
    curated = load(DATA / "meanings_final.json", {})
    books = load_books()
    items = []
    for row in words:
        word = row["word"]
        item = books.get(word, {})
        items.append({
            "word": word,
            "current": curated.get(word) or row["meaning"],
            "senses": (item.get("senses") or [])[:4],
            "usage": (item.get("usage") or "")[:180],
        })
    batches = [items[i:i+BATCH] for i in range(0, len(items), BATCH)]
    merged = load(OUT, {})
    print(f"words={len(items)} batches={len(batches)} cached={len(merged)}", flush=True)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(run, b, i+1): i+1 for i, b in enumerate(batches)}
        for future in as_completed(futures):
            i = futures[future]
            try:
                result = future.result()
                merged.update(result)
                OUT.write_text(json.dumps(merged, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
                print(f"batch {i}/{len(batches)} corrected={len(result)} total={len(merged)}", flush=True)
            except Exception as exc:
                print(f"batch {i} ERROR {type(exc).__name__}: {exc}", flush=True)
    print("done", len(merged), flush=True)


if __name__ == "__main__":
    main()
