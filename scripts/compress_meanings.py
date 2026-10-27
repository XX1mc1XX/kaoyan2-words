# -*- coding: utf-8 -*-
"""Compress curated meanings toward one core sense per word."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "meanings_final.json"
CLAUDE = shutil.which("claude.cmd") or shutil.which("claude")
BATCH = 140
WORKERS = 3


def load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


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
你是考研英语二词库的释义压缩审校员。输入是单词和当前释义。
请把释义压缩成“看到英文时最该反应出的中文核心义”。

规则：
1. 只输出严格 JSON 对象 {{"单词":"核心义"}}，不要解释。
2. 目标至少 85% 的单词只保留 1 个义项。
3. 如果两个义项是同义、近义、同一概念的展开，合并成一个，例如“技术；科技”=“技术”，“积极的；肯定的”=“积极的”，“权力；力量”=“权力”，“方法；途径”=“方法”，“执行；表演”按考试高频保留“执行”。
4. 只有两个义项在词性或考试语义上明显不同、删掉会误导读者时，才用“；”保留两个，例如 issue=问题；发行，yield=产生；产量，address=处理；解决（这里可压成处理）。
5. 不得新增输入中没有的义项，不得增加词性、音标、英文、括号或例句。
6. 每个释义尽量 2-8 个汉字，最多 12 个汉字。
7. 必须覆盖每一个输入单词，键名保持原样。

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
    out = {}
    for word, value in obj.items():
        word = str(word).strip().lower()
        if word not in wanted:
            continue
        value = str(value).replace(";", "；").strip()
        parts = [p.strip() for p in value.split("；") if p.strip()]
        value = "；".join(parts[:2])[:24]
        if value:
            out[word] = value
    return out


def main():
    words = load(DATA / "words.json", [])
    curated = load(DATA / "meanings_curated.json", {})
    prior = load(OUT, {})
    items = [
        {"word": w["word"], "current": curated.get(w["word"]) or w["meaning"]}
        for w in words if w["word"] not in prior
    ]
    batches = [items[i:i + BATCH] for i in range(0, len(items), BATCH)]
    print(f"words={len(items)} batches={len(batches)}", flush=True)
    merged = dict(prior)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(run, b, i + 1): i + 1 for i, b in enumerate(batches)}
        for future in as_completed(futures):
            i = futures[future]
            try:
                result = future.result()
                merged.update(result)
                OUT.write_text(json.dumps(merged, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
                print(f"batch {i}/{len(batches)} +{len(result)} total={len(merged)}", flush=True)
            except Exception as exc:
                print(f"batch {i} ERROR {type(exc).__name__}: {exc}", flush=True)
    final = {w["word"]: merged[w["word"]] for w in words if w["word"] in merged}
    OUT.write_text(json.dumps(final, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    multi = sum("；" in v for v in final.values())
    print(f"done={len(final)} multi={multi} ratio={multi/max(1,len(final)):.1%}", flush=True)


if __name__ == "__main__":
    main()
